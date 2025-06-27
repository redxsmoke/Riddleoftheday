import discord
from discord.ext import tasks
import asyncio
import json
import os
from datetime import datetime, time, timezone, timedelta
import random
from discord import app_commands

# --- Timezone Setup ---
EST = timezone(timedelta(hours=-5))  # Fixed EST offset UTC-5 (no DST)

# --- Global Variables ---
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
guess_attempts = {}  # user_id -> guesses this riddle
deducted_for_user = set()  # users who lost 1 point this riddle

leaderboard_pages = {}

# --- Helper functions ---

def load_json(file):
    if os.path.exists(file):
        with open(file, "r", encoding="utf-8") as f:
            return json.load(f)
    return [] if file == QUESTIONS_FILE else {}

def save_json(file, data):
    with open(file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def save_all_scores():
    save_json(SCORES_FILE, scores)
    save_json(STREAKS_FILE, streaks)

def get_rank(score, streak):
    if streak >= 3:
        return f"🔥 Streak Samurai (Solved {streak} riddles consecutively)"
    if score <= 5:
        return "Sushi Newbie 🍽️"
    elif 6 <= score <= 15:
        return "Maki Novice 🍣"
    elif 16 <= score <= 25:
        return "Sashimi Skilled 🍤"
    elif 26 <= score <= 50:
        return "Brainy Botan 🧠"
    else:
        return "Sushi Einstein 🧪"

def count_unused_questions():
    return len([q for q in submitted_questions if q.get("id") not in used_question_ids])

def pick_next_riddle():
    unused = [q for q in submitted_questions if q.get("id") not in used_question_ids and q.get("id") is not None]
    if not unused:
        used_question_ids.clear()
        unused = [q for q in submitted_questions if q.get("id") is not None]
    riddle = random.choice(unused)
    used_question_ids.add(riddle["id"])
    return riddle

def format_question_text(qdict):
    base = f"@everyone {qdict['question']} ***(Answer will be revealed in 1 minute)***"
    remaining = count_unused_questions()
    if remaining < 5:
        base += "\n\n⚠️ Less than 5 new riddles remain - submit a new riddle with /submitriddle to add it to the queue!"
    return base

# --- Load data ---
submitted_questions = load_json(QUESTIONS_FILE)

# 👇 Simulate that all riddles were submitted by IzzyBan (e.g., ID: 123456789012345678)
for q in submitted_questions:
    q["submitter_id"] = "123456789012345678"

scores = load_json(SCORES_FILE)
streaks = load_json(STREAKS_FILE)

# --- Debug prints on startup ---
print("Starting bot...")
token = os.getenv("DISCORD_BOT_TOKEN")
channel_id = os.getenv("DISCORD_CHANNEL_ID")
guild_id = os.getenv("DISCORD_GUILD_ID")
print(f"Token set? {'Yes' if token else 'No'}")
print(f"Channel ID: {channel_id}")
print(f"Guild ID: {guild_id}")

if not token:
    print("ERROR: DISCORD_BOT_TOKEN environment variable is NOT set!")

# --- Events ---

@client.event
async def on_ready():
    global current_riddle, current_answer_revealed, correct_users, guess_attempts, deducted_for_user

    print(f"Logged in as {client.user} (ID: {client.user.id})")
    print("------")

    if guild_id:
        guild_obj = discord.Object(id=int(guild_id))
        await tree.sync(guild=guild_obj)
        print(f"Synced commands to guild {guild_id}")
    else:
        await tree.sync()
        print("Synced global commands")

    ch_id = int(channel_id or 0)
    if ch_id == 0:
        print("DISCORD_CHANNEL_ID not set or invalid.")
        return

    channel = client.get_channel(ch_id)
    if not channel:
        print("Channel not found.")
        return

    current_riddle = pick_next_riddle()
    current_answer_revealed = False
    correct_users.clear()
    guess_attempts.clear()
    deducted_for_user.clear()

    question_text = format_question_text(current_riddle)
    submitter_id = current_riddle.get("submitter_id")
    submitter_text = f"<@{submitter_id}>" if submitter_id else "Riddle of the Day bot"

    await channel.send(f"{question_text}\n\n_(Submitted by: {submitter_text})_")
    await asyncio.sleep(60)

    current_answer_revealed = True

    correct_answer = current_riddle["answer"]
    lines = [f"✅ The correct answer was: **{correct_answer}**"]
    if correct_users:
        lines.append("🎉 Congratulations to the following solvers:")
        for uid in correct_users:
            try:
                user = await client.fetch_user(int(uid))
                lines.append(f"• {user.display_name}")
            except:
                lines.append("• Unknown user")
    else:
        lines.append("No one guessed correctly this time.")
    lines.append(f"\n_(Riddle submitted by: {submitter_text})_")

    await channel.send("\n".join(lines))

    post_riddle.start()
    reveal_answer.start()

@client.event
async def on_message(message):
    if message.author.bot:
        return

    ch_id = int(channel_id or 0)
    if message.channel.id != ch_id:
        return

    global correct_users, guess_attempts, deducted_for_user, current_riddle

    user_id = str(message.author.id)
    content = message.content.strip()

    if not current_riddle or current_answer_revealed:
        return

    submitter_id = current_riddle.get("submitter_id")
    if user_id == submitter_id:
        try:
            await message.delete()
        except:
            pass
        await message.channel.send(f"⛔ You submitted this riddle and cannot answer it, {message.author.mention}.", delete_after=5)
        return

    if user_id in correct_users:
        try:
            await message.delete()
        except:
            pass
        await message.channel.send(f"✅ You already answered correctly, {message.author.mention}. No more guesses counted.", delete_after=5)
        return

    attempts = guess_attempts.get(user_id, 0)
    if attempts >= 5:
        try:
            await message.delete()
        except:
            pass
        await message.channel.send(f"❌ You are out of guesses for this riddle, {message.author.mention}.", delete_after=5)
        return

    guess_attempts[user_id] = attempts + 1
    guess = content.lower()
    correct_answer = current_riddle["answer"].lower()

    if guess == correct_answer or guess.rstrip("s") == correct_answer.rstrip("s"):
        correct_users.add(user_id)
        scores[user_id] = scores.get(user_id, 0) + 1
        streaks[user_id] = streaks.get(user_id, 0) + 1
        save_all_scores()
        try:
            await message.delete()
        except:
            pass
        await message.channel.send(f"🎉 Correct, {message.author.mention}! Your total score: {scores[user_id]}")
    else:
        remaining = 5 - guess_attempts[user_id]
        if remaining == 0 and user_id not in deducted_for_user:
            scores[user_id] = max(0, scores.get(user_id, 0) - 1)
            streaks[user_id] = 0
            deducted_for_user.add(user_id)
            save_all_scores()
            await message.channel.send(f"❌ Incorrect, {message.author.mention}. You've used all guesses and lost 1 point.", delete_after=8)
        elif remaining > 0:
            await message.channel.send(f"❌ Incorrect, {message.author.mention}. {remaining} guess(es) left.", delete_after=6)
        try:
            await message.delete()
        except:
            pass

    now_utc = datetime.now(timezone.utc)
    now_est = now_utc.astimezone(EST)
    today_est = now_est.date()

    if today_est == datetime.now(EST).date():
        reveal_est = datetime.combine(today_est, time(21, 0), tzinfo=EST)
        reveal_dt = reveal_est.astimezone(timezone.utc)
        delta = max(reveal_dt - now_utc, timedelta(0))
    else:
        reveal_dt = datetime.combine(now_utc.date(), time(23, 0), tzinfo=timezone.utc)
        if now_utc >= reveal_dt:
            reveal_dt += timedelta(days=1)
        delta = reveal_dt - now_utc

    hours, remainder = divmod(int(delta.total_seconds()), 3600)
    minutes = remainder // 60
    countdown_msg = f"⏳ Answer will be revealed in {hours} hour{'s' if hours != 1 else ''} {minutes} minute{'s' if minutes != 1 else ''}."
    await message.channel.send(countdown_msg, delete_after=12)

# --- Run bot ---
if token:
    client.run(token)
else:
    print("Bot token not found. Please set the DISCORD_BOT_TOKEN environment variable.")
