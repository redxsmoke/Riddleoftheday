import discord
import datetime
import csv
import requests
import io
import json
import logging
from discord.ext import tasks
from datetime import time as dt_time, datetime, timedelta
import os
from discord import app_commands, ui

logging.basicConfig(level=logging.INFO)
print("💡 Riddle bot is running")

# CONFIG
TOKEN = os.getenv('DISCORD_BOT_TOKEN')
if not TOKEN:
    raise RuntimeError("❌ DISCORD_BOT_TOKEN environment variable not set!")

CHANNEL_ID = 1387520693859782867  # Your riddle channel ID
SUBMITTED_QUESTIONS_FILE = "submitted_questions.json"

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

# Load submitted riddles
try:
    with open(SUBMITTED_QUESTIONS_FILE, "r") as f:
        submitted_riddles = json.load(f)
except FileNotFoundError:
    submitted_riddles = []

used_riddle_indexes = set()

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

def save_submitted_riddles():
    with open(SUBMITTED_QUESTIONS_FILE, "w") as f:
        json.dump(submitted_riddles, f, indent=2)

def save_scores_and_streaks():
    with open("scores.json", "w") as f:
        json.dump(scores, f, indent=2)
    with open("streaks.json", "w") as f:
        json.dump(streaks, f, indent=2)

def get_unused_riddle_index():
    total = len(submitted_riddles)
    unused = [i for i in range(total) if i not in used_riddle_indexes]
    if not unused:
        used_riddle_indexes.clear()
        unused = list(range(total))
    import random
    chosen = random.choice(unused)
    used_riddle_indexes.add(chosen)
    return chosen

def append_usage_warning(question: str) -> str:
    # Check if fewer than 5 unused riddles remain
    total = len(submitted_riddles)
    unused_count = total - len(used_riddle_indexes)
    if unused_count < 5:
        note = "\n\n*(Less than 5 new riddles remain - submit a new riddle with /submit to add it to the queue)*"
        if note not in question:
            question += note
    return question

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
        "• `/submit <question> <answer>` - Submit a new riddle\n"
        "• `!score` - Show your current score and streak\n"
        "• `!leaderboard` - Show the leaderboard\n"
        "• `!next` - Next leaderboard page\n"
        "• `!prev` - Previous leaderboard page\n"
        "\nSubmit your answer by typing it directly in the riddle channel."
    )
    await interaction.response.send_message(commands_list, ephemeral=True)

@tree.command(name="submit", description="Submit a new riddle")
@app_commands.describe(question="Your riddle question", answer="The correct answer")
async def submit(interaction: discord.Interaction, question: str, answer: str):
    # Append the standard formatting
    formatted_question = f"@everyone {question.strip()} ***(Answer will be revealed later this evening)***"
    # Save submission with user id
    submitted_riddles.append({
        "question": formatted_question,
        "answer": answer.strip(),
        "user_id": str(interaction.user.id)
    })
    save_submitted_riddles()
    # Reset used riddles so new one can be used
    used_riddle_indexes.clear()
    await interaction.response.send_message(
        f"✅ Thanks for submitting a riddle, {interaction.user.mention}! You won't be able to answer your own submission.",
        ephemeral=True
    )

@tasks.loop(time=dt_time(hour=6, minute=0))  # 6:00 AM UTC
async def post_riddle():
    global current_riddle, correct_users
    if not submitted_riddles:
        print("⚠️ No riddles available to post!")
        return

    index = get_unused_riddle_index()
    riddle = submitted_riddles[index]

    current_riddle = {
        "question": append_usage_warning(riddle["question"]),
        "answer": riddle["answer"],
        "submitter_id": riddle.get("user_id", None)
    }
    correct_users = set()

    channel = client.get_channel(CHANNEL_ID)
    if channel:
        await channel.send(f"🧠 **Riddle of the Day:**\n{current_riddle['question']}\n\nSubmit your guess in this channel — your answer will be hidden!")
        logging.info("✅ Riddle posted")
    else:
        logging.warning("⚠️ Channel missing")

@tasks.loop(time=dt_time(hour=23, minute=0))  # 11:00 PM UTC
async def reveal_answer():
    global current_riddle, correct_users
    if not current_riddle:
        return

    channel = client.get_channel(CHANNEL_ID)
    correct_answer = normalize_answer(current_riddle["answer"])

    if channel:
        submitter_id = current_riddle.get("submitter_id")
        submitter_text = "Riddle of the Day bot"
        if submitter_id:
            try:
                submitter = await client.fetch_user(int(submitter_id))
                submitter_text = submitter.display_name
            except:
                pass

        if correct_users:
            lines = [f"✅ The correct answer was **{correct_answer}**!\n"]
            lines.append(f"Submitted by: {submitter_text}\n")
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
            await channel.send(f"❌ The correct answer was **{correct_answer}**. No one got it right today.\n\nSubmitted by: {submitter_text}")

        # Reset streaks for users who missed
        for uid in list(scores.keys()):
            if int(uid) not in correct_users:
                streaks[uid] = 0

        save_scores_and_streaks()

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

    # Leaderboard navigation
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

        # Prevent submitter from answering their own question
        if current_riddle.get("submitter_id") == user_id:
            await message.channel.send(f"{message.author.mention} ❌ You cannot answer your own submitted riddle.", delete_after=10)
            return

        try:
            await message.delete()
        except:
            pass

        if user_answer == correct_answer:
            correct_users.add(message.author.id)

        # Calculate countdown until next reveal at 23:00 UTC
        now = datetime.utcnow()
        reveal_time_today = datetime.combine(now.date(), dt_time(hour=23, minute=0))
        if now > reveal_time_today:
            reveal_time_today += timedelta(days=1)
        delta = reveal_time_today - now
        hours, remainder = divmod(int(delta.total_seconds()), 3600)
        minutes = remainder // 60

        await message.channel.send(
            f"{message.author.mention} ✅ Thanks for your submission! The answer will be revealed in {hours}h {minutes}m.",
            delete_after=10
        )

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
from keep_alive import keep_alive  # If you use a keep_alive.py file
keep_alive()
client.run(TOKEN)
