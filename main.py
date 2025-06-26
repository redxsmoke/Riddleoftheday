import discord
from discord.ext import tasks
import asyncio
import json
import os
from datetime import datetime, time, timezone, timedelta
import random

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)
tree = discord.app_commands.CommandTree(client)

# Files
QUESTIONS_FILE = "submitted_questions.json"
SCORES_FILE = "scores.json"
STREAKS_FILE = "streaks.json"

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
leaderboard_pages = {}
guess_attempts = {}
purged_on_startup = False

REVEAL_HOUR = 23
REVEAL_MINUTE = 0
if datetime.utcnow().date() == datetime(2025, 6, 26).date():
    REVEAL_HOUR = 1
    REVEAL_MINUTE = 0


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

def get_top_scorers():
    if not scores:
        return []
    max_score = max(scores.values())
    return [uid for uid, s in scores.items() if s == max_score and max_score > 0]

def format_question_text(qdict):
    base = f"@everyone {qdict['question']} ***(Answer will be revealed later this evening)***"
    remaining = count_unused_questions()
    if remaining < 5:
        base += "\n\n⚠️ Less than 5 new riddles remain - submit a new riddle with !submitriddle to add it to the queue!"
    return base

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

def save_all_scores():
    save_json(SCORES_FILE, scores)
    save_json(STREAKS_FILE, streaks)

@client.event
async def on_message(message):
    if message.author.bot:
        return

    channel_id = int(os.getenv("DISCORD_CHANNEL_ID", "0"))
    if message.channel.id != channel_id:
        if message.content.startswith("!"):
            return
        return

    content = message.content.strip()
    user_id = str(message.author.id)

    if content == "!score":
        score = scores.get(user_id, 0)
        streak = streaks.get(user_id, 0)
        rank = get_rank(score, streak)
        await message.channel.send(
            f"📊 {message.author.display_name}'s score: **{score}**, 🔥 Streak: {streak}\n🏅 Rank: {rank}"
        )
        return

    if content == "!leaderboard":
        leaderboard_pages[user_id] = 0
        await show_leaderboard(message.channel, user_id)
        return

    if content.startswith("!submitriddle"):
        try:
            _, rest = content.split(" ", 1)
            question, answer = rest.split("|", 1)
            question = question.strip()
            answer = answer.strip()
            if not question or not answer:
                await message.channel.send("❌ Please provide both a question and an answer, separated by '|'.")
                return
        except Exception:
            await message.channel.send("❌ Invalid format. Use: `!submitriddle Your question here | The answer here`")
            return

        new_id = str(int(datetime.utcnow().timestamp() * 1000)) + "_" + user_id
        submitted_questions.append({
            "id": new_id,
            "question": question,
            "answer": answer,
            "submitter_id": user_id
        })
        save_json(QUESTIONS_FILE, submitted_questions)
        await message.channel.send(f"✅ Thanks {message.author.mention}, your riddle has been submitted! It will appear in the queue soon.")
        return

    # Skip if it's a command to avoid processing as guess
    if content.startswith("!"):
        return

    if current_riddle and not current_answer_revealed:
        if user_id in correct_users:
            try:
                await message.delete()
            except Exception:
                pass
            await message.channel.send(f"✅ You have already guessed the correct answer, {message.author.mention}. No more guesses will be counted.")
            return

        user_attempts = guess_attempts.get(user_id, 0)
        if user_attempts >= 5:
            await message.channel.send(f"❌ You're out of attempts for today's riddle, {message.author.mention}.")
            try:
                await message.delete()
            except Exception:
                pass
            return

        guess = content.lower()
        correct_answer = current_riddle["answer"].lower()

        if guess == correct_answer or guess.rstrip("s") == correct_answer.rstrip("s"):
            correct_users.add(user_id)
            if scores.get(user_id, 0) == None:
                scores[user_id] = 0
            if user_id not in correct_users:
                scores[user_id] = max(0, scores.get(user_id, 0) + 1)
                streaks[user_id] = streaks.get(user_id, 0) + 1
                save_all_scores()
            await message.channel.send(
                f"🎉 Correct, {message.author.mention}! Keep it up! 🏅 Your current score: {scores.get(user_id,0)}"
            )
            try:
                await message.delete()
            except Exception:
                pass
            return
        else:
            guess_attempts[user_id] = user_attempts + 1
            remaining = 5 - guess_attempts[user_id]

            now = datetime.utcnow().replace(tzinfo=timezone.utc)
            reveal_time = now.replace(hour=REVEAL_HOUR, minute=REVEAL_MINUTE, second=0, microsecond=0)
            if now > reveal_time:
                reveal_time += timedelta(days=1)
            time_left = reveal_time - now
            hours, remainder = divmod(int(time_left.total_seconds()), 3600)
            minutes, _ = divmod(remainder, 60)
            countdown = f"Time left until answer reveal: {hours}h {minutes}m"

            if remaining == 0:
                scores[user_id] = max(0, scores.get(user_id, 0) - 1)
                streaks[user_id] = 0
                save_all_scores()
                await message.channel.send(
                    f"❌ Sorry, that answer is incorrect, {message.author.mention}. You have no guesses left and lost 1 point.\n{countdown}"
                )
            elif remaining == 1:
                await message.channel.send(
                    f"❌ Sorry, that answer is incorrect, {message.author.mention} ({remaining} guess remaining). If you guess incorrectly again, you will lose 1 point.\n{countdown}"
                )
            else:
                await message.channel.send(
                    f"❌ Sorry, that answer is incorrect, {message.author.mention} ({remaining} guesses remaining).\n{countdown}"
                )

            try:
                await message.delete()
            except Exception:
                pass
            return
