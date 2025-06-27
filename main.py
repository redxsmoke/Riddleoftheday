import discord
from discord.ext import tasks
import asyncio
import json
import os
from datetime import datetime, time, timezone, timedelta
import random
from discord import app_commands

# --- Timezone Setup ---
EST = timezone(timedelta(hours=-5))  # EST fixed offset UTC-5 (no DST)

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
    base = f"@everyone {qdict['question']} ***(Answer will be revealed later this evening)***"
    remaining = count_unused_questions()
    if remaining < 5:
        base += "\n\n⚠️ Less than 5 new riddles remain - submit a new riddle with /submitriddle to add it to the queue!"
    return base

# --- Load data ---
submitted_questions = load_json(QUESTIONS_FILE)
scores = load_json(SCORES_FILE)
streaks = load_json(STREAKS_FILE)

# --- Events ---

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
    channel = client.get_channel(channel_id)
    if not channel:
        print("Channel not found.")
        return

    # On startup post riddle immediately, then answer after 1 minute (testing)
    global current_riddle, current_answer_revealed, correct_users, guess_attempts, deducted_for_user

    current_riddle = pick_next_riddle()
    current_answer_revealed = False
    correct_users.clear()
    guess_attempts.clear()
    deducted_for_user.clear()

    question_text = format_question_text(current_riddle)
    submitter_id = current_riddle.get("submitter_id")
    submitter_text = f"<@{submitter_id}>" if submitter_id else "Riddle of the Day bot"

    await channel.send(f"{question_text}\n\n_(Submitted by: {submitter_text})_")

    # Wait 1 minute then post the answer for testing
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

    # Start daily loops after testing
    post_riddle.start()
    reveal_answer.start()

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
        # Send correct confirmation WITHOUT delete_after so message stays
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

    # --- Countdown message logic ---
    now_utc = datetime.now(timezone.utc)
    now_est = now_utc.astimezone(EST)
    today_est = now_est.date()

    if today_est == datetime.now(EST).date():
        # Today only: countdown to 9:00 PM EST today
        reveal_est = datetime.combine(today_est, time(21, 0), tzinfo=EST)  # 9 PM EST today
        reveal_dt = reveal_est.astimezone(timezone.utc)
        if now_utc >= reveal_dt:
            delta = timedelta(seconds=0)
        else:
            delta = reveal_dt - now_utc
    else:
        # Starting tomorrow: countdown to 23:00 UTC today or next day if past 23:00 UTC
        reveal_dt = datetime.combine(now_utc.date(), time(23, 0), tzinfo=timezone.utc)
        if now_utc >= reveal_dt:
            reveal_dt += timedelta(days=1)
        delta = reveal_dt - now_utc

    hours, remainder = divmod(int(delta.total_seconds()), 3600)
    minutes = remainder // 60
    countdown_msg = f"⏳ Answer will be revealed in {hours} hour{'s' if hours != 1 else ''} {minutes} minute{'s' if minutes != 1 else ''}."
    await message.channel.send(countdown_msg, delete_after=12)

# --- /listquestions with pagination ---

class QuestionListView(discord.ui.View):
    def __init__(self, user_id, questions, per_page=10):
        super().__init__(timeout=300)  # 5 minutes timeout
        self.user_id = user_id
        self.questions = questions
        self.per_page = per_page
        self.current_page = 0
        self.total_pages = (len(questions) - 1) // per_page + 1 if questions else 1

    def get_page_content(self):
        start = self.current_page * self.per_page
        end = start + self.per_page
        page_questions = self.questions[start:end]

        lines = [f"📋 Total riddles: {len(self.questions)}"]
        for idx, q in enumerate(page_questions, start=start + 1):
            lines.append(f"{idx}. {q['question']}")
        return "\n".join(lines)

    async def update_message(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("⛔ This pagination isn't for you.", ephemeral=True)
            return
        content = self.get_page_content()
        await interaction.response.edit_message(content=content, view=self)

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary)
    async def previous_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page > 0:
            self.current_page -= 1
            await self.update_message(interaction)
        else:
            await interaction.response.send_message("⛔ Already at the first page.", ephemeral=True)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page < self.total_pages - 1:
            self.current_page += 1
            await self.update_message(interaction)
        else:
            await interaction.response.send_message("⛔ Already at the last page.", ephemeral=True)

@tree.command(name="listquestions", description="List all submitted riddles")
@app_commands.checks.has_permissions(manage_guild=True)
async def listquestions(interaction: discord.Interaction):
    if not submitted_questions:
        await interaction.response.send_message("📭 No riddles found in the queue.", ephemeral=True)
        return

    view = QuestionListView(interaction.user.id, submitted_questions)
    content = view.get_page_content()
    await interaction.response.send_message(content=content, view=view, ephemeral=True)

# --- Other commands ---

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
        await dm_channel.send("✅ Your riddle has been submitted and will appear soon!")

    except asyncio.TimeoutError:
        await interaction.user.send("⏰ Submission timed out. Please try again with /submitriddle.")

# --- The restored /riddleofthedaycommands command ---

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

# --- Scheduled Tasks ---

@tasks.loop(time=time(19, 15, tzinfo=timezone.utc))  # 7:15 PM UTC daily post time
async def post_riddle():
    global current_riddle, current_answer_revealed, correct_users, guess_attempts, deducted_for_user

    channel_id = int(os.getenv("DISCORD_CHANNEL_ID", "0"))
    channel = client.get_channel(channel_id)
    if not channel:
        print("Channel not found for scheduled post.")
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

@tasks.loop(time=time(0, 0, tzinfo=timezone.utc))  # Midnight UTC reveal
async def reveal_answer():
    global current_answer_revealed

    channel_id = int(os.getenv("DISCORD_CHANNEL_ID", "0"))
    channel = client.get_channel(channel_id)
    if not channel:
        print("Channel not found for scheduled reveal.")
        return

    if not current_riddle or current_answer_revealed:
        return

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
    submitter_id = current_riddle.get("submitter_id")
    submitter_text = f"<@{submitter_id}>" if submitter_id else "Riddle of the Day bot"
    lines.append(f"\n_(Riddle submitted by: {submitter_text})_")

    await channel.send("\n".join(lines))

# --- Run the bot ---

client.run(os.getenv("DISCORD_BOT_TOKEN"))
