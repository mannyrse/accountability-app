import os
import discord
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


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    if not check_pending_notifications.is_running():
        check_pending_notifications.start()
    if not check_daily_reports.is_running():
        check_daily_reports.start()


@bot.event
async def on_connect():
    await bot.tree.sync()
