import discord
from discord.ext import tasks
import asyncio
import json
import os
from datetime import datetime, time, timezone, timedelta
import random

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
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
        base += "\n\n⚠️ Less than 5 new riddles remain - submit a new riddle with /submitriddle to add it to the queue!"
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

async def purge_channel_messages(channel):
    print(f"Purging all messages in channel: {channel.name} ({channel.id}) for clean test")
    try:
        async for message in channel.history(limit=None):
            await message.delete()
        print("Channel purge complete.")
    except Exception as e:
        print(f"Error during purge: {e}")

def is_admin_or_mod(member: discord.Member):
    return any(role.permissions.administrator for role in member.roles) or \
           any(role.permissions.manage_messages for role in member.roles)

@client.event
async def on_ready():
    global purged_on_startup, current_riddle, current_answer_revealed, correct_users, guess_attempts

    print(f"Logged in as {client.user} (ID: {client.user.id})")
    print("------")
    await tree.sync()

    channel_id = int(os.getenv("DISCORD_CHANNEL_ID", "0"))
    if channel_id == 0:
        print("DISCORD_CHANNEL_ID not set.")
    else:
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
    if channel_id == 0:
        print("DISCORD_CHANNEL_ID not set.")
        return

    channel = client.get_channel(channel_id)
    if not channel:
        print("Channel not found.")
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

    question_text = format_question_text(current_riddle)
    await channel.send(f"{question_text}\n\n_(Submitted by: Riddle of the Day bot)_")

def get_answer_reveal_time():
    now_utc = datetime.utcnow().replace(tzinfo=timezone.utc)
    today_utc_date = now_utc.date()
    reveal_time_today = datetime.combine(today_utc_date, time(hour=1, minute=0, tzinfo=timezone.utc))
    if now_utc < reveal_time_today:
        return reveal_time_today
    else:
        # Starting tomorrow 23:00 UTC
        tomorrow = today_utc_date + timedelta(days=1)
        return datetime.combine(tomorrow, time(hour=23, minute=0, tzinfo=timezone.utc))

def format_countdown():
    now_utc = datetime.utcnow().replace(tzinfo=timezone.utc)
    reveal_time = get_answer_reveal_time()
    delta = reveal_time - now_utc
    total_seconds = int(delta.total_seconds())
    if total_seconds < 0:
        return "soon"
    hours, remainder = divmod(total_seconds, 3600)
    minutes, _ = divmod(remainder, 60)
    parts = []
    if hours > 0:
        parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
    if minutes > 0:
        parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
    return " and ".join(parts) if parts else "less than a minute"

@client.event
async def on_message(message):
    if message.author.bot:
        return

    channel_id = int(os.getenv("DISCORD_CHANNEL_ID", "0"))
    if message.channel.id != channel_id:
        # Outside designated channel, allow commands but no guess processing or deletion
        if message.content.startswith("!"):
            # Let commands run outside channel but do not delete or process guesses
            return
        # Outside channel, ignore guesses
        return

    content = message.content.strip()
    user_id = str(message.author.id)

    # Commands: run commands, do NOT delete command messages, do NOT count as guesses
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

    # Admin/mod commands
    if content == "!listquestions":
        if not is_admin_or_mod(message.author):
            await message.channel.send("❌ You do not have permission to use this command.")
            return
        if not submitted_questions:
            await message.channel.send("No submitted questions available.")
            return
        lines = []
        for q in submitted_questions:
            lines.append(f"ID: `{q['id']}` - Q: {q['question']} (Submitted by <@{q.get('submitter_id', 'unknown')}>)")
        # Send in chunks if too long
        chunk_size = 10
        for i in range(0, len(lines), chunk_size):
            await message.channel.send("\n".join(lines[i:i+chunk_size]))
        return

    if content.startswith("!removequestion "):
        if not is_admin_or_mod(message.author):
            await message.channel.send("❌ You do not have permission to use this command.")
            return
        parts = content.split(" ", 1)
        if len(parts) < 2:
            await message.channel.send("Usage: !removequestion <id>")
            return
        qid = parts[1].strip()
        found = False
        for i, q in enumerate(submitted_questions):
            if q.get("id") == qid:
                found = True
                del submitted_questions[i]
                save_json(QUESTIONS_FILE, submitted_questions)
                await message.channel.send(f"✅ Question with ID `{qid}` removed.")
                break
        if not found:
            await message.channel.send(f"❌ No question found with ID `{qid}`.")
        return

    # Guessing logic inside the designated channel only
    if current_riddle and not current_answer_revealed:
        # Allow slash commands (they won't hit on_message)
        # Check if user already answered correctly
        if user_id in correct_users:
            if content.startswith("!"):
                # Allow commands even if user already guessed correctly
                return
            # Delete any further guesses after correct answer without penalty
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

        guess_attempts[user_id] = user_attempts + 1
        guess = content.lower()
        correct_answer = current_riddle["answer"].lower()

        # Accept minor plural (simple rstrip s) as correct
        if guess == correct_answer or guess.rstrip("s") == correct_answer.rstrip("s"):
            correct_users.add(user_id)
            # Award point only once per user per riddle
            if user_id not in scores:
                scores[user_id] = 0
            # Add point only if not already added
            if guess_attempts[user_id] == 1 or user_id not in correct_users:
                scores[user_id] = max(0, scores.get(user_id, 0) + 1)
                streaks[user_id] = streaks.get(user_id, 0) + 1
                save_all_scores()

            await message.channel.send(
                f"🎉 Correct, {message.author.mention}! Keep it up! 🏅 Your current score: {scores.get(user_id,0)}\n"
                f"⏳ Answer will be revealed in {format_countdown()}."
            )
            try:
                await message.delete()
            except Exception:
                pass
            return
        else:
            remaining = 5 - guess_attempts[user_id]
            # On last incorrect guess warn about point loss on next guess
            if remaining == 0:
                # Deduct 1 point but never below zero
                scores[user_id] = max(0, scores.get(user_id, 0) - 1)
                streaks[user_id] = 0  # reset streak on failure
                save_all_scores()
                await message.channel.send(
                    f"❌ Sorry, that answer is incorrect, {message.author.mention}. You have no guesses left and lost 1 point.\n"
                    f"⏳ Answer will be revealed in {format_countdown()}."
                )
            elif remaining == 1:
                await message.channel.send(
                    f"❌ Sorry, that answer is incorrect, {message.author.mention} ({remaining} guess remaining). "
                    "If you guess incorrectly again, you will lose 1 point.\n"
                    f"⏳ Answer will be revealed in {format_countdown()}."
                )
            else:
                await message.channel.send(
                    f"❌ Sorry, that answer is incorrect, {message.author.mention} ({remaining} guesses remaining).\n"
                    f"⏳ Answer will be revealed in {format_countdown()}."
                )

            try:
                await message.delete()
            except Exception:
                pass
            return

