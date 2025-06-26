import discord
import datetime
import csv
import requests
import io
import json
import logging
from discord.ext import tasks
from datetime import time
import os
from discord import app_commands

from keep_alive import keep_alive  # Optional, remove if unused

logging.basicConfig(level=logging.INFO)
print("💡 Riddle bot is running")

# CONFIG
TOKEN = os.getenv('DISCORD_BOT_TOKEN')
if not TOKEN:
    raise RuntimeError("❌ DISCORD_BOT_TOKEN environment variable not set!")

CHANNEL_ID = 1387520693859782867  # Your riddle channel ID
CSV_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vT8vzD0iw-M_16DPBN9J_WtvEGfS57nUFCKJJ4u1HFXs95BKEQYQ0wvKIvs8MRS0yRhBtTZJSIUeEjR/pub?output=csv"
START_DATE = datetime.date(2025, 6, 25)

# State
current_riddle = None
correct_users = set()
leaderboard_pages = {}

# Load persistent data
try:
    with open("scores.json", "r") as f:
        scores = json.load(f)
except FileNotFoundError:
    scores = {}

try:
    with open("streaks.json", "r") as f:
        streaks = json.load(f)
except FileNotFoundError:
    streaks = {}

# Intents
intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

def normalize_answer(ans: str) -> str:
    ans = ans.lower().strip()
    if ans.endswith("es"):
        ans = ans[:-2]
    elif ans.endswith("s"):
        ans = ans[:-1]
    return ans

@client.event
async def on_ready():
    print(f"✅ Logged in as {client.user}")
    await tree.sync()
    post_riddle.start()
    reveal_answer.start()

@tree.command(name="riddleoftheday", description="Show Riddle of the Day bot commands")
async def riddle_commands(interaction: discord.Interaction):
    commands_list = (
        "**Riddle of the Day Bot Commands:**\n"
        "• `/riddleoftheday` - Show this command list\n"
        "• `!score` - Show your current score and streak\n"
        "• `!leaderboard` - Show the leaderboard\n"
        "• `!next` - Next leaderboard page\n"
        "• `!prev` - Previous leaderboard page\n"
        "\nSubmit your answer by typing it directly in the riddle channel."
    )
    await interaction.response.send_message(commands_list, ephemeral=True)

def fetch_today_riddle():
    try:
        response = requests.get(CSV_URL)
        if response.status_code == 200:
            content = response.content.decode("utf-8")
            reader = csv.reader(io.StringIO(content))
            riddles = [row for row in reader if len(row) >= 2]

            days_since = (datetime.date.today() - START_DATE).days
            index = min(days_since, len(riddles) - 1)

            question, answer = riddles[index][0].strip(), riddles[index][1].strip()
            return {"question": question, "answer": answer}
        else:
            logging.error(f"❌ Google Sheet fetch failed: {response.status_code}")
    except Exception as e:
        logging.error(f"❌ Exception fetching riddles: {e}")
    return None

@tasks.loop(time=time(hour=19, minute=15))  # 7:15 PM UTC
async def post_riddle():
    global current_riddle, correct_users

    current_riddle = fetch_today_riddle()
    correct_users = set()

    channel = client.get_channel(CHANNEL_ID)
    if current_riddle and channel:
        await channel.send(
            f"🧠 **Riddle of the Day:**\n{current_riddle['question']}\n\nSubmit your guess in this channel — your answer will be hidden!"
        )
        logging.info("✅ Riddle posted")
    else:
        logging.warning("⚠️ Riddle or channel missing")

@tasks.loop(time=time(hour=0, minute=0))  # 12:00 AM UTC
async def reveal_answer():
    global current_riddle, correct_users

    if not current_riddle:
        return

    channel = client.get_channel(CHANNEL_ID)
    correct_answer = normalize_answer(current_riddle["answer"])

    if channel:
        if correct_users:
            lines = [f"✅ The correct answer was **{correct_answer}**!\n"]
            lines.append("The following users got it correct:")

            for uid in correct_users:
                uid_str = str(uid)
                scores[uid_str] = scores.get(uid_str, 0) + 1
                streaks[uid_str] = streaks.get(uid_str, 0) + 1
                user = await client.fetch_user(uid)
                lines.append(f"• {user.mention} (**{scores[uid_str]}** total, 🔥 {streaks[uid_str]} streak)")

            lines.append("\n📅 Stay tuned for tomorrow’s riddle!")
            await channel.send("\n".join(lines))
        else:
            await channel.send(f"❌ The correct answer was **{correct_answer}**. No one got it right today.")

        # Reset streaks for users who missed
        for uid in list(scores.keys()):
            if int(uid) not in correct_users:
                streaks[uid] = 0

        with open("scores.json", "w") as f:
            json.dump(scores, f, indent=2)
        with open("streaks.json", "w") as f:
            json.dump(streaks, f, indent=2)

    current_riddle = None
    correct_users.clear()

@client.event
async def on_message(message):
    if message.author == client.user:
        return

    user_id = str(message.author.id)
    msg = message.content.lower().strip()

    # Personal score
    if msg == "!score":
        score = scores.get(user_id, 0)
        streak = streaks.get(user_id, 0)
        await message.channel.send(f"📊 {message.author.display_name}'s score: **{score}**, 🔥 Streak: {streak}")
        return

    # Leaderboard
    elif msg.startswith("!leaderboard"):
        leaderboard_pages[user_id] = 0
        await show_leaderboard(message.channel, user_id)
        return

    elif msg == "!next":
        if user_id in leaderboard_pages:
            leaderboard_pages[user_id] += 1
            await show_leaderboard(message.channel, user_id)
        return

    elif msg == "!prev":
        if user_id in leaderboard_pages and leaderboard_pages[user_id] > 0:
            leaderboard_pages[user_id] -= 1
            await show_leaderboard(message.channel, user_id)
        return

    # Answer submission
    if current_riddle and message.channel.id == CHANNEL_ID:
        user_answer = normalize_answer(message.content)
        correct_answer = normalize_answer(current_riddle["answer"])

        try:
            await message.delete()
        except:
            pass

        if user_answer == correct_answer:
            correct_users.add(message.author.id)

        try:
            await message.channel.send(
                f"{message.author.mention} ✅ Thanks for your submission! The answer will be revealed at 00:00 UTC.",
                delete_after=10
            )
        except:
            pass

async def show_leaderboard(channel, user_id):
    page = leaderboard_pages.get(user_id, 0)
    sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    total_pages = max((len(sorted_scores) - 1) // 10 + 1, 1)
    page = min(page, total_pages - 1)

    embed = discord.Embed(
        title=f"🏆 Riddle Leaderboard (Page {page + 1}/{total_pages})",
        description="Top riddle solvers by total correct guesses",
        color=discord.Color.gold()
    )

    start = page * 10
    for i, (uid, score) in enumerate(sorted_scores[start:start+10], start=start + 1):
        user = await client.fetch_user(int(uid))
        streak = streaks.get(uid, 0)
        embed.add_field(
            name=f"{i}. {user.display_name}",
            value=f"Correct: **{score}**, 🔥 Streak: {streak}",
            inline=False
        )

    embed.set_footer(text="Use !next and !prev to navigate pages")
    await channel.send(embed=embed)

# Keep-alive for Railway or similar platforms (optional)
keep_alive()
client.run(TOKEN)
