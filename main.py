import discord
from discord.ext import tasks
import asyncio
import json
import os
from datetime import datetime, time, timezone, timedelta, date
import random
from discord import app_commands

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

max_id = 0  # tracks max numeric ID assigned

submission_dates = {}  # user_id -> date of last submission point awarded


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
    if scores:
        max_score = max(scores.values())
        if score == max_score and max_score > 0:
            return "🍣 Master Sushi Chef (Top scorer)"
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
    base = f"@everyone {qdict['id']}. {qdict['question']} ***(Answer will be revealed at 23:00 UTC)***"
    remaining = count_unused_questions()
    base += "\n\n💡 Use the /submitriddle command to submit your own riddle."
    if remaining < 5:
        base += "\n\n⚠️ Less than 5 new riddles remain - submit a new riddle with /submitriddle to add it to the queue!"
    return base

def get_next_id():
    global max_id
    max_id += 1
    return str(max_id)


# --- Load data and initialize max_id ---
submitted_questions = load_json(QUESTIONS_FILE)
scores = load_json(SCORES_FILE)
streaks = load_json(STREAKS_FILE)

# Initialize max_id from existing question IDs (assuming numeric IDs)
existing_ids = [int(q["id"]) for q in submitted_questions if q.get("id") and str(q["id"]).isdigit()]
max_id = max(existing_ids) if existing_ids else 0


