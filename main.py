import discord
from discord.ext import tasks
import asyncio
import json
import os
from datetime import datetime, time, timezone, timedelta
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

leaderboard_pages = {}

max_id = 0  # tracks max numeric ID assigned


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
    base = f"@everyone {qdict['id']}. {qdict['question']} ***(Answer will be revealed at 23:00 UTC)***"
    remaining = count_unused_questions()
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


# --- /listquestions command ---
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
        for idx, q in enumerate(page_questions, start=start + 1):
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

@tree.command(name="listquestions", description="List all submitted riddles")
@app_commands.checks.has_permissions(manage_guild=True)
async def listquestions(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    if not submitted_questions:
        await interaction.followup.send("📭 No riddles found in the queue.", ephemeral=True)
        return
    view = QuestionListView(interaction.user.id, submitted_questions)
    await interaction.followup.send(content=view.get_page_content(), view=view, ephemeral=True)

@tree.command(name="removequestion", description="Remove a submitted riddle by ID")
@app_commands.checks.has_permissions(manage_guild=True)
async def removequestion(interaction: discord.Interaction):
    class RemoveQuestionModal(discord.ui.Modal, title="Remove a Riddle"):
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
    await interaction.response.send_modal(RemoveQuestionModal())

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
        # Replace any line breaks with a space to store question as single line
        q = self.question.value.strip().replace("\n", " ").replace("\r", " ")
        a = self.answer.value.strip()

        # Check for duplicates ignoring spaces and case
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
        try:
            dm = await interaction.user.create_dm()
            await dm.send(
                "✅ Thanks for submitting a riddle! It is now in the queue.\n"
                "⚠️ You will **not** be able to answer your own riddle when it is posted."
            )
        except discord.Forbidden:
            pass

        await interaction.response.send_message("✅ Your riddle has been submitted and added to the queue! Check your DMs.", ephemeral=True)

@tree.command(name="submitriddle", description="Submit a new riddle via a form")
async def submitriddle(interaction: discord.Interaction):
    await interaction.response.send_modal(SubmitRiddleModal())

# (The rest of your bot code remains unchanged)

# --- /riddleofthedaycommands command ---
@tree.command(name="riddleofthedaycommands", description="List all available Riddle of the Day commands")
async def riddleofthedaycommands(interaction: discord.Interaction):
    commands_list = """
**Available Riddle of the Day Commands:**

• `/submitriddle` - Submit a new riddle via a form.
• `/listquestions` - (Admin) List all submitted riddles.
• `/removequestion` - (Admin) Remove a riddle by ID.
• `/score` - View your current score and rank.
• `/leaderboard` - Show the top solvers.
• `/addpoints` - (Admin) Add a point to a user.
• `/riddleofthedaycommands` - Show this list of commands.
"""
    await interaction.response.send_message(commands_list, ephemeral=True)


# --- On Ready ---
@client.event
async def on_ready():
    print(f"Logged in as {client.user} (ID: {client.user.id})")
    await tree.sync()
    # Start your tasks here (assuming they exist)
    # daily_purge.start()
    # notify_upcoming_riddle.start()
    # post_riddle.start()
    # reveal_answer.start()

# --- Run bot ---
DISCORD_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
if not DISCORD_TOKEN:
    print("ERROR: DISCORD_BOT_TOKEN environment variable not set.")
else:
    client.run(DISCORD_TOKEN)