@tree.command(name="submitriddle", description="Submit a new riddle with question and answer")
async def submitriddle(interaction: discord.Interaction):
    # Start the submission modal for question and answer input
    class SubmitRiddleModal(discord.ui.Modal, title="Submit a new riddle"):
        question = discord.ui.TextInput(label="Riddle Question", style=discord.TextStyle.paragraph, max_length=500)
        answer = discord.ui.TextInput(label="Riddle Answer", style=discord.TextStyle.short, max_length=100)

        async def on_submit(self, interaction: discord.Interaction):
            new_id = str(int(datetime.utcnow().timestamp() * 1000)) + "_" + str(interaction.user.id)
            submitted_questions.append({
                "id": new_id,
                "question": self.question.value.strip(),
                "answer": self.answer.value.strip(),
                "submitter_id": str(interaction.user.id)
            })
            save_json(QUESTIONS_FILE, submitted_questions)
            await interaction.response.send_message(f"✅ Thanks {interaction.user.mention}, your riddle has been submitted! It will appear in the queue soon.", ephemeral=True)

        async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
            await interaction.response.send_message("❌ An error occurred while submitting your riddle.", ephemeral=True)

    await interaction.response.send_modal(SubmitRiddleModal())

@tree.command(name="riddleofthedaycommands", description="View all available Riddle of the Day commands")
async def riddleofthedaycommands(interaction: discord.Interaction):
    commands = """
**Available Riddle Bot Commands:**
• `/submitriddle` – Submit a new riddle.
• `!score` – View your score and rank.
• `!leaderboard` – Show the top solvers.
• `!listquestions` – (Admin/Mod) List all submitted riddles.
• `!removequestion <id>` – (Admin/Mod) Remove a submitted riddle by ID.
• Just type your guess to answer the riddle!
"""
    await interaction.response.send_message(commands, ephemeral=True)

@tasks.loop(time=time(hour=6, minute=0, tzinfo=timezone.utc))
async def post_riddle():
    global current_riddle, current_answer_revealed, correct_users, guess_attempts
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
    guess_attempts.clear()

    question_text = format_question_text(current_riddle)
    submitter_id = current_riddle.get("submitter_id")
    submitter_text = f"<@{submitter_id}>" if submitter_id else "Riddle of the Day bot"

    await channel.send(f"{question_text}\n\n_(Submitted by: {submitter_text})_")

@tasks.loop(time=time(hour=1, minute=0, tzinfo=timezone.utc))
async def reveal_answer():
    global current_answer_revealed
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
            user = await client.fetch_user(int(uid))
            rank = get_rank(scores.get(uid_str, 0), streaks.get(uid_str, 0))
            extra = " 👑 Chopstick Champ (Top Solver)" if uid_str in top_scorers else ""
            lines.append(f"\u2022 {user.mention} (**{scores.get(uid_str, 0)}**, 🔥 {streaks.get(uid_str, 0)}) 🏅 {rank}{extra}")
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
            value=f"Score: **{score}** 🔥 Streak: **{streak}**\nRank: {rank}{extra}",
            inline=False
        )
    msg = await channel.send(embed=embed)

    # Add reaction controls for paging
    await msg.add_reaction("⬅️")
    await msg.add_reaction("➡️")

    # Save message id for reaction paging
    leaderboard_pages[user_id] = page

@client.event
async def on_reaction_add(reaction, user):
    if user.bot:
        return

    channel_id = int(os.getenv("DISCORD_CHANNEL_ID", "0"))
    if reaction.message.channel.id != channel_id:
        return

    if reaction.emoji not in ["⬅️", "➡️"]:
        return

    user_id = str(user.id)
    if user_id not in leaderboard_pages:
        return

    if reaction.message.author != client.user:
        return

    page = leaderboard_pages[user_id]
    sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    total_pages = max((len(sorted_scores) - 1) // 10 + 1, 1)

    if reaction.emoji == "⬅️":
        page = max(0, page - 1)
    elif reaction.emoji == "➡️":
        page = min(total_pages - 1, page + 1)
    leaderboard_pages[user_id] = page

    await reaction.message.delete()
    await show_leaderboard(reaction.message.channel, user_id)

if __name__ == "__main__":
    TOKEN = os.getenv("DISCORD_BOT_TOKEN")
    if not TOKEN:
        print("Error: DISCORD_BOT_TOKEN environment variable not set.")
        exit(1)
    client.run(TOKEN)
