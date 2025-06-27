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

@client.event
async def on_ready():
    global purged_on_startup, current_riddle, current_answer_revealed, correct_users, guess_attempts

    print(f"Logged in as {client.user} (ID: {client.user.id})")
    print("------")

    # Optionally sync only to a guild for faster command registration during dev
    GUILD_ID = os.getenv("DISCORD_GUILD_ID")
    if GUILD_ID:
        guild_obj = discord.Object(id=int(GUILD_ID))
        await tree.sync(guild=guild_obj)
        print(f"Synced commands to guild {GUILD_ID}")
    else:
        await tree.sync()
        print("Synced global commands")

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

@client.event
async def on_message(message):
    if message.author.bot:
        return

    channel_id = int(os.getenv("DISCORD_CHANNEL_ID", "0"))
    if message.channel.id != channel_id:
        # Outside designated channel, allow commands but no guess processing or deletion
        if message.content.startswith("!"):
            return
        return

    content = message.content.strip()
    user_id = str(message.author.id)

    # This block is for legacy text commands that are now slash commands
    # You can remove this block if you fully moved to slash commands
    # but keeping it for score and leaderboard commands
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

    # Guessing logic inside the designated channel only
    if current_riddle and not current_answer_revealed:
        if user_id in correct_users:
            if content.startswith("!"):
                return
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

        if guess == correct_answer or guess.rstrip("s") == correct_answer.rstrip("s"):
            correct_users.add(user_id)
            # Award point only once per user per riddle
            if user_id not in scores:
                scores[user_id] = 0
            # Prevent awarding point multiple times for same user
            # so this condition is only for the first correct guess:
            if guess_attempts[user_id] == 1:
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
            remaining = 5 - guess_attempts[user_id]
            if remaining == 0:
                scores[user_id] = max(0, scores.get(user_id, 0) - 1)
                streaks[user_id] = 0
                save_all_scores()
                await message.channel.send(
                    f"❌ Sorry, that answer is incorrect, {message.author.mention}. You have no guesses left and lost 1 point."
                )
            elif remaining == 1:
                await message.channel.send(
                    f"❌ Sorry, that answer is incorrect, {message.author.mention} ({remaining} guess remaining). If you guess incorrectly again, you will lose 1 point."
                )
            else:
                await message.channel.send(
                    f"❌ Sorry, that answer is incorrect, {message.author.mention} ({remaining} guesses remaining)."
                )
            try:
                await message.delete()
            except Exception:
                pass
            return

# Slash command: /listquestions (admin/mod only)
@tree.command(name="listquestions", description="List all submitted riddles")
@app_commands.checks.has_permissions(manage_guild=True)
async def listquestions(interaction: discord.Interaction):
    if not submitted_questions:
        await interaction.response.send_message("📭 No riddles found in the queue.", ephemeral=True)
        return

    lines = [f"📋 Total riddles: {len(submitted_questions)}"]
    for idx, q in enumerate(submitted_questions, start=1):
        lines.append(f"{idx}. {q['question']}")

    # Discord messages max 2000 chars - send in chunks of 10 lines
    chunks = [lines[i:i+10] for i in range(0, len(lines), 10)]
    for chunk in chunks:
        await interaction.followup.send("\n".join(chunk), ephemeral=True)

# Modal to prompt question number for removal
class RemoveQuestionModal(discord.ui.Modal, title="Remove a Submitted Riddle"):
    question_number = discord.ui.TextInput(label="Riddle number to remove", placeholder="Enter a number")

    def __init__(self, interaction: discord.Interaction):
        super().__init__()
        self.interaction = interaction

    async def on_submit(self, interaction: discord.Interaction):
        try:
            num = int(self.question_number.value.strip())
            if num < 1 or num > len(submitted_questions):
                await interaction.response.send_message(
                    f"⚠️ Invalid question number `{num}`. Please use a number between 1 and {len(submitted_questions)}.",
                    ephemeral=True,
                )
                return
            removed_question = submitted_questions.pop(num - 1)
            save_json(QUESTIONS_FILE, submitted_questions)
            await interaction.response.send_message(
                f"✅ Removed riddle #{num}: \"{removed_question['question']}\"",
                ephemeral=True,
            )
        except ValueError:
            await interaction.response.send_message(
                "⚠️ That doesn't look like a valid number. Please try /removequestion again.",
                ephemeral=True,
            )
        except Exception as e:
            await interaction.response.send_message(
                f"⚠️ An error occurred while removing the question: {e}", ephemeral=True
            )

# Slash command: /removequestion (admin/mod only)
@tree.command(name="removequestion", description="Remove a submitted riddle by number")
@app_commands.checks.has_permissions(manage_guild=True)
async def removequestion(interaction: discord.Interaction):
    modal = RemoveQuestionModal(interaction)
    await interaction.response.send_modal(modal)

