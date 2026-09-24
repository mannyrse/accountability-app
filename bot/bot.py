import os
import discord
from discord.ext import commands
from dotenv import load_dotenv
from app.database import SessionLocal
from app.models import Habit, Points, Reward, PointTransaction

load_dotenv()

TOKEN = os.getenv("DISCORD_BOT_TOKEN")

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")

@bot.tree.command(name="points", description="Check current and lifetime points")
async def points(interaction: discord.Interaction):
    db = SessionLocal()
    points_row = db.query(Points).first()
    db.close()
    await interaction.response.send_message(
        f"Current points: {points_row.current_points}\nLifetime points: {points_row.lifetime_points}"
    )

@bot.event
async def on_connect():
    await bot.tree.sync()


bot.run(TOKEN)