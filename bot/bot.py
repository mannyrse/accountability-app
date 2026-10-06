import os
import random
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv
from app.database import SessionLocal
from app.models import (
    Habit, Points, Reward, PointTransaction, PendingNotification,
    DailyReport, Redemption, User,
)
from datetime import datetime, timezone

load_dotenv()

TOKEN = os.getenv("DISCORD_BOT_TOKEN")

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

NOT_REGISTERED = "You haven't set up your account yet. Log in on the website first, then try again."
SELF_BLOCK = "You can't use this on yourself. It's for other people to use on your points."


# ---------- Helpers ----------

def get_user_by_discord_id(db, discord_id) -> Optional[User]:
    return db.query(User).filter(User.discord_id == str(discord_id)).first()


def get_points_row(db, user: User) -> Points:
    row = db.query(Points).filter(Points.user_id == user.id).first()
    if row is None:
        row = Points(user_id=user.id, current_points=0, lifetime_points=0)
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def resolve_target(db, interaction: discord.Interaction, member):
    """Whose points a command acts on. Anyone can run these commands; only the
    target needs an account. Returns (target, error)."""
    target = get_user_by_discord_id(db, member.id)
    if target is None:
        return None, f"{member.display_name} hasn't joined yet."
    if str(interaction.user.id) == target.discord_id:
        return target, SELF_BLOCK
    return target, None


def _option_value(interaction: discord.Interaction, name: str):
    """Raw value of another option the person has already filled in (used by autocomplete)."""
    for opt in (interaction.data or {}).get("options", []):
        if opt.get("name") == name:
            return opt.get("value")
    return None


def _ts(dt) -> int:
    # Naive-UTC datetime from the DB -> unix timestamp for Discord's <t:...> markup,
    # which each person sees in their own timezone.
    return int(dt.replace(tzinfo=timezone.utc).timestamp())


# ---------- Commands ----------

@bot.tree.command(name="points", description="Check points (yours, or another member's)")
@app_commands.describe(member="Whose points to check (leave empty for your own)")
async def points(interaction: discord.Interaction, member: Optional[discord.User] = None):
    db = SessionLocal()
    target_discord = member or interaction.user
    user = get_user_by_discord_id(db, target_discord.id)

    if user is None:
        db.close()
        if member is None:
            await interaction.response.send_message(NOT_REGISTERED, ephemeral=True)
        else:
            await interaction.response.send_message(
                f"{member.display_name} hasn't joined yet.", ephemeral=True
            )
        return

    points_row = get_points_row(db, user)
    message = (
        f"**{user.username}**\n"
        f"Current points: {points_row.current_points}\n"
        f"Lifetime points: {points_row.lifetime_points}"
    )
    db.close()
    await interaction.response.send_message(message)


@bot.tree.command(name="rewards", description="View someone's reward shop")
@app_commands.describe(member="Whose reward shop to view (leave empty for your own)")
async def rewards(interaction: discord.Interaction, member: Optional[discord.User] = None):
    db = SessionLocal()
    target_discord = member or interaction.user
    user = get_user_by_discord_id(db, target_discord.id)

    if user is None:
        db.close()
        if member is None:
            await interaction.response.send_message(NOT_REGISTERED, ephemeral=True)
        else:
            await interaction.response.send_message(
                f"{member.display_name} hasn't joined yet.", ephemeral=True
            )
        return

    reward_list = (
        db.query(Reward)
        .filter(Reward.user_id == user.id, Reward.active == True)
        .order_by(Reward.point_cost.asc())
        .all()
    )
    points_row = get_points_row(db, user)

    if not reward_list:
        db.close()
        await interaction.response.send_message(f"{user.username} has no rewards yet.")
        return

    message = f"**{user.username}'s Reward Shop**\n"
    for reward in reward_list:
        message += f"• {reward.name} — {reward.point_cost} pts\n"
        if reward.description:
            message += f"   _{reward.description}_\n"
    message += f"\n{user.username}'s points: {points_row.current_points}"

    db.close()
    await interaction.response.send_message(message)


async def reward_autocomplete(interaction: discord.Interaction, current: str):
    # Needs the member option filled in first, so we know whose shop to search.
    target_discord_id = _option_value(interaction, "member")
    if not target_discord_id:
        return []

    db = SessionLocal()
    target = get_user_by_discord_id(db, target_discord_id)
    if target is None:
        db.close()
        return []
    reward_list = (
        db.query(Reward)
        .filter(Reward.user_id == target.id, Reward.active == True)
        .order_by(Reward.point_cost.asc())
        .all()
    )
    db.close()
    return [
        app_commands.Choice(name=f"{reward.name} ({reward.point_cost} pts)", value=reward.id)
        for reward in reward_list
        if current.lower() in reward.name.lower()
    ][:25]