# Slash command: /score to show user's score
@tree.command(name="score", description="View your score and rank")
async def score(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    score_val = scores.get(user_id, 0)
    streak = streaks.get(user_id, 0)
    rank = get_rank(score_val, streak)
    await interaction.response.send_message(
        f"📊 {interaction.user.display_name}'s score: **{score_val}**, 🔥 Streak: {streak}\n🏅 Rank: {rank}",
        ephemeral=True
    )

# Slash command: /leaderboard to show top solvers
@tree.command(name="leaderboard", description="Show the top solvers")
async def leaderboard(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    leaderboard_pages[user_id] = 0
    await show_leaderboard(interaction.channel, user_id)

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

    for i, (uid, score_val) in enumerate(sorted_scores[start:start + 10], start=start + 1):
        try:
            user = await client.fetch_user(int(uid))
            streak = streaks.get(uid, 0)
            rank = get_rank(score_val, streak)
            extra = " 👑 Chopstick Champ (Top Solver)" if uid in top_scorers else ""
            embed.add_field(name=f"{i}. {user.display_name}", value=f"Score: {score_val} | Streak: {streak}\nRank: {rank}{extra}", inline=False)
        except Exception:
            embed.add_field(name=f"{i}. Unknown User", value=f"Score: {score_val}", inline=False)

    await channel.send(embed=embed)

# Slash command: /riddleofthedaycommands to show available commands
@tree.command(name="riddleofthedaycommands", description="View all available Riddle of the Day commands")
async def riddleofthedaycommands(interaction: discord.Interaction):
    commands = """
**Available Riddle Bot Commands:**
• `/score` – View your score and rank.
• `/submitriddle` – Submit a new riddle using the modal form.
• `/leaderboard` – Show the top solvers.
• `/listquestions` – List all submitted riddles (admin only).
• `/removequestion` – Remove a riddle by number (admin only).
• Just type your guess to answer the riddle!
"""
    await interaction.response.send_message(commands, ephemeral=True)

# Slash command /submitriddle now prompts user step-by-step like Dank Memer's /rob
@tree.command(name="submitriddle", description="Submit a new riddle step-by-step")
async def submitriddle(interaction: discord.Interaction):
    await interaction.response.send_message("✍️ What's your riddle question? (Check your DMs!)", ephemeral=True)

    def check(m):
        return m.author.id == interaction.user.id and isinstance(m.channel, discord.DMChannel)

    try:
        dm_channel = await interaction.user.create_dm()
        await dm_channel.send("✍️ Please enter your riddle question:")
        question_msg = await client.wait_for('message', timeout=120.0, check=check)
        question = question_msg.content.strip()

        await dm_channel.send("💡 Now enter the answer to your riddle:")
        answer_msg = await client.wait_for('message', timeout=120.0, check=check)
        answer = answer_msg.content.strip()

        if not question or not answer:
            await dm_channel.send("⚠️ Invalid submission. Both question and answer must be provided.")
            return

        user_id = str(interaction.user.id)
        new_id = str(int(datetime.utcnow().timestamp() * 1000)) + "_" + user_id
        submitted_questions.append({
            "id": new_id,
            "question": question,
            "answer": answer,
            "submitter_id": user_id
        })
        save_json(QUESTIONS_FILE, submitted_questions)
        await dm_channel.send("✅ Your riddle has been submitted! Thank you!")
        await interaction.followup.send("✅ Submission complete!", ephemeral=True)

    except asyncio.TimeoutError:
        await interaction.followup.send("⏰ You took too long to respond. Please try /submitriddle again.", ephemeral=True)

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

@tasks.loop(time=time(hour=23, minute=0, tzinfo=timezone.utc))
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
        lines = [f"✅ The correct answer is: **{correct_answer}**"]
        lines.append("🎉 Congratulations to the following solvers:")
        for uid in correct_users:
            try:
                user = await client.fetch_user(int(uid))
                lines.append(f"• {user.display_name}")
            except Exception:
                lines.append("• Unknown user")
    else:
        lines = [f"⚠️ The correct answer was: **{correct_answer}**"]
        lines.append("No one guessed correctly this time.")

    lines.append(f"\n_(Riddle submitted by: {submitter_text})_")
    await channel.send("\n".join(lines))

@tree.error
async def on_app_command_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("⛔ You don't have permission to run this command.", ephemeral=True)
    else:
        raise error

# Run bot
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
if not DISCORD_BOT_TOKEN:
    print("Please set the DISCORD_BOT_TOKEN environment variable!")
else:
    client.run(DISCORD_BOT_TOKEN)
