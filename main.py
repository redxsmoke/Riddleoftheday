import discord
from discord.ext import tasks
import asyncio
import json
import os
from datetime import datetime, time, timezone
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
    return {}

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

def get_rank(score, streak):
    if score <= 5:
        rank = "Sushi Newbie 🍼"
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
        base += "\n\n⚠️ Less than 5 new riddles remain - submit a new riddle with !submit_riddle to add it to the queue!"
    return base

def count_unused_questions():
    return len([q for q in submitted_questions if q["id"] not in used_question_ids])

def pick_next_riddle():
    unused = [q for q in submitted_questions if q["id"] not in used_question_ids]
    if not unused:
        used_question_ids.clear()
        unused = submitted_questions[:]
    riddle = random.choice(unused)
    used_question_ids.add(riddle["id"])
    return riddle

def save_all_scores():
    save_json(SCORES_FILE, scores)
    save_json(STREAKS_FILE, streaks)

@client.event
async def on_ready():
    print(f"Logged in as {client.user} (ID: {client.user.id})")
    print("------")
    await tree.sync()
    post_riddle.start()
    reveal_answer.start()

@client.event
async def on_message(message):
    if message.author.bot:
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

    if content.startswith("!submit_riddle "):
        try:
            _, rest = content.split(" ", 1)
            question, answer = rest.split("|", 1)
            question = question.strip()
            answer = answer.strip()
            if not question or not answer:
                await message.channel.send("❌ Please provide both a question and an answer, separated by '|'.")
                return
        except Exception:
            await message.channel.send("❌ Invalid format. Use: `!submit_riddle Your question here | The answer here`")
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

    if content == "!leaderboard":
        leaderboard_pages[user_id] = 0
        await show_leaderboard(message.channel, user_id)
        return

    if content == "!next":
        if user_id in leaderboard_pages:
            leaderboard_pages[user_id] += 1
            await show_leaderboard(message.channel, user_id)
        return

    if content == "!prev":
        if user_id in leaderboard_pages and leaderboard_pages[user_id] > 0:
            leaderboard_pages[user_id] -= 1
            await show_leaderboard(message.channel, user_id)
        return

    if current_riddle and not current_answer_revealed:
        guess = content.lower()
        correct_answer = current_riddle["answer"].lower()
        if guess == correct_answer:
            correct_users.add(message.author.id)
            scores[user_id] = scores.get(user_id, 0) + 1
            streaks[user_id] = streaks.get(user_id, 0) + 1
            save_all_scores()
            await message.channel.send(f"🎉 Correct, {message.author.mention}! Keep it up! 🏅 Your current score: {scores[user_id]}")
        else:
            try:
                await message.delete()
            except Exception:
                pass

@tree.command(name="riddleofthedaycommands", description="View all available Riddle of the Day commands")
async def riddleofthedaycommands(interaction: discord.Interaction):
    commands = """
**Available Riddle Bot Commands:**
• `!score` – View your score and rank.
• `!submit_riddle question | answer` – Submit a new riddle.
• `!leaderboard` – Show the top solvers.
• `!next` / `!prev` – Navigate the leaderboard.
• Just type your guess to answer the riddle!
"""
    await interaction.response.send_message(commands, ephemeral=True)

@tasks.loop(time=time(hour=6, minute=0, tzinfo=timezone.utc))
async def post_riddle():
    global current_riddle, current_answer_revealed, correct_users
    channel_id = int(os.getenv("DISCORD_CHANNEL_ID", "0"))
    if channel_id == 0:
        print("DISCORD_CHANNEL_ID not set.")
        return
    channel = client.get_channel(channel_id)
    if not channel:
        print("Channel not found.")
        return

    current_riddle = pick_next_riddle()
    current_answer_revealed = False
    correct_users = set()

    question_text = format_question_text(current_riddle)
    submitter_id = current_riddle.get("submitter_id")
    submitter_text = f"<@{submitter_id}>" if submitter_id else "Riddle of the Day bot"

    await channel.send(f"{question_text}\n\n_(Submitted by: {submitter_text})_")

@tasks.loop(time=time(hour=23, minute=0, tzinfo=timezone.utc))
async def reveal_answer():
    global current_answer_revealed, correct_users
    channel_id = int(os.getenv("DISCORD_CHANNEL_ID", "0"))
    if channel_id == 0:
        print("DISCORD_CHANNEL_ID not set.")
        return
    channel = client.get_channel(channel_id)
    if not channel or not current_riddle:
        return

    current_answer_revealed = True
    correct_answer = current_riddle["answer"]
    submitter_id = current_riddle.get("submitter_id")
    submitter_text = f"<@{submitter_id}>" if submitter_id else "Riddle of the Day bot"

    if correct_users:
        lines = [f"✅ The correct answer was **{correct_answer}**!\n"]
        lines.append(f"Submitted by: {submitter_text}\n")
        lines.append("The following users got it correct:")

        top_scorers = get_top_scorers()
        for uid in correct_users:
            uid_str = str(uid)
            user = await client.fetch_user(uid)
            rank = get_rank(scores.get(uid_str, 0), streaks.get(uid_str, 0))
            extra = " 👑 Chopstick Champ (Top Solver)" if uid_str in top_scorers else ""
            lines.append(f"• {user.mention} (**{scores.get(uid_str, 0)}**, 🔥 {streaks.get(uid_str, 0)}) 🏅 {rank}{extra}")
        lines.append("\n📅 Stay tuned for tomorrow’s riddle!")
        await channel.send("\n".join(lines))
    else:
        await channel.send(f"❌ The correct answer was **{correct_answer}**. No one got it right.\n\nSubmitted by: {submitter_text}")

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
    top_score = sorted_scores[0][1] if sorted_scores else 0
    top_scorers = [uid for uid, s in sorted_scores if s == top_score and top_score > 0]

    for i, (uid, score) in enumerate(sorted_scores[start:start+10], start=start + 1):
        user = await client.fetch_user(int(uid))
        streak = streaks.get(uid, 0)
        rank = get_rank(score, streak)
        extra = " 👑 Chopstick Champ (Top Solver)" if uid in top_scorers else ""
        embed.add_field(
            name=f"{i}. {user.display_name}",
            value=f"Correct: **{score}**, 🔥 Streak: {streak}\n🏅 Rank: {rank}{extra}",
            inline=False
        )

    embed.set_footer(text="Use !next and !prev to navigate pages")
    await channel.send(embed=embed)

if __name__ == "__main__":
    TOKEN = os.getenv("DISCORD_BOT_TOKEN")
    if not TOKEN:
        print("Error: DISCORD_BOT_TOKEN environment variable not set.")
        exit(1)
    client.run(TOKEN)
