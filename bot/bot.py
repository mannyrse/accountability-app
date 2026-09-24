import os
import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_BOT_TOKEN")

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")


@bot.tree.command(name="ping", description="Test that the bot is alive")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("Pong bitch")


@bot.event
async def on_connect():
    await bot.tree.sync()


bot.run(TOKEN)