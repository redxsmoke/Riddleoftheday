import discord
from discord.ext import tasks
from discord import app_commands
import asyncio
import json
import os
from datetime import datetime, time, timedelta, timezone
import random

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

QUESTIONS_FILE = "submitted_questions.json"
SCORES_FILE = "scores.json"
STREAKS_FILE = "streaks.json"

submitted_questions = []
scores = {}
streaks = {}
used_question_ids = set()
current_riddle = None
current_answer_revealed = False
correct_users = set()
guess_attempts = {}
purged_on_startup = False

CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID", "0"))
MOD_ROLE_NAMES = ["Admin", "Moderator"]

# Load helpers
def load_json(file):
    if os.path.exists(file):
        with open(file, "r", encoding="utf-8") as f:
            return json.load(f)
    return [] if file == QUESTIONS_FILE else {}

def save_json(file, data):
    with open(file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def get_rank(score, streak):
    if score <= 5:
        rank = "Sushi Newbie 🍽️"
    elif 6 <= score <= 15:
        rank = "Maki Novice 🍣"
    elif 16 <= score <= 25:
        rank = "Sashimi Skilled 🍤"
    elif 26 <= score <= 50:
        rank = "Brainy Botan 🧠"
    else:
        rank = "Sushi Einstein 🧪"
    if streak >= 3:
        rank = f"🔥 Streak Samurai (Solved {streak} riddles consecutively)"
    return rank

def get_time_until_reveal():
    now = datetime.now(timezone.utc)
    if now.date() == datetime.utcnow().date():
        target_time = datetime.combine(now.date(), time(1, 0, tzinfo=timezone.utc))
    else:
        target_time = datetime.combine(now.date(), time(23, 0, tzinfo=timezone.utc))
    remaining = target_time - now
    hours, remainder = divmod(int(remaining.total_seconds()), 3600)
    minutes = remainder // 60
    return f"Answer will be revealed in {hours}h {minutes}m."

# File loading
submitted_questions = load_json(QUESTIONS_FILE)
scores = load_json(SCORES_FILE)
streaks = load_json(STREAKS_FILE)

# Core bot events
@client.event
async def on_ready():
    global purged_on_startup, current_riddle, current_answer_revealed, correct_users, guess_attempts
    await tree.sync()
    print(f"Logged in as {client.user} (ID: {client.user.id})")

    if CHANNEL_ID:
        channel = client.get_channel(CHANNEL_ID)
        if channel and not purged_on_startup:
            await purge_channel_messages(channel)
            purged_on_startup = True
            current_riddle = None
            current_answer_revealed = False
            correct_users.clear()
            guess_attempts.clear()
            await post_special_riddle(channel)

    post_riddle.start()
    reveal_answer.start()

async def purge_channel_messages(channel):
    try:
        async for message in channel.history(limit=None):
            await message.delete()
    except Exception as e:
        print(f"Purge error: {e}")

async def post_special_riddle(channel):
    global current_riddle, current_answer_revealed, correct_users, guess_attempts
    current_riddle = {
        "id": "manual_egg",
        "question": "What has to be broken before you can use it?",
        "answer": "Egg",
        "submitter_id": None
    }
    current_answer_revealed = False
    correct_users.clear()
    guess_attempts.clear()
    await channel.send(f"@everyone {current_riddle['question']}\n\n_(Answer will be revealed later tonight)_")

@tree.command(name="submitriddle", description="Submit a new riddle")
@app_commands.describe(question="Your riddle question", answer="The answer to the riddle")
async def submitriddle(interaction: discord.Interaction, question: str, answer: str):
    new_id = str(int(datetime.utcnow().timestamp() * 1000)) + f"_{interaction.user.id}"
    submitted_questions.append({
        "id": new_id,
        "question": question,
        "answer": answer,
        "submitter_id": str(interaction.user.id)
    })
    save_json(QUESTIONS_FILE, submitted_questions)
    await interaction.response.send_message("✅ Riddle submitted successfully!", ephemeral=True)

@client.event
async def on_message(message):
    if message.author.bot or message.channel.id != CHANNEL_ID:
        return

    user_id = str(message.author.id)
    content = message.content.strip()

    if content.startswith("!"):
        return

    if current_riddle and not current_answer_revealed:
        if user_id in correct_users:
            await message.channel.send(f"✅ You have already guessed the correct answer, {message.author.mention}. {get_time_until_reveal()}")
            return

        guess_attempts[user_id] = guess_attempts.get(user_id, 0)
        if guess_attempts[user_id] >= 5:
            await message.channel.send(f"❌ You're out of guesses, {message.author.mention}.")
            return

        guess = content.lower()
        answer = current_riddle["answer"].lower()
        if guess == answer or guess.rstrip("s") == answer.rstrip("s"):
            correct_users.add(user_id)
            scores[user_id] = scores.get(user_id, 0) + 1
            streaks[user_id] = streaks.get(user_id, 0) + 1
            save_json(SCORES_FILE, scores)
            save_json(STREAKS_FILE, streaks)
            await message.channel.send(f"🎉 Correct, {message.author.mention}! {get_time_until_reveal()}")
        else:
            guess_attempts[user_id] += 1
            await message.channel.send(f"❌ Incorrect, {message.author.mention}. {5 - guess_attempts[user_id]} attempts left. {get_time_until_reveal()}")

@tasks.loop(time=time(hour=6, minute=0, tzinfo=timezone.utc))
async def post_riddle():
    global current_riddle, current_answer_revealed, correct_users, guess_attempts
    channel = client.get_channel(CHANNEL_ID)
    if not channel:
        return
    if not submitted_questions:
        return
    question = random.choice([q for q in submitted_questions if q.get("id") not in used_question_ids])
    current_riddle = question
    used_question_ids.add(question["id"])
    current_answer_revealed = False
    correct_users.clear()
    guess_attempts.clear()
    await channel.send(f"@everyone {question['question']}\n\n_(Answer will be revealed tonight)_")

@tasks.loop(time=time(hour=1 if datetime.now().date() == datetime.utcnow().date() else 23, tzinfo=timezone.utc))
async def reveal_answer():
    global current_answer_revealed
    channel = client.get_channel(CHANNEL_ID)
    if not channel or not current_riddle:
        return
    current_answer_revealed = True
    await channel.send(f"🕵️‍♀️ The answer was: **{current_riddle['answer']}**")

if __name__ == "__main__":
    TOKEN = os.getenv("DISCORD_BOT_TOKEN")
    if not TOKEN:
        print("DISCORD_BOT_TOKEN not set")
        exit(1)
    client.run(TOKEN)