# --- /listriddles command ---
class QuestionListView(discord.ui.View):
    def __init__(self, user_id, questions, per_page=10):
        super().__init__(timeout=300)
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
        for q in page_questions:
            qid = q.get("id", "NA")
            lines.append(f"{qid}. {q['question']}")
        return "\n".join(lines)

    async def update_message(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("⛔ This pagination isn't for you.", ephemeral=True)
            return
        await interaction.response.edit_message(content=self.get_page_content(), view=self)

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

@tree.command(name="listriddles", description="List all submitted riddles")
@app_commands.checks.has_permissions(manage_guild=True)
async def listriddles(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    if not submitted_questions:
        await interaction.followup.send("📭 No riddles found in the queue.", ephemeral=True)
        return
    view = QuestionListView(interaction.user.id, submitted_questions)
    await interaction.followup.send(content=view.get_page_content(), view=view, ephemeral=True)

@tree.command(name="removeriddle", description="Remove a submitted riddle by ID")
@app_commands.checks.has_permissions(manage_guild=True)
async def removeriddle(interaction: discord.Interaction):
    class RemoveRiddleModal(discord.ui.Modal, title="Remove a Riddle"):
        question_id = discord.ui.TextInput(
            label="Enter the ID of the riddle to remove",
            placeholder="e.g. 3",
            required=True,
            max_length=10
        )
        async def on_submit(self, modal_interaction: discord.Interaction):
            qid = self.question_id.value.strip()
            idx = next((i for i, q in enumerate(submitted_questions) if q.get("id") == qid), None)
            if idx is None:
                await modal_interaction.response.send_message(f"⚠️ No riddle found with ID `{qid}`.", ephemeral=True)
                return
            removed = submitted_questions.pop(idx)
            save_json(QUESTIONS_FILE, submitted_questions)
            await modal_interaction.response.send_message(f"✅ Removed riddle ID {qid}: \"{removed['question']}\"", ephemeral=True)
    await interaction.response.send_modal(RemoveRiddleModal())


# --- Submit riddle modal ---
class SubmitRiddleModal(discord.ui.Modal, title="Submit a New Riddle"):
    question = discord.ui.TextInput(
        label="Riddle Question",
        style=discord.TextStyle.paragraph,
        placeholder="Enter your riddle question here",
        required=True,
        max_length=1000
    )
    answer = discord.ui.TextInput(
        label="Answer",
        style=discord.TextStyle.paragraph,
        placeholder="Enter the answer here",
        required=True,
        max_length=500
    )

    async def on_submit(self, interaction: discord.Interaction):
        global max_id
        q = self.question.value.strip().replace("\n", " ").replace("\r", " ")
        a = self.answer.value.strip()

        q_normalized = q.lower().replace(" ", "")
        for existing in submitted_questions:
            existing_q = existing["question"].strip().lower().replace(" ", "")
            if existing_q == q_normalized:
                await interaction.response.send_message("⚠️ This riddle has already been submitted. Please try a different one.", ephemeral=True)
                return

        new_id = get_next_id()
        uid = str(interaction.user.id)
        submitted_questions.append({
            "id": new_id,
            "question": q,
            "answer": a,
            "submitter_id": uid
        })
        save_json(QUESTIONS_FILE, submitted_questions)

        # Notify admins/moderators via DM (no channel message)
        # Find all guild members with manage_guild permission and DM them
        for guild in client.guilds:
            for member in guild.members:
                if member.guild_permissions.manage_guild and not member.bot:
                    try:
                        dm = await member.create_dm()
                        await dm.send(f"🧠 @{interaction.user.display_name} has submitted a new Riddle of the Day. Use /listriddles to view the question and /removeriddle if moderation is needed.")
                    except Exception:
                        pass  # Ignore DM failures

        # Award point to submitter once per day
        today = date.today()
        last_award_date = submission_dates.get(uid)
        awarded_point_msg = ""
        if last_award_date != today:
            scores[uid] = scores.get(uid, 0) + 1
            save_json(SCORES_FILE, scores)
            submission_dates[uid] = today
            awarded_point_msg = "\n🏅 You’ve also been awarded **1 point** for your submission!"
        else:
            awarded_point_msg = "\n⚠️ You have already received your submission point today. Submit another riddle tomorrow for more points."

        # DM submitter confirmation + info
        try:
            dm = await interaction.user.create_dm()
            await dm.send(
                "✅ Thanks for submitting a riddle! It is now in the queue.\n"
                "⚠️ You will **not** be able to answer your own riddle when it is posted."
                + awarded_point_msg
            )
        except discord.Forbidden:
            pass

        await interaction.response.send_message("✅ Your riddle has been submitted and added to the queue! Check your DMs.", ephemeral=True)


@tree.command(name="submitriddle", description="Submit a new riddle via a form")
async def submitriddle(interaction: discord.Interaction):
    await interaction.response.send_modal(SubmitRiddleModal())


@tree.command(name="addpoints", description="Add 1 point to a user's score")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.describe(user="The user to award a point to")
async def addpoints(interaction: discord.Interaction, user: discord.User):
    uid = str(user.id)
    scores[uid] = scores.get(uid, 0) + 1
    streaks[uid] = streaks.get(uid, 0) + 1
    save_all_scores()
    await interaction.response.send_message(
        f"✅ Added 1 point and 1 streak to {user.mention}. New score: {scores[uid]}, new streak: {streaks[uid]}",
        ephemeral=True
    )

@tree.command(name="removepoint", description="Remove 1 point from a user's score")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.describe(user="The user to remove a point from")
async def removepoint(interaction: discord.Interaction, user: discord.User):
    uid = str(user.id)
    scores[uid] = max(0, scores.get(uid, 0) - 1)
    streaks[uid] = 0
    save_all_scores()
    await interaction.response.send_message(
        f"❌ Removed 1 point and reset streak for {user.mention}. New score: {scores[uid]}, streak reset to 0.",
        ephemeral=True
    )

@tree.command(name="score", description="View your score and rank")
async def score(interaction: discord.Interaction):
    uid = str(interaction.user.id)
    sv = scores.get(uid, 0)
    st = streaks.get(uid, 0)
    await interaction.response.send_message(
        f"📊 {interaction.user.display_name}'s score: **{sv}**, 🔥 Streak: {st}\n🏅 {get_rank(sv, st)}",
        ephemeral=True
    )


# --- Updated /leaderboard command with pagination ---
class LeaderboardView(discord.ui.View):
    def __init__(self, user_id):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.current_page = 0
        self.sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        self.total_pages = max((len(self.sorted_scores) - 1) // 10 + 1, 1)

    async def format_page(self):
        start = self.current_page * 10
        end = start + 10
        embed = discord.Embed(
            title=f"🏆 Riddle Leaderboard ({self.current_page + 1}/{self.total_pages})",
            color=discord.Color.gold()
        )
        for i, (uid, sv) in enumerate(self.sorted_scores[start:end], start=start + 1):
            try:
                user = client.get_user(int(uid)) or await client.fetch_user(int(uid))
                name = user.display_name
            except:
                name = "Unknown"
            st = streaks.get(uid, 0)
            embed.add_field(name=f"{i}. {name}", value=f"Score: {sv} | Streak: {st}\nRank: {get_rank(sv, st)}", inline=False)
        return embed

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary)
    async def previous_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("⛔ This leaderboard isn't for you.", ephemeral=True)
            return
        if self.current_page > 0:
            self.current_page -= 1
            embed = await self.format_page()
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.response.send_message("⛔ Already at the first page.", ephemeral=True)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("⛔ This leaderboard isn't for you.", ephemeral=True)
            return
        if self.current_page < self.total_pages - 1:
            self.current_page += 1
            embed = await self.format_page()
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.response.send_message("⛔ Already at the last page.", ephemeral=True)


@tree.command(name="leaderboard", description="Show the top solvers")
async def leaderboard(interaction: discord.Interaction):
    if not scores:
        await interaction.response.send_message("📭 No scores available yet.", ephemeral=True)
        return
    view = LeaderboardView(interaction.user.id)
    embed = await view.format_page()
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


# --- Rest of your code unchanged ---


@client.event
async def on_message(message):
    if message.author.bot:
        return

    ch_id = int(os.getenv("DISCORD_CHANNEL_ID") or 0)
    if message.channel.id != ch_id:
        return

    global correct_users, guess_attempts, deducted_for_user, current_riddle

    user_id = str(message.author.id)
    content = message.content.strip()

    if not current_riddle or current_answer_revealed:
        return

    # Block submitter from answering their own riddle, without breaking their streak
    if current_riddle.get("submitter_id") == user_id:
        try: await message.delete()
        except: pass
        await message.channel.send(f"⛔ You submitted this riddle and cannot answer it, {message.author.mention}.", delete_after=10)
        return

    if user_id in correct_users:
        try: await message.delete()
        except: pass
        await message.channel.send(f"✅ You already answered correctly, {message.author.mention}.", delete_after=10)
        return

    # Commands do not count as guesses
    if content.startswith("!"):
        return

    # Initialize guess count
    guess_attempts.setdefault(user_id, 0)

    if guess_attempts[user_id] >= 5:
        try: await message.delete()
        except: pass
        await message.channel.send(f"⛔ You have used all 5 guesses for today's riddle, {message.author.mention}.", delete_after=10)
        return

    # Check guess against answer (case-insensitive)
    answer = current_riddle.get("answer", "").lower().strip()
    guess = content.lower().strip()

    guess_attempts[user_id] += 1

    if guess == answer:
        correct_users.add(user_id)
        # Award 1 point if not already awarded this riddle
        if scores.get(user_id) is None:
            scores[user_id] = 0
        scores[user_id] += 1
        streaks[user_id] = streaks.get(user_id, 0) + 1
        save_all_scores()
        await message.channel.send(f"🎉 Correct answer, {message.author.mention}! You earned 1 point and your streak is now {streaks[user_id]}.", delete_after=10)
        try:
            await message.delete()
        except:
            pass
    else:
        # Wrong guess
        if guess_attempts[user_id] == 5 and user_id not in correct_users and user_id not in deducted_for_user:
            # Deduct 1 point and reset streak
            scores[user_id] = max(0, scores.get(user_id, 0) - 1)
            streaks[user_id] = 0
            deducted_for_user.add(user_id)
            save_all_scores()
            await message.channel.send(f"❌ You've used all 5 guesses and did not answer correctly, {message.author.mention}. 1 point deducted and your streak reset to 0.", delete_after=15)
        else:
            tries_left = 5 - guess_attempts[user_id]
            await message.channel.send(f"❌ Incorrect guess, {message.author.mention}. You have {tries_left} guesses left.", delete_after=10)
        try:
            await message.delete()
        except:
            pass


@tasks.loop(time=time(hour=19, minute=0, tzinfo=timezone.utc))
async def post_daily_riddle():
    global current_riddle, current_answer_revealed, correct_users, guess_attempts, deducted_for_user

    channel_id = int(os.getenv("DISCORD_CHANNEL_ID") or 0)
    channel = client.get_channel(channel_id)
    if not channel:
        print("Channel not found")
        return

    # Pick and post new riddle
    current_riddle = pick_next_riddle()
    current_answer_revealed = False
    correct_users.clear()
    guess_attempts.clear()
    deducted_for_user.clear()

    text = format_question_text(current_riddle)
    await channel.send(text)


@tasks.loop(time=time(hour=3, minute=0, tzinfo=timezone.utc))
async def reveal_answer():
    global current_answer_revealed, streaks

    channel_id = int(os.getenv("DISCORD_CHANNEL_ID") or 0)
    channel = client.get_channel(channel_id)
    if not channel:
        print("Channel not found")
        return

    if not current_riddle or current_answer_revealed:
        return

    current_answer_revealed = True
    answer_text = current_riddle.get("answer", "No answer found")

    # List users who answered correctly
    if correct_users:
        mentions = []
        for uid in correct_users:
            try:
                user = await client.fetch_user(int(uid))
                mentions.append(user.mention)
            except:
                mentions.append(f"<@{uid}>")
        correct_str = ", ".join(mentions)
        msg = (
            f"✅ The answer to today's riddle is:\n**{answer_text}**\n\n"
            f"🎉 Correct answers by: {correct_str}\n\n"
            "💡 Use the /submitriddle command to submit your own riddle."
        )
    else:
        msg = (
            f"❌ No one answered today's riddle correctly.\n"
            f"The answer was:\n**{answer_text}**\n\n"
            "💡 Use the /submitriddle command to submit your own riddle."
        )

    await channel.send(msg)

    # Reset streaks for users who did not answer correctly AND
    # are not the submitter of the riddle
    for uid in scores.keys():
        if uid not in correct_users and uid != current_riddle.get("submitter_id"):
            streaks[uid] = 0
    save_all_scores()


@client.event
async def on_ready():
    print(f"Logged in as {client.user} (ID: {client.user.id})")
    print("------")
    try:
        await tree.sync()
        print("Commands synced")
    except Exception as e:
        print(f"Failed to sync commands: {e}")
    post_daily_riddle.start()
    reveal_answer.start()


TOKEN = os.getenv("DISCORD_BOT_TOKEN")
client.run(TOKEN)
