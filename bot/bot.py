import os
import random
import discord
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv
from app.database import SessionLocal
from app.models import Habit, Points, Reward, PointTransaction, PendingNotification, DailyReport, Redemption
from datetime import datetime, timezone

load_dotenv()

TOKEN = os.getenv("DISCORD_BOT_TOKEN")

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.tree.command(name="points", description="Check current and lifetime points")
async def points(interaction: discord.Interaction):
    db = SessionLocal()
    points_row = db.query(Points).first()
    db.close()
    await interaction.response.send_message(
        f"Current points: {points_row.current_points}\nLifetime points: {points_row.lifetime_points}"
    )


@bot.tree.command(name="rewards", description="View the reward shop")
async def rewards(interaction: discord.Interaction):
    db = SessionLocal()
    reward_list = db.query(Reward).filter(Reward.active == True).all()
    points_row = db.query(Points).first()
    db.close()

    if not reward_list:
        await interaction.response.send_message("No rewards available yet.")
        return

    message = "**Reward Shop**\n"
    for reward in reward_list:
        message += f"• {reward.name} — {reward.point_cost} pts\n"
        if reward.description:
            message += f"   _{reward.description}_\n"
    message += f"\nAvailable points: {points_row.current_points}"

    await interaction.response.send_message(message)


async def reward_autocomplete(interaction: discord.Interaction, current: str):
    db = SessionLocal()
    reward_list = db.query(Reward).filter(Reward.active == True).all()
    db.close()
    return [
        discord.app_commands.Choice(name=reward.name, value=reward.id)
        for reward in reward_list
        if current.lower() in reward.name.lower()
    ][:25]


@bot.tree.command(name="redeem", description="Redeem a reward using your points")
@discord.app_commands.autocomplete(reward_id=reward_autocomplete)
async def redeem(interaction: discord.Interaction, reward_id: int):
    db = SessionLocal()
    reward = db.query(Reward).filter(Reward.id == reward_id).first()
    points_row = db.query(Points).first()

    if points_row.current_points >= reward.point_cost:
        transaction = PointTransaction(
            amount=-reward.point_cost,
            type="reward",
            reason=reward.name,
        )
        db.add(transaction)
        points_row.current_points -= reward.point_cost

        redemption = Redemption(
            reward_name=reward.name,
            point_cost=reward.point_cost,
            completed=False,
        )
        db.add(redemption)

        db.commit()
        message = f"Redeemed **{reward.name}** for {reward.point_cost} points! Remaining: {points_row.current_points}"
    else:
        message = f"Not enough points. You have {points_row.current_points}, but {reward.name} costs {reward.point_cost}."

    db.close()
    await interaction.response.send_message(message)

@bot.tree.command(
    name="gamble",
    description="Let's go gambling! 50/50 chance to win or lose your wager."
)
@app_commands.describe(amount="How many points to wager")
async def gamble(interaction: discord.Interaction, amount: app_commands.Range[int, 1]):

    await interaction.response.defer()

    db = SessionLocal()

    try:
        points_row = db.query(Points).first()

        if points_row is None:

            await interaction.followup.send(
                "No points account exists yet.",
                ephemeral=True,
            )
            return


        if amount > points_row.current_points:
            balance = points_row.current_points

            await interaction.followup.send(
                f"You only have **{balance}** points. You can't wager {amount}.",
                ephemeral=True,
            )
            return

        # Simple 50/50
        won = random.choice([True, False])
        if won:
            points_row.current_points += amount
            db.add(PointTransaction(amount=amount, type="gamble", reason=f"Gamble won ({amount})"))
            result = f"🟢 **You won!** You gained **{amount}** points."
        else:
            points_row.current_points -= amount
            db.add(PointTransaction(amount=-amount, type="gamble", reason=f"Gamble lost ({amount})"))
            result = f"🔴 **You lost!** You lost **{amount}** points. lol"


        # Force SQLAlchemy to send the UPDATE to PostgreSQL
        db.flush()

        # Commit the transaction
        db.commit()

        new_balance = points_row.current_points

        await interaction.followup.send(
            f"{result}\n\n"
            f"Balance: **{new_balance}** points."
        )


    except Exception as e:
        print(f"GAMBLE ERROR: {type(e).__name__}: {e}")

        db.rollback()

        try:
            await interaction.followup.send(
                "Something went wrong processing the gamble.",
                ephemeral=True,
            )
        except discord.HTTPException:
            pass

    finally:
        db.close()
        print("GAMBLE: database closed")

@tasks.loop(seconds=30)
async def check_pending_notifications():
    db = SessionLocal()
    now = datetime.now(timezone.utc)

    due = db.query(PendingNotification).filter(
        PendingNotification.status == "pending",
        PendingNotification.scheduled_at <= now,
    ).all()

    channel = bot.get_channel(int(os.getenv("DISCORD_CHANNEL_ID")))

    for notification in due:
        habit = db.query(Habit).filter(Habit.id == notification.habit_id).first()
        await channel.send(f"🚨 Bad habit alert: **{habit.name}** was checked off.")
        notification.status = "sent"

    db.commit()
    db.close()


@tasks.loop(seconds=30)
async def check_daily_reports():
    db = SessionLocal()

    due = db.query(DailyReport).filter(DailyReport.status == "pending").all()

    channel = bot.get_channel(int(os.getenv("DISCORD_CHANNEL_ID")))

    for report in due:
        await channel.send(report.message)
        report.status = "sent"

    db.commit()
    db.close()

def _ts(dt) -> int:
    # Naive-UTC datetime from the DB -> unix timestamp for Discord's <t:...> markup,
    # which each person sees in their own timezone.
    return int(dt.replace(tzinfo=timezone.utc).timestamp())


@bot.tree.command(name="redeemed", description="See rewards that have been redeemed")
async def redeemed(interaction: discord.Interaction):
    db = SessionLocal()
    pending = (
        db.query(Redemption)
        .filter(Redemption.completed == False)
        .order_by(Redemption.redeemed_at.asc())
        .all()
    )
    done = (
        db.query(Redemption)
        .filter(Redemption.completed == True)
        .order_by(Redemption.redeemed_at.desc())
        .limit(5)
        .all()
    )

    if not pending and not done:
        db.close()
        await interaction.response.send_message("Nothing has been redeemed yet.")
        return

    message = "**⏳ Waiting to be claimed**\n"
    if pending:
        for r in pending:
            message += f"• {r.reward_name} — {r.point_cost} pts (redeemed <t:{_ts(r.redeemed_at)}:d>)\n"
    else:
        message += "_Nothing waiting._\n"

    if done:
        message += "\n**✅ Completed (last 5)**\n"
        for r in done:
            message += f"• {r.reward_name} — {r.point_cost} pts (redeemed <t:{_ts(r.redeemed_at)}:d>)\n"

    db.close()
    await interaction.response.send_message(message)


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
            await channel.send(f"✅ **{r.reward_name}** has been completed!")
            r.completion_announced = True
        db.commit()
    except Exception as e:
        # Without this, one failure would silently stop the loop for good.
        print(f"REDEMPTION NOTIFY ERROR: {type(e).__name__}: {e}")
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


@bot.event
async def on_connect():
    await bot.tree.sync()