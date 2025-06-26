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

def get_rank(score, streak):
    if score <= 5:
        return "Sushi Newbie 🍽️"
    elif score <= 15:
        return "Maki Novice 🍣"
    elif score <= 25:
        return "Sashimi Skilled 🍤"
    elif score <= 50:
        return "Brainy Botan 🧠"
    return "Sushi Einstein 🧪" if streak < 3 else f"🔥 Streak Samurai (Solved {streak} riddles consecutively)"

def get_top_scorers():
    if not scores:
        return []
    max_score = max(scores.values())
    return [uid for uid, s in scores.items() if s == max_score and max_score > 0]

def format_question_text(qdict):
    base = f"@everyone {qdict['question']} ***(Answer will be revealed later this evening)***"
    if count_unused_questions() < 5:
        base += "\n\n⚠️ Less than 5 new riddles remain - submit a new riddle with !submitriddle to add it to the queue!"
    return base

def count_unused_questions():
    return len([q for q in submitted_questions if q.get("id") not in used_question_ids])

def pick_next_riddle():
    unused = [q for q in submitted_questions if q.get("id") not in used_question_ids and q.get("id")]
    if not unused:
        used_question_ids.clear()
        unused = [q for q in submitted_questions if q.get("id")]
    riddle = random.choice(unused)
    used_question_ids.add(riddle["id"])
    return riddle

def save_all_scores():
    save_json(SCORES_FILE, scores)
    save_json(STREAKS_FILE, streaks)

async def purge_channel_messages(channel):
    try:
        async for message in channel.history(limit=None):
            await message.delete()
    except Exception as e:
        print(f"Error during purge: {e}")

def get_time_remaining_string():
    now = datetime.now(timezone.utc)
    reveal_time = now.replace(hour=23, minute=0, second=0, microsecond=0)
    if now > reveal_time:
        reveal_time += timedelta(days=1)
    remaining = reveal_time - now
    hours, remainder = divmod(int(remaining.total_seconds()), 3600)
    minutes = remainder // 60
    return f"⏳ Time remaining until the answer is revealed: **{hours}h {minutes}m**."

@client.event
async def on_ready():
    global purged_on_startup, current_riddle, current_answer_revealed, correct_users, guess_attempts

    await tree.sync()
    channel_id = int(os.getenv("DISCORD_CHANNEL_ID", "0"))
    if not channel_id:
        return
    channel = client.get_channel(channel_id)
    if channel and not purged_on_startup:
        await purge_channel_messages(channel)
        purged_on_startup = True
        current_riddle = None
        current_answer_revealed = False
        correct_users.clear()
        guess_attempts.clear()
        await post_special_riddle()

    if not current_riddle:
        await post_special_riddle()

    post_riddle.start()
    reveal_answer.start()

async def post_special_riddle():
    global current_riddle, current_answer_revealed, correct_users, guess_attempts

    channel_id = int(os.getenv("DISCORD_CHANNEL_ID", "0"))
    channel = client.get_channel(channel_id)
    if not channel:
        return

    current_riddle = {
        "id": "manual_egg",
        "question": "What has to be broken before you can use it?",
        "answer": "Egg",
        "submitter_id": None
    }
    current_answer_revealed = False
    correct_users = set()
    guess_attempts.clear()

    await channel.send(f"{format_question_text(current_riddle)}\n\n_(Submitted by: Riddle of the Day bot)_")

