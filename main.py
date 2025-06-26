import discord
from discord.ext import tasks
from discord import app_commands
import asyncio
import json
import os
from datetime import datetime, time, timezone, timedelta
import random

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

QUESTIONS_FILE = "submitted_questions.json"
SCORES_FILE = "scores.json"
STREAKS_FILE = "streaks.json"

ADMIN_ROLE_NAMES = ["admin", "moderator"]

# Load or initialize data stores
def load_json(file):
    if os.path.exists(file):
        with open(file, "r", encoding="utf-8") as f:
            return json.load(f)
    return [] if file == QUESTIONS_FILE else {}

def save_json(file, data):
    with open(file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

submitted_questions = load_json(QUESTIONS_FILE)
scores = load_json(SCORES_FILE)
streaks = load_json(STREAKS_FILE)

used_question_ids = set()
current_riddle = None
current_answer_revealed = False
correct_users = set()
guess_attempts = {}
purged_on_startup = False

def get_rank(score, streak):
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

def format_question_text(qdict):
    base = f"@everyone {qdict['question']} ***(Answer will be revealed later this evening)***"
    remaining = count_unused_questions()
    if remaining < 5:
        base += "\n\n\u26a0\ufe0f Less than 5 new riddles remain - submit a new riddle with /submitriddle!"
    return base

def pick_next_riddle():
    unused = [q for q in submitted_questions if q.get("id") not in used_question_ids and q.get("id") is not None]
    if not unused:
        used_question_ids.clear()
        unused = [q for q in submitted_questions if q.get("id") is not None]
    riddle = random.choice(unused)
    used_question_ids.add(riddle["id"])
    return riddle

async def purge_channel_messages(channel):
    try:
        async for message in channel.history(limit=None):
            await message.delete()
    except Exception as e:
        print(f"Error during purge: {e}")

@client.event
async def on_ready():
    global purged_on_startup, current_riddle, current_answer_revealed, correct_users, guess_attempts
    await tree.sync()
    channel_id = int(os.getenv("DISCORD_CHANNEL_ID", "0"))
    if channel_id:
        channel = client.get_channel(channel_id)
        if channel and not purged_on_startup:
            await purge_channel_messages(channel)
            purged_on_startup = True
            current_riddle = None
            current_answer_revealed = False
            correct_users.clear()
            guess_attempts.clear()
    post_riddle.start()
    reveal_answer.start()

@client.event
async def on_message(message):
    if message.author.bot:
        return

    channel_id = int(os.getenv("DISCORD_CHANNEL_ID", "0"))
    if message.channel.id != channel_id:
        return

    content = message.content.strip()
    user_id = str(message.author.id)

    if content.startswith("!") or content.startswith("/"):
        return  # Ignore commands

    if current_riddle and not current_answer_revealed:
        if user_id in correct_users:
            try:
                await message.delete()
            except:
                pass
            await message.channel.send(f"✅ You have already guessed the correct answer, {message.author.mention}. No more guesses will be counted.")
            return

        user_attempts = guess_attempts.get(user_id, 0)
        if user_attempts >= 5:
            await message.channel.send(f"❌ You're out of attempts for today's riddle, {message.author.mention}.")
            try:
                await message.delete()
            except:
                pass
            return

        guess = content.lower()
        correct_answer = current_riddle["answer"].lower()

        if guess == correct_answer or guess.rstrip("s") == correct_answer.rstrip("s"):
            if user_id not in correct_users:
                correct_users.add(user_id)
                scores[user_id] = scores.get(user_id, 0) + 1
                streaks[user_id] = streaks.get(user_id, 0) + 1
                with open(SCORES_FILE, "w") as f:
                    json.dump(scores, f)
                with open(STREAKS_FILE, "w") as f:
                    json.dump(streaks, f)
            await message.channel.send(f"🎉 Correct, {message.author.mention}! Keep it up! \nAnswer will be revealed in {time_until_reveal()}.")
            try:
                await message.delete()
            except:
                pass
            return

        guess_attempts[user_id] = user_attempts + 1
        remaining = 5 - guess_attempts[user_id]
        msg = f"❌ Sorry, that answer is incorrect, {message.author.mention} ({remaining} guess{'es' if remaining != 1 else ''} remaining)."
        if remaining == 1:
            msg += " If you guess incorrectly again, you will lose 1 point."
        elif remaining == 0:
            scores[user_id] = max(0, scores.get(user_id, 0) - 1)
            streaks[user_id] = 0
            with open(SCORES_FILE, "w") as f:
                json.dump(scores, f)
            msg = f"❌ Sorry, that answer is incorrect, {message.author.mention}. You have no guesses left and lost 1 point."
        await message.channel.send(msg)
        try:
            await message.delete()
        except:
            pass

@tree.command(name="submitriddle", description="Submit a new riddle to be added to the queue")
async def submit_riddle(interaction: discord.Interaction, question: str, answer: str):
    user_id = str(interaction.user.id)
    new_id = str(int(datetime.utcnow().timestamp() * 1000)) + "_" + user_id
    submitted_questions.append({
        "id": new_id,
        "question": question,
        "answer": answer,
        "submitter_id": user_id
    })
    save_json(QUESTIONS_FILE, submitted_questions)
    await interaction.response.send_message(f"✅ Your riddle has been submitted, {interaction.user.mention}!", ephemeral=True)

@tree.command(name="listquestions", description="List all submitted questions")
async def list_questions(interaction: discord.Interaction):
    if not any(role.name.lower() in ADMIN_ROLE_NAMES for role in interaction.user.roles):
        await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
        return
    if not submitted_questions:
        await interaction.response.send_message("No questions submitted yet.", ephemeral=True)
        return
    message = "\n".join([f"ID: {q['id']} | Q: {q['question']}" for q in submitted_questions])
    await interaction.response.send_message(f"Submitted Questions:\n{message}", ephemeral=True)

@tree.command(name="removequestion", description="Remove a question by ID")
async def remove_question(interaction: discord.Interaction, id: str):
    if not any(role.name.lower() in ADMIN_ROLE_NAMES for role in interaction.user.roles):
        await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
        return
    global submitted_questions
    before_count = len(submitted_questions)
    submitted_questions = [q for q in submitted_questions if q["id"] != id]
    if len(submitted_questions) < before_count:
        save_json(QUESTIONS_FILE, submitted_questions)
        await interaction.response.send_message(f"✅ Question with ID {id} removed.", ephemeral=True)
    else:
        await interaction.response.send_message("No question found with that ID.", ephemeral=True)

def time_until_reveal():
    now = datetime.utcnow()
    today = now.date()
    if now < datetime(today.year, today.month, today.day, 23, 0, tzinfo=timezone.utc):
        reveal_time = datetime(today.year, today.month, today.day, 23, 0, tzinfo=timezone.utc)
    else:
        reveal_time = datetime(today.year, today.month, today.day + 1, 23, 0, tzinfo=timezone.utc)
    remaining = reveal_time - now.replace(tzinfo=timezone.utc)
    hours, remainder = divmod(int(remaining.total_seconds()), 3600)
    minutes = remainder // 60
    return f"{hours}h {minutes}m"

@tasks.loop(time=time(hour=6, tzinfo=timezone.utc))
async def post_riddle():
    global current_riddle, current_answer_revealed, correct_users, guess_attempts
    channel = client.get_channel(int(os.getenv("DISCORD_CHANNEL_ID")))
    current_riddle = pick_next_riddle()
    current_answer_revealed = False
    correct_users = set()
    guess_attempts.clear()
    question_text = format_question_text(current_riddle)
    submitter_text = f"<@{current_riddle.get('submitter_id')}>" if current_riddle.get("submitter_id") else "Riddle of the Day bot"
    await channel.send(f"{question_text}\n\n_(Submitted by: {submitter_text})_")

@tasks.loop(time=time(hour=23, tzinfo=timezone.utc))
async def reveal_answer():
    global current_answer_revealed
    channel = client.get_channel(int(os.getenv("DISCORD_CHANNEL_ID")))
    if not current_riddle:
        return
    current_answer_revealed = True
    correct_answer = current_riddle["answer"]
    submitter_id = current_riddle.get("submitter_id")
    submitter_text = f"<@{submitter_id}>" if submitter_id else "Riddle of the Day bot"

    if correct_users:
        users_text = "\n".join([f"\u2022 <@{uid}>" for uid in correct_users])
        await channel.send(f"✅ The correct answer was **{correct_answer}**!\nSubmitted by: {submitter_text}\n\nCorrect solvers:\n{users_text}")
    else:
        await channel.send(f"❌ The correct answer was **{correct_answer}**. No one got it right.\n\nSubmitted by: {submitter_text}")

if __name__ == "__main__":
    TOKEN = os.getenv("DISCORD_BOT_TOKEN")
    if not TOKEN:
        print("Error: DISCORD_BOT_TOKEN environment variable not set.")
        exit(1)
    client.run(TOKEN)