@bot.tree.command(name="redeem", description="Redeem a reward from someone's shop, spending their points")
@app_commands.describe(member="Whose reward shop to redeem from", reward_id="Which reward")
@app_commands.rename(reward_id="reward")
@app_commands.autocomplete(reward_id=reward_autocomplete)
async def redeem(interaction: discord.Interaction, member: discord.User, reward_id: int):
    db = SessionLocal()
    target, error = resolve_target(db, interaction, member)
    actor_name = interaction.user.display_name
    if error:
        db.close()
        await interaction.response.send_message(error, ephemeral=True)
        return

    reward = db.query(Reward).filter(
        Reward.id == reward_id, Reward.user_id == target.id, Reward.active == True
    ).first()
    if reward is None:
        db.close()
        await interaction.response.send_message(
            f"That reward isn't in {target.username}'s shop.", ephemeral=True
        )
        return

    points_row = get_points_row(db, target)

    if points_row.current_points < reward.point_cost:
        message = (
            f"{target.username} only has {points_row.current_points} points, "
            f"but {reward.name} costs {reward.point_cost}."
        )
        db.close()
        await interaction.response.send_message(message, ephemeral=True)
        return

    db.add(PointTransaction(
        user_id=target.id,
        amount=-reward.point_cost,
        type="reward",
        reason=f"{reward.name} (redeemed by {actor_name})",
    ))
    points_row.current_points -= reward.point_cost

    db.add(Redemption(
        user_id=target.id,
        redeemed_by_discord_id=str(interaction.user.id),
        redeemed_by_name=actor_name,
        reward_name=reward.name,
        point_cost=reward.point_cost,
        completed=False,
    ))
    db.commit()

    message = (
        f"🎯 **{actor_name}** redeemed **{reward.name}** from <@{target.discord_id}> "
        f"for {reward.point_cost} points!\n"
        f"{target.username} now has {points_row.current_points} points."
    )
    db.close()
    await interaction.response.send_message(message)


@bot.tree.command(
    name="gamble",
    description="Gamble someone else's points: 50/50 to double the wager or lose it."
)
@app_commands.describe(member="Whose points to gamble", amount="How many of their points to wager")
async def gamble(interaction: discord.Interaction, member: discord.User, amount: app_commands.Range[int, 1]):
    db = SessionLocal()

    try:
        target, error = resolve_target(db, interaction, member)
        actor_name = interaction.user.display_name
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return

        points_row = get_points_row(db, target)

        if amount > points_row.current_points:
            await interaction.response.send_message(
                f"{target.username} only has **{points_row.current_points}** points. You can't wager {amount}.",
                ephemeral=True,
            )
            return

        # Simple 50/50
        won = random.choice([True, False])
        if won:
            points_row.current_points += amount
            db.add(PointTransaction(
                user_id=target.id, amount=amount, type="gamble",
                reason=f"Gamble won ({amount}) by {actor_name}",
            ))
            result = (
                f"🟢 **{actor_name}** gambled **{amount}** of <@{target.discord_id}>'s points "
                f"and **won**! Doubled: **+{amount}**."
            )
        else:
            points_row.current_points -= amount
            db.add(PointTransaction(
                user_id=target.id, amount=-amount, type="gamble",
                reason=f"Gamble lost ({amount}) by {actor_name}",
            ))
            result = (
                f"🔴 **{actor_name}** gambled **{amount}** of <@{target.discord_id}>'s points "
                f"and **lost**. Those points are gone."
            )

        db.commit()
        new_balance = points_row.current_points

        await interaction.response.send_message(
            f"{result}\n\n{target.username} now has **{new_balance}** points."
        )

    except Exception as e:
        print(f"GAMBLE ERROR: {type(e).__name__}: {e}")
        db.rollback()
        try:
            if interaction.response.is_done():
                await interaction.followup.send("Something went wrong processing the gamble.", ephemeral=True)
            else:
                await interaction.response.send_message("Something went wrong processing the gamble.", ephemeral=True)
        except discord.HTTPException:
            pass

    finally:
        db.close()


@bot.tree.command(name="redeemed", description="See someone's redeemed rewards")
@app_commands.describe(member="Whose redemptions to view (leave empty for your own)")
async def redeemed(interaction: discord.Interaction, member: Optional[discord.User] = None):
    db = SessionLocal()
    target_discord = member or interaction.user
    user = get_user_by_discord_id(db, target_discord.id)

    if user is None:
        db.close()
        if member is None:
            await interaction.response.send_message(NOT_REGISTERED, ephemeral=True)
        else:
            await interaction.response.send_message(
                f"{member.display_name} hasn't joined yet.", ephemeral=True
            )
        return

    pending = (
        db.query(Redemption)
        .filter(Redemption.user_id == user.id, Redemption.completed == False)
        .order_by(Redemption.redeemed_at.asc())
        .all()
    )
    done = (
        db.query(Redemption)
        .filter(Redemption.user_id == user.id, Redemption.completed == True)
        .order_by(Redemption.redeemed_at.desc())
        .limit(5)
        .all()
    )

    if not pending and not done:
        db.close()
        await interaction.response.send_message(f"Nothing has been redeemed from {user.username} yet.")
        return

    def line(r):
        by_text = f" by {r.redeemed_by_name}" if r.redeemed_by_name else ""
        return f"• {r.reward_name} — {r.point_cost} pts (redeemed{by_text} <t:{_ts(r.redeemed_at)}:d>)\n"

    message = f"**{user.username}**\n\n**⏳ Owed**\n"
    if pending:
        for r in pending:
            message += line(r)
    else:
        message += "_Nothing owed._\n"

    if done:
        message += "\n**✅ Completed (last 5)**\n"
        for r in done:
            message += line(r)

    db.close()
    await interaction.response.send_message(message)