@client.event
async def on_message(message):
    if message.author.bot:
        return

    channel_id = int(os.getenv("DISCORD_CHANNEL_ID", "0"))
    if message.channel.id != channel_id:
        return

    content = message.content.strip()
    user_id = str(message.author.id)

    if content == "!score":
        score = scores.get(user_id, 0)
        streak = streaks.get(user_id, 0)
        rank = get_rank(score, streak)
        await message.channel.send(f"📊 {message.author.display_name}'s score: **{score}**, 🔥 Streak: {streak}\n🏅 Rank: {rank}")
        return

    if content == "!leaderboard":
        leaderboard_pages[user_id] = 0
        await show_leaderboard(message.channel, user_id)
        return

    if content.startswith("!submitriddle "):
        try:
            _, rest = content.split(" ", 1)
            question, answer = rest.split("|", 1)
            submitted_questions.append({
                "id": str(int(datetime.utcnow().timestamp() * 1000)) + "_" + user_id,
                "question": question.strip(),
                "answer": answer.strip(),
                "submitter_id": user_id
            })
            save_json(QUESTIONS_FILE, submitted_questions)
            await message.channel.send(f"✅ Thanks {message.author.mention}, your riddle has been submitted!")
        except:
            await message.channel.send("❌ Invalid format. Use `!submitriddle your question | answer`")
        return

    if current_riddle and not current_answer_revealed:
        if user_id in correct_users:
            await message.channel.send(f"✅ You have already guessed the correct answer, {message.author.mention}. No more guesses will be counted.")
            try:
                await message.delete()
            except:
                pass
            return

        guess = content.lower()
        correct = current_riddle["answer"].lower()
        attempts = guess_attempts.get(user_id, 0)

        if attempts >= 5:
            await message.channel.send(f"❌ You're out of attempts for today's riddle, {message.author.mention}.")
            try:
                await message.delete()
            except:
                pass
            return

        if guess == correct or guess.rstrip("s") == correct.rstrip("s"):
            correct_users.add(user_id)
            if user_id not in scores:
                scores[user_id] = 0
            if guess_attempts.get(user_id, 0) < 5:
                scores[user_id] += 1
                streaks[user_id] = streaks.get(user_id, 0) + 1
                save_all_scores()

            await message.channel.send(f"🎉 Correct, {message.author.mention}! Keep it up! 🏅 Your current score: {scores[user_id]}")
            await message.channel.send(get_time_remaining_string())
            try:
                await message.delete()
            except:
                pass
            return

        guess_attempts[user_id] = attempts + 1
        remaining = 5 - guess_attempts[user_id]

        if remaining == 0:
            scores[user_id] = max(0, scores.get(user_id, 0) - 1)
            streaks[user_id] = 0
            save_all_scores()
            await message.channel.send(f"❌ Sorry, that answer is incorrect, {message.author.mention}. You have no guesses left and lost 1 point.")
        elif remaining == 1:
            await message.channel.send(f"❌ Sorry, that answer is incorrect, {message.author.mention} (1 guess remaining). If you guess incorrectly again, you will lose 1 point.")
        else:
            await message.channel.send(f"❌ Sorry, that answer is incorrect, {message.author.mention} ({remaining} guesses remaining).")

        await message.channel.send(get_time_remaining_string())

        try:
            await message.delete()
        except:
            pass

@tree.command(name="riddleofthedaycommands", description="View all available Riddle of the Day commands")
async def riddleofthedaycommands(interaction: discord.Interaction):
    await interaction.response.send_message(
        "**Available Riddle Bot Commands:**\n"
        "• `!score` – View your score and rank.\n"
        "• `!submitriddle question | answer` – Submit a new riddle.\n"
        "• `!leaderboard` – Show the top solvers.\n"
        "• Just type your guess to answer the riddle!",
        ephemeral=True
    )

@tasks.loop(time=time(hour=6, minute=0, tzinfo=timezone.utc))
async def post_riddle():
    global current_riddle, current_answer_revealed, correct_users, guess_attempts

    channel_id = int(os.getenv("DISCORD_CHANNEL_ID", "0"))
    channel = client.get_channel(channel_id)
    if not channel:
        return

    current_riddle = pick_next_riddle()
    current_answer_revealed = False
    correct_users = set()
    guess_attempts.clear()

    submitter = current_riddle.get("submitter_id")
    submitter_text = f"<@{submitter}>" if submitter else "Riddle of the Day bot"

    await channel.send(f"{format_question_text(current_riddle)}\n\n_(Submitted by: {submitter_text})_")

@tasks.loop(time=time(hour=23, minute=0, tzinfo=timezone.utc))
async def reveal_answer():
    global current_answer_revealed
    channel_id = int(os.getenv("DISCORD_CHANNEL_ID", "0"))
    channel = client.get_channel(channel_id)
    if not channel or not current_riddle:
        return

    current_answer_revealed = True
    correct_answer = current_riddle["answer"]
    submitter = current_riddle.get("submitter_id")
    submitter_text = f"<@{submitter}>" if submitter else "Riddle of the Day bot"

    if correct_users:
        lines = [f"✅ The correct answer was **{correct_answer}**!\n", f"Submitted by: {submitter_text}\n", "The following users got it correct:"]
        top_scorers = get_top_scorers()
        for uid in correct_users:
            uid_str = str(uid)
            user = await client.fetch_user(int(uid_str))
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

    for i, (uid, score) in enumerate(sorted_scores[start:start + 10], start=start + 1):
        user = await client.fetch_user(int(uid))
        streak = streaks.get(uid, 0)
        rank = get_rank(score, streak)
        extra = " 👑 Chopstick Champ (Top Solver)" if uid in top_scorers else ""
        embed.add_field(
            name=f"{i}. {user.display_name}",
            value=f"Correct: **{score}**, 🔥 Streak: {streak}\n🏅 Rank: {rank}{extra}",
            inline=False
        )

    embed.set_footer(text="Use !leaderboard again to refresh")
    await channel.send(embed=embed)

if __name__ == "__main__":
    TOKEN = os.getenv("DISCORD_BOT_TOKEN")
    if not TOKEN:
        print("Error: DISCORD_BOT_TOKEN environment variable not set.")
        exit(1)
    client.run(TOKEN)
