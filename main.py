import discord
from discord.ext import tasks
import asyncio
import json
import os
from datetime import datetime, time, timezone, timedelta
import random
from discord import app_commands

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
guess_attempts = {}  # user_id -> guesses used this riddle
deducted_for_user = set()  # users who lost 1 point this riddle

leaderboard_pages = {}

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
    global current_riddle, current_answer_revealed, correct_users, guess_attempts, deducted_for_user

    print(f"Logged in as {client.user} (ID: {client.user.id})")
    print("------")

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
        if channel:
            # Purge once on startup if desired
            await purge_channel_messages(channel)

    # Initialize riddle state if none
    if not current_riddle:
        await post_special_riddle()

    post_riddle.start()
    reveal_answer.start()

async def post_special_riddle():
    global current_riddle, current_answer_revealed, correct_users, guess_attempts, deducted_for_user

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
    correct_users.clear()
    guess_attempts.clear()
    deducted_for_user.clear()

    question_text = format_question_text(current_riddle)
    await channel.send(f"{question_text}\n\n_(Submitted by: Riddle of the Day bot)_")

@client.event
async def on_message(message):
    if message.author.bot:
        return

    channel_id = int(os.getenv("DISCORD_CHANNEL_ID", "0"))
    if message.channel.id != channel_id:
        return

    global correct_users, guess_attempts, deducted_for_user, current_riddle

    user_id = str(message.author.id)
    content = message.content.strip()

    if not current_riddle or current_answer_revealed:
        return

    # If user already answered correctly this riddle
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

    # Accept minor plural form
    if guess == correct_answer or guess.rstrip("s") == correct_answer.rstrip("s"):
        correct_users.add(user_id)
        # Add 1 point only once per user per riddle
        scores[user_id] = scores.get(user_id, 0) + 1
        streaks[user_id] = streaks.get(user_id, 0) + 1
        save_all_scores()
        try:
            await message.delete()
        except:
            pass
        await message.channel.send(f"🎉 Correct, {message.author.mention}! Your total score: {scores[user_id]}", delete_after=8)

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

    # Calculate time until answer reveal and send countdown message
    now_utc = datetime.utcnow().replace(tzinfo=timezone.utc)

    today_utc = now_utc.date()
    reveal_time_today = datetime.combine(today_utc + timedelta(days=1), time(hour=1, minute=0, tzinfo=timezone.utc))
    reveal_time_tomorrow = datetime.combine(today_utc, time(hour=23, minute=0, tzinfo=timezone.utc))
    post_time_tomorrow = datetime.combine(today_utc, time(hour=7, minute=0, tzinfo=timezone.utc))

    if now_utc < post_time_tomorrow:
        reveal_dt = reveal_time_today
    else:
        reveal_dt = reveal_time_tomorrow

    if reveal_dt <= now_utc:
        reveal_dt += timedelta(days=1)

    delta = reveal_dt - now_utc
    hours, remainder = divmod(int(delta.total_seconds()), 3600)
    minutes = remainder // 60

    countdown_msg = f"⏳ Answer will be revealed in {hours} hour{'s' if hours != 1 else ''} {minutes} minute{'s' if minutes != 1 else ''}."
    await message.channel.send(countdown_msg, delete_after=12)

# --- PAGINATED LISTQUESTIONS COMMAND ---

class ListQuestionsView(discord.ui.View):
    def __init__(self, user_id, questions, per_page=10, timeout=180):
        super().__init__(timeout=timeout)
        self.user_id = user_id
        self.questions = questions
        self.per_page = per_page
        self.current_page = 0
        self.total_pages = max(1, (len(self.questions) - 1) // self.per_page + 1)

        # Disable prev button on first page
        self.prev_button.disabled = True
        if self.total_pages <= 1:
            self.next_button.disabled = True

    def get_page_content(self):
        start = self.current_page * self.per_page
        end = start + self.per_page
        page_questions = self.questions[start:end]
        lines = [f"📋 Total riddles: {len(self.questions)}\n"]
        for idx, q in enumerate(page_questions, start=start + 1):
            lines.append(f"{idx}. {q['question']}")
        return "\n".join(lines)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("⚠️ You cannot control this pagination.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.primary, disabled=True)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page > 0:
            self.current_page -= 1
            # Enable/disable buttons accordingly
            self.next_button.disabled = False
            if self.current_page == 0:
                button.disabled = True
            self.update_buttons()
            await interaction.response.edit_message(content=self.get_page_content(), view=self)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.primary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page < self.total_pages - 1:
            self.current_page += 1
            # Enable/disable buttons accordingly
            self.prev_button.disabled = False
            if self.current_page == self.total_pages - 1:
                button.disabled = True
            self.update_buttons()
            await interaction.response.edit_message(content=self.get_page_content(), view=self)

    def update_buttons(self):
        # Sync button disabled states
        self.prev_button.disabled = (self.current_page == 0)
        self.next_button.disabled = (self.current_page == self.total_pages - 1)

@tree.command(name="listquestions", description="List all submitted riddles")
@app_commands.checks.has_permissions(manage_guild=True)
async def listquestions(interaction: discord.Interaction):
    if not submitted_questions:
        await interaction.response.send_message("📭 No riddles found in the queue.", ephemeral=True)
        return

    view = ListQuestionsView(user_id=interaction.user.id, questions=submitted_questions, per_page=10)
    await interaction.response.send_message(content=view.get_page_content(), view=view, ephemeral=True)

# --- Rest of commands unchanged ---

@tree.command(name="removequestion", description="Remove a submitted riddle by number")
@app_commands.checks.has_permissions(manage_guild=True)
async def removequestion(interaction: discord.Interaction):
    class RemoveQuestionModal(discord.ui.Modal, title="Remove a Riddle"):
        question_number = discord.ui.TextInput(
            label="Enter the number of the riddle to remove",
            placeholder="e.g. 3",
            required=True,
            max_length=5
        )

        async def on_submit(self, modal_interaction: discord.Interaction):
            try:
                num = int(self.question_number.value.strip())
                if num < 1 or num > len(submitted_questions):
                    await modal_interaction.response.send_message(
                        f"⚠️ Invalid question number `{num}`. Please provide a number between 1 and {len(submitted_questions)}.",
                        ephemeral=True
                    )
                    return
                removed = submitted_questions.pop(num - 1)
                save_json(QUESTIONS_FILE, submitted_questions)
                await modal_interaction.response.send_message(f"✅ Removed riddle #{num}: \"{removed['question']}\"", ephemeral=True)
            except ValueError:
                await modal_interaction.response.send_message("⚠️ Please enter a valid number.", ephemeral=True)

    await interaction.response.send_modal(RemoveQuestionModal())

@tree.command(name="score", description="View your score and rank")
async def score(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    score_val = scores.get(user_id, 0)
    streak_val = streaks.get(user_id, 0)
    rank = get_rank(score_val, streak_val)
    await interaction.response.send_message(
        f"📊 {interaction.user.display_name}'s score: **{score_val}**, 🔥 Streak: {streak_val}\n🏅 Rank: {rank}",
        ephemeral=True
    )

@tree.command(name="leaderboard", description="Show the top solvers")
async def leaderboard(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    leaderboard_pages[user_id] = 0
    await show_leaderboard(interaction.channel, user_id)
    await interaction.response.send_message("📋 Showing leaderboard...", ephemeral=True)

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
            streak_val = streaks.get(uid, 0)
            rank = get_rank(score_val, streak_val)
            extra = " 👑 Chopstick Champ (Top Solver)" if uid in top_scorers else ""
            embed.add_field(name=f"{i}. {user.display_name}", value=f"Score: {score_val} | Streak: {streak_val}\nRank: {rank}{extra}", inline=False)
        except Exception:
            embed.add_field(name=f"{i}. Unknown user", value=f"Score: {score_val}", inline=False)

    await channel.send(embed=embed)

@tree.command(name="submitriddle", description="Submit a new riddle step-by-step")
async def submitriddle(interaction: discord.Interaction):
    await interaction.response.send_message("✍️ Check your DMs to submit a riddle!", ephemeral=True)

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

@tree.command(name="riddleofthedaycommands", description="View all available Riddle of the Day commands")
async def riddleofthedaycommands(interaction: discord.Interaction):
    commands = """
**Available Riddle Bot Commands**
/submitriddle - Submit a new riddle via DM prompt
/listquestions - List all submitted riddles (admin only)
/removequestion - Remove a riddle by number (admin only)
/score - Show your score and rank
/leaderboard - Show the top solvers
"""
    await interaction.response.send_message(commands, ephemeral=True)

# TODO: Your scheduled tasks for posting riddles and revealing answers here (post_riddle, reveal_answer)

# Run bot
DISCORD_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
if not DISCORD_TOKEN:
    print("DISCORD_BOT_TOKEN environment variable is missing.")
    exit(1)

client.run(DISCORD_TOKEN)