# ---------- Background loops ----------

@tasks.loop(seconds=30)
async def check_pending_notifications():
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        due = db.query(PendingNotification).filter(
            PendingNotification.status == "pending",
            PendingNotification.scheduled_at <= now,
        ).all()
        if not due:
            return

        channel = bot.get_channel(int(os.getenv("DISCORD_CHANNEL_ID")))
        if channel is None:
            return  # channel cache not ready yet; try again next loop

        for notification in due:
            habit = db.query(Habit).filter(Habit.id == notification.habit_id).first()
            owner = db.query(User).filter(User.id == habit.user_id).first() if habit else None
            who = f"<@{owner.discord_id}>" if owner else "Someone"
            name = habit.name if habit else "a habit"
            await channel.send(f"🚨 {who} Bad habit alert: **{name}** was checked off.")
            notification.status = "sent"
            db.commit()
    except Exception as e:
        print(f"NOTIFICATION ERROR: {type(e).__name__}: {e}")
        db.rollback()
    finally:
        db.close()


@tasks.loop(seconds=30)
async def check_daily_reports():
    db = SessionLocal()
    try:
        due = db.query(DailyReport).filter(DailyReport.status == "pending").all()
        if not due:
            return

        channel = bot.get_channel(int(os.getenv("DISCORD_CHANNEL_ID")))
        if channel is None:
            return

        for report in due:
            await channel.send(report.message)
            report.status = "sent"
            db.commit()
    except Exception as e:
        print(f"DAILY REPORT ERROR: {type(e).__name__}: {e}")
        db.rollback()
    finally:
        db.close()


@tasks.loop(seconds=30)
async def check_completed_redemptions():
    db = SessionLocal()
    try:
        due = (
            db.query(Redemption)
            .filter(Redemption.completed == True, Redemption.completion_announced == False)
            .order_by(Redemption.redeemed_at.asc())
            .all()
        )
        if not due:
            return

        channel = bot.get_channel(int(os.getenv("DISCORD_CHANNEL_ID")))
        if channel is None:
            return  # channel cache not ready yet; try again next loop

        for r in due:
            owner = db.query(User).filter(User.id == r.user_id).first()
            who = f"**{owner.username}**" if owner else "Someone"
            for_whom = (
                f" (redeemed by <@{r.redeemed_by_discord_id}>)" if r.redeemed_by_discord_id else ""
            )
            await channel.send(f"✅ {who} completed **{r.reward_name}**{for_whom}!")
            r.completion_announced = True
            db.commit()
    except Exception as e:
        # Without this, one failure would silently stop the loop for good.
        print(f"REDEMPTION NOTIFY ERROR: {type(e).__name__}: {e}")
        db.rollback()
    finally:
        db.close()


@tasks.loop(seconds=30)
async def check_redeem_announcements():
    db = SessionLocal()
    try:
        due = (
            db.query(Redemption)
            .filter(Redemption.redeem_announced == False)
            .order_by(Redemption.redeemed_at.asc())
            .all()
        )
        if not due:
            return

        channel = bot.get_channel(int(os.getenv("DISCORD_CHANNEL_ID")))
        if channel is None:
            return

        for r in due:
            owner = db.query(User).filter(User.id == r.user_id).first()
            if owner is None:
                r.redeem_announced = True
                db.commit()
                continue
            points_row = db.query(Points).filter(Points.user_id == owner.id).first()
            balance = points_row.current_points if points_row else 0
            by = r.redeemed_by_name or "Someone"
            await channel.send(
                f"🎯 **{by}** redeemed **{r.reward_name}** from <@{owner.discord_id}> "
                f"for {r.point_cost} points!\n{owner.username} now has {balance} points."
            )
            r.redeem_announced = True
            db.commit()
    except Exception as e:
        print(f"REDEEM ANNOUNCE ERROR: {type(e).__name__}: {e}")
        db.rollback()
    finally:
        db.close()

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    if not check_pending_notifications.is_running():
        check_pending_notifications.start()
    if not check_daily_reports.is_running():
        check_daily_reports.start()
    if not check_completed_redemptions.is_running():
        check_completed_redemptions.start()
    if not check_redeem_announcements.is_running():
        check_redeem_announcements.start()

@bot.event
async def on_connect():
    await bot.tree.sync()