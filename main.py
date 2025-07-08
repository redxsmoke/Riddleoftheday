import discord
from discord.ext import tasks
from discord import app_commands, Interaction, Embed
from discord.ui import View, Button
import asyncio
import json
import os
import re
import random
import traceback
from datetime import datetime, timezone, time


# Constants for file names
QUESTIONS_FILE = "submitted_questions.json"
SCORES_FILE = "scores.json"
STREAKS_FILE = "streaks.json"
SUBMISSION_DATES_FILE = "submission_dates.json"

# Bot intents
intents = discord.Intents.default()
intents.members = True
intents.message_content = True

client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# Global state containers
submitted_questions = []    # List of dicts with riddles, each with id, question, answer, submitter_id
scores = {}                 # user_id (str) -> int score
streaks = {}                # user_id (str) -> int streak count
submission_dates = {}       # user_id (str) -> str date (YYYY-MM-DD) for tracking submissions
used_question_ids = set()   # Set of str IDs used recently

current_riddle = None       # Currently active riddle dict or None
current_answer_revealed = False
correct_users = set()       # user_ids who guessed right this round
guess_attempts = {}         # user_id -> int attempts count for current riddle
deducted_for_user = set()   # user_ids deducted penalty for wrong guess in current riddle

max_id = 0                  # For generating new IDs (incremental)


# Utility: Clamp value to zero minimum
def clamp_min_zero(value):
    return max(0, value)


# Load JSON file or return default empty data
def load_json(filename):
    if os.path.exists(filename):
        try:
            with open(filename, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading {filename}: {e}")
    # Return defaults
    if filename == QUESTIONS_FILE:
        return []
    else:
        return {}


# Save data to JSON file
def save_json(filename, data):
    try:
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"Error saving {filename}: {e}")


# Load all persistent data on bot start
def load_all_data():
    global submitted_questions, scores, streaks, submission_dates, max_id

    submitted_questions = load_json(QUESTIONS_FILE)
    scores = load_json(SCORES_FILE)
    streaks = load_json(STREAKS_FILE)
    submission_dates = load_json(SUBMISSION_DATES_FILE)

    # Determine max ID for new riddle submissions
    existing_ids = []
    for q in submitted_questions:
        if "id" in q and str(q["id"]).isdigit():
            existing_ids.append(int(q["id"]))
    max_id = max(existing_ids) if existing_ids else 0


# Save all score and streak data
def save_all_scores():
    save_json(SCORES_FILE, scores)
    save_json(STREAKS_FILE, streaks)
    save_json(SUBMISSION_DATES_FILE, submission_dates)


# Save all riddles/questions
def save_all_riddles():
    save_json(QUESTIONS_FILE, submitted_questions)


# Call load on startup
load_all_data()

def get_next_id():
    global max_id
    max_id += 1
    return str(max_id)


def pick_next_riddle():
    unused = [q for q in submitted_questions if str(q.get("id")) not in used_question_ids and q.get("id") is not None]
    if not unused:
        used_question_ids.clear()
        unused = [q for q in submitted_questions if q.get("id") is not None]
    if not unused:
        return None
    riddle = random.choice(unused)
    used_question_ids.add(str(riddle["id"]))
    return riddle
STOP_WORDS = {"a", "an", "the", "is", "was", "were", "of", "to", "and", "in", "on", "at", "by"}

def clean_and_filter(text):
    words = re.findall(r'\b\w+\b', text.lower())
    return [w for w in words if w not in STOP_WORDS]


def count_unused_questions():
    return len([q for q in submitted_questions if str(q.get("id")) not in used_question_ids])


def format_question_embed(qdict, submitter=None):
    embed = discord.Embed(
        title=f"🧠 Riddle #{qdict['id']}",
        description=qdict['question'],
        color=discord.Color.blurple()
    )
    embed.set_footer(text="Answer will be revealed at 23:00 UTC. Use /submitriddle to contribute your own!")

    remaining = count_unused_questions()
    if remaining < 5:
        embed.add_field(
            name="⚠️ Riddle Supply Low",
            value="Less than 5 new riddles remain - submit one with `/submitriddle`!",
            inline=False
        )
    if submitter:
        embed.add_field(
            name="Submitted By",
            value=submitter.mention,
            inline=False
        )
    return embed


def get_rank(score, streak):
    # Example rank calculation, customize as needed
    if scores:
        max_score = max(scores.values())
        if score == max_score and max_score > 0:
            return "🍣 Master Sushi Chef (Top scorer)"
    if streak >= 30:
        return "💚🔥 Wasabi Warlord (30+ day streak)"
    elif streak >= 20:
        return "🥢 Rollmaster Ronin (20+ day streak)"
    elif streak >= 10:
        return "🍣 Nigiri Ninja (10+ day streak)"
    elif streak >= 5:
        return "🍤 Tempura Titan (5+ day streak)"
    elif streak >= 3:
        return "🔥 Streak Samurai (3+ day streak)"
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

@tree.command(name="submitriddle", description="Submit a new riddle for the daily contest")
@app_commands.describe(question="The riddle question", answer="The answer to the riddle")
async def submitriddle(interaction: discord.Interaction, question: str, answer: str):
    global current_riddle, current_answer_revealed, correct_users, guess_attempts, deducted_for_user

    question = question.strip()
    answer = answer.strip().lower()

    if not question or not answer:
        await interaction.response.send_message("❌ Question and answer cannot be empty.", ephemeral=True)
        return

    # Check for duplicate question (case-insensitive, ignoring extra spaces)
    normalized_question = " ".join(question.lower().split())
    for q in submitted_questions:
        existing_question = q.get("question", "")
        normalized_existing = " ".join(existing_question.lower().split())
        if normalized_question == normalized_existing:
            await interaction.response.send_message(
                "❌ This riddle has already been submitted. Please try a different one.",
                ephemeral=True
            )
            return

    new_id = get_next_id()
    new_riddle = {
        "id": new_id,
        "question": question,
        "answer": answer,
        "submitter_id": str(interaction.user.id),
    }
    submitted_questions.append(new_riddle)
    save_all_riddles()

    current_riddle = new_riddle
    current_answer_revealed = False
    correct_users = set()
    guess_attempts = {}
    deducted_for_user = set()

    embed = discord.Embed(
        title=f"🧩 Riddle of the Day #{new_id}",
        description=f"**Riddle:** {question}\n\n_(Riddle submitted by {interaction.user.display_name})_",
        color=discord.Color.blurple()
    )
    await interaction.response.send_message(embed=embed)

    # Notify moderation user
    notify_user_id = os.getenv("NOTIFY_USER_ID")
    if notify_user_id:
        try:
            notify_user = await client.fetch_user(int(notify_user_id))
            if notify_user:
                await notify_user.send(
                    f"@{interaction.user.display_name} has submitted a new riddle. "
                    "Use `/listriddles` to view the riddle and `/removeriddle` if moderation is needed."
                )
        except Exception as e:
            print(f"Failed to send DM to notify user: {e}")

    # DM the submitter with confirmation and info
    dm_message = (
        "✅ Thank you for submitting your riddle! It has been added to the queue.\n\n"
        "📌 Please note that on the day your riddle is posted, you won’t be able to answer it yourself.\n"
        "🎉 Your score has already been increased by 1, and your streak will remain intact. Keep up the great work!"
    )
    try:
        await interaction.user.send(dm_message)
    except Exception:
        pass



def ensure_user_initialized(uid: str):
    # Initialize user data if missing
    if uid not in scores:
        scores[uid] = 0
    if uid not in streaks:
        streaks[uid] = 0
    if uid not in submission_dates:
        submission_dates[uid] = None


@tree.command(name="addpoints", description="Add points to a user")
@app_commands.describe(user="The user to add points to", amount="Number of points to add (positive integer)")
@app_commands.checks.has_permissions(manage_guild=True)
async def addpoints(interaction: discord.Interaction, user: discord.User, amount: int):
    if amount <= 0:
        await interaction.response.send_message("❌ Amount must be a positive integer.", ephemeral=True)
        return

    uid = str(user.id)
    ensure_user_initialized(uid)

    scores[uid] += amount
    save_all_scores()
    await interaction.response.send_message(
        f"✅ Added {amount} point(s) to {user.mention}. New score: {scores[uid]}",
        ephemeral=True
    )


@tree.command(name="addstreak", description="Add streak days to a user")
@app_commands.describe(user="The user to add streak days to", amount="Number of streak days to add (positive integer)")
@app_commands.checks.has_permissions(manage_guild=True)
async def addstreak(interaction: discord.Interaction, user: discord.User, amount: int):
    if amount <= 0:
        await interaction.response.send_message("❌ Amount must be a positive integer.", ephemeral=True)
        return

    uid = str(user.id)
    ensure_user_initialized(uid)

    streaks[uid] += amount
    save_all_scores()
    await interaction.response.send_message(
        f"✅ Added {amount} streak day(s) to {user.mention}. New streak: {streaks[uid]}",
        ephemeral=True
    )


@tree.command(name="removepoints", description="Remove points from a user")
@app_commands.describe(user="The user to remove points from", amount="Number of points to remove (positive integer)")
@app_commands.checks.has_permissions(manage_guild=True)
async def removepoints(interaction: discord.Interaction, user: discord.User, amount: int):
    if amount <= 0:
        await interaction.response.send_message("❌ Amount must be a positive integer.", ephemeral=True)
        return

    uid = str(user.id)
    ensure_user_initialized(uid)

    scores[uid] = clamp_min_zero(scores[uid] - amount)
    save_all_scores()
    await interaction.response.send_message(
        f"❌ Removed {amount} point(s) from {user.mention}. New score: {scores[uid]}",
        ephemeral=True
    )


@tree.command(name="removestreak", description="Remove streak days from a user")
@app_commands.describe(user="The user to remove streak days from", amount="Number of streak days to remove (positive integer)")
@app_commands.checks.has_permissions(manage_guild=True)
async def removestreak(interaction: discord.Interaction, user: discord.User, amount: int):
    if amount <= 0:
        await interaction.response.send_message("❌ Amount must be a positive integer.", ephemeral=True)
        return

    uid = str(user.id)
    ensure_user_initialized(uid)

    streaks[uid] = clamp_min_zero(streaks[uid] - amount)
    save_all_scores()
    await interaction.response.send_message(
        f"❌ Removed {amount} streak day(s) from {user.mention}. New streak: {streaks[uid]}",
        ephemeral=True
    )



@tree.command(name="ranks", description="View all rank tiers and how to earn them")
async def ranks(interaction: discord.Interaction):
    embed = discord.Embed(
        title="📊 Riddle Rank Tiers",
        description="Earn score and build streaks to level up your riddle mastery!",
        color=discord.Color.purple()
    )

    embed.add_field(
        name="👑 Top Rank",
        value="**🍣 Master Sushi Chef** — Awarded to the user(s) with the highest score.",
        inline=False
    )

    embed.add_field(
        name="🔥 Streak-Based Titles",
        value=(
            "• 🔥 **Streak Samurai** — 3-day streak\n"
            "• 🍤 **Tempura Titan** — 5-day streak\n"
            "• 🍣 **Nigiri Ninja** — 10-day streak\n"
            "• 🥢 **Rollmaster Ronin** — 20-day streak\n"
            "• 💚🔥 **Wasabi Warlord** — 30+ day streak"
        ),
        inline=False
    )

    embed.add_field(
        name="🎯 Score-Based Ranks",
        value=(
            "• 🍽️ **Sushi Newbie** — 0–5 points\n"
            "• 🍣 **Maki Novice** — 6–15 points\n"
            "• 🍤 **Sashimi Skilled** — 16–25 points\n"
            "• 🧠 **Brainy Botan** — 26–50 points\n"
            "• 🧪 **Sushi Einstein** — 51+ points"
        ),
        inline=False
    )

    embed.set_footer(text="Ranks update automatically based on your progress.")
    await interaction.response.send_message(embed=embed)



def get_rank(score):
    if score <= 5:
        return "🍽️ Sushi Newbie"
    elif 6 <= score <= 15:
        return "🍣 Maki Novice"
    elif 16 <= score <= 25:
        return "🍤 Sashimi Skilled"
    elif 26 <= score <= 50:
        return "🧠 Brainy Botan"
    else:
        return "🧪 Sushi Einstein"

def get_streak_rank(streak):
    if streak >= 30:
        return "💚🔥 Wasabi Warlord"
    elif streak >= 20:
        return "🥢 Rollmaster Ronin"
    elif streak >= 10:
        return "🍣 Nigiri Ninja"
    elif streak >= 5:
        return "🍤 Tempura Titan"
    elif streak >= 3:
        return "🔥 Streak Samurai"
    else:
        return None  # No title


async def create_leaderboard_embed():
    load_all_data()  # Reload latest data from disk

    # Top scores sorted descending
    top_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:10]
    max_score = top_scores[0][1] if top_scores else 0

    leaderboard_embed = discord.Embed(
        title="🏆 Riddle of the Day Leaderboard",
        color=discord.Color.purple()
    )

    description_lines = []

    for idx, (user_id, score_val) in enumerate(top_scores, start=1):
        try:
            user = await client.fetch_user(int(user_id))
            streak_val = streaks.get(user_id, 0)

            # Score line
            score_line = f"    • Score: {score_val}"
            if score_val == max_score and max_score > 0:
                score_line += " — 👑 🍣 Master Sushi Chef"

            # Rank line
            rank = get_rank(score_val)
            rank_line = f"    • Rank: {rank}"

            # Streak line
            streak_title = get_streak_rank(streak_val)
            streak_line = f"    • Streak: 🔥{streak_val}"
            if streak_title:
                streak_line += f" — {streak_title}"

            # Combine
            description_lines.append(f"#{idx} {user.display_name}:")
            description_lines.append(score_line)
            description_lines.append(rank_line)
            description_lines.append(streak_line)
            description_lines.append("")  # Blank line between entries
        except Exception:
            description_lines.append(f"#{idx} <@{user_id}> (User data unavailable)")
            description_lines.append("")

    leaderboard_embed.description = "\n".join(description_lines)
    leaderboard_embed.set_footer(text="Ranks update automatically based on your progress.")

    return leaderboard_embed

@tree.command(name="removeriddle", description="Remove a riddle by its number (ID)")
@app_commands.describe(riddle_id="The ID number of the riddle to remove")
@app_commands.checks.has_permissions(manage_guild=True)
async def removeriddle(interaction: discord.Interaction, riddle_id: int):
    global submitted_questions, used_question_ids

    # Convert ID to string to match stored riddles
    riddle_id_str = str(riddle_id)

    # Find riddle index by ID
    index_to_remove = next((i for i, r in enumerate(submitted_questions) if str(r.get("id")) == riddle_id_str), None)

    if index_to_remove is None:
        await interaction.response.send_message(f"❌ No riddle found with ID #{riddle_id}.", ephemeral=True)
        return

    # Remove riddle
    removed_riddle = submitted_questions.pop(index_to_remove)
    used_question_ids.discard(riddle_id_str)

    # Save changes
    save_all_riddles()

    await interaction.response.send_message(f"✅ Removed riddle #{riddle_id}: {removed_riddle.get('question')}", ephemeral=True)

ITEMS_PER_PAGE = 10

class ListRiddlesView(View):
    def __init__(self, riddles, author_id, bot):
        super().__init__(timeout=180)
        self.riddles = riddles
        self.author_id = author_id
        self.current_page = 0
        self.total_pages = max(1, (len(riddles) - 1) // ITEMS_PER_PAGE + 1)
        self.bot = bot  # save bot/client to fetch users
        self.update_buttons()

    def update_buttons(self):
        self.prev_button.disabled = self.current_page == 0
        self.next_button.disabled = self.current_page >= self.total_pages - 1

    async def get_page_embed(self):
        start = self.current_page * ITEMS_PER_PAGE
        end = start + ITEMS_PER_PAGE
        page_riddles = self.riddles[start:end]

        embed = Embed(
            title=f"📜 Submitted Riddles (Page {self.current_page + 1}/{self.total_pages})",
            color=discord.Color.blurple()
        )

        if not page_riddles:
            embed.description = "No riddles available."
            return embed

        desc_lines = []
        for riddle in page_riddles:
            try:
                user = await self.bot.fetch_user(int(riddle['submitter_id']))
                display_name = user.display_name if hasattr(user, 'display_name') else user.name
            except Exception:
                display_name = "Unknown User"
            desc_lines.append(f"#{riddle['id']}: {riddle['question']}\n_(submitted by {display_name})_")

        embed.description = "\n\n".join(desc_lines)
        embed.set_footer(text="Use the buttons below to navigate pages.")
        return embed

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary)
    async def prev_button(self, interaction: Interaction, button: Button):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Only the command invoker can use these buttons.", ephemeral=True)
            return
        if self.current_page > 0:
            self.current_page -= 1
            self.update_buttons()
            embed = await self.get_page_embed()
            await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: Interaction, button: Button):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Only the command invoker can use these buttons.", ephemeral=True)
            return
        if self.current_page < self.total_pages - 1:
            self.current_page += 1
            self.update_buttons()
            embed = await self.get_page_embed()
            await interaction.response.edit_message(embed=embed, view=self)


@tree.command(name="listriddles", description="List all submitted riddles with pagination")
async def listriddles(interaction: discord.Interaction):
    if not submitted_questions:
        await interaction.response.send_message("No riddles have been submitted yet.", ephemeral=True)
        return

    view = ListRiddlesView(submitted_questions, interaction.user.id, interaction.client)
    embed = await view.get_page_embed()
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)



@tree.command(name="leaderboard", description="Show the top scores and streaks")
async def leaderboard(interaction: discord.Interaction):
    load_all_data()  # Reload latest data from disk before building embed
    embed = await create_leaderboard_embed()
    await interaction.response.send_message(embed=embed)


@tree.command(name="purge", description="Delete all messages in this channel")
@app_commands.checks.has_permissions(administrator=True)
async def purge(interaction: discord.Interaction):
    channel = interaction.channel
    if not isinstance(channel, discord.TextChannel):
        await interaction.response.send_message("❌ This command can only be used in text channels.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    def is_not_pinned(m):
        return not m.pinned

    deleted = await channel.purge(limit=None, check=is_not_pinned)
    await interaction.followup.send(f"🧹 Purged {len(deleted)} messages.", ephemeral=True)

def setup_test_sequence_commands(tree, client):
    @tree.command(name="run_test_sequence", description="Run a full test riddle workflow")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def run_test_sequence(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        channel_id = int(os.getenv("DISCORD_CHANNEL_ID") or 0)
        channel = client.get_channel(channel_id)
        if not channel:
            await interaction.followup.send("❌ Test failed: Channel not found.", ephemeral=True)
            return

        # Announcement embed for next riddle
        announcement_embed = discord.Embed(
            title="ℹ️ Upcoming Riddle Alert!",
            description="The next riddle will be submitted soon. Get ready!\n\n💡 Submit your own riddle using the `/submitriddle` command!",
            color=discord.Color.blurple()
        )
        await channel.send(embed=announcement_embed)

        global current_riddle, current_answer_revealed, correct_users, guess_attempts, deducted_for_user

        current_riddle = {
            "id": "9999",
            "question": "What has keys but can't open locks?",
            "answer": "piano",
            "submitter_id": None,
        }
        current_answer_revealed = False
        correct_users = set()
        guess_attempts = {}
        deducted_for_user = set()

        riddle_embed = discord.Embed(
            title=f"🧩 Riddle of the Day #{current_riddle['id']}",
            description=f"**Riddle:** {current_riddle['question']}\n\n_(Riddle submitted by **Riddle of the Day Bot**)_\n\n",
            color=discord.Color.blurple()
        )
        await channel.send(embed=riddle_embed)

        await interaction.followup.send("✅ Test riddle posted. Waiting 30 seconds before revealing answer...", ephemeral=True)

        await asyncio.sleep(30)

        answer_embed = discord.Embed(
            title=f"🔔 Answer to Riddle #{current_riddle['id']}",
            description=f"**Answer:** {current_riddle['answer']}\n\n💡 Use `/submitriddle` to submit your own riddle!",
            color=discord.Color.green()
        )
        await channel.send(embed=answer_embed)

        if correct_users:
            max_score = max(scores.values()) if scores else 0
        
            congrats_embed = discord.Embed(
                title="🎊 Congratulations to the following users who solved today's riddle! 🎊",
                color=discord.Color.gold()
            )
        
            description_lines = []
            for idx, user_id_str in enumerate(correct_users, start=1):
                try:
                    user = await client.fetch_user(int(user_id_str))
                    score_val = scores.get(user_id_str, 0)
                    streak_val = streaks.get(user_id_str, 0)
        
                    # Score line (include 👑 only if top scorer)
                    score_line = f"{score_val}"
                    if score_val == max_score and max_score > 0:
                        score_line += " - 👑 🍣 Master Sushi Chef"
        
                    # Rank line
                    rank = get_rank(score_val)
        
                    # Streak rank
                    streak_rank = get_streak_rank(streak_val)
        
                    # Build lines
                    description_lines.append(f"#{idx} {user.display_name}:")
                    description_lines.append(f"    • Score: {score_line}")
                    description_lines.append(f"    • Rank: {rank}")
        
                    streak_text = f"🔥{streak_val}"
                    if streak_rank:
                        streak_text += f" - {streak_rank}"
                    description_lines.append(f"    • Streak: {streak_text}")
                    description_lines.append("")
        
                except Exception:
                    # Fallback if user fetch fails: show mention with stats
                    score_val = scores.get(user_id_str, 0)
                    rank = get_rank(score_val)
                    streak_val = streaks.get(user_id_str, 0)
                    streak_rank = get_streak_rank(streak_val)
                    streak_text = f"🔥{streak_val}"
                    if streak_rank:
                        streak_text += f" - {streak_rank}"
        
                    description_lines.append(f"#{idx} <@{user_id_str}>")
                    description_lines.append(f"    • Score: {score_val}")
                    description_lines.append(f"    • Rank: {rank}")
                    description_lines.append(f"    • Streak: {streak_text}")
                    description_lines.append("")
        
            congrats_embed.description = "\n".join(description_lines)
            await channel.send(embed=congrats_embed)
        else:
            await channel.send("😢 No one guessed the riddle correctly today.")



        
        current_answer_revealed = True
        correct_users.clear()
        guess_attempts.clear()
        deducted_for_user.clear()
        current_riddle = None
        
        await channel.send("✅ Test sequence completed. You can run `/run_test_sequence` again to test.")



setup_test_sequence_commands(tree, client)

@client.event
async def on_message(message):
    if message.author.bot:
        return

    ch_id = int(os.getenv("DISCORD_CHANNEL_ID") or 0)
    if message.channel.id != ch_id:
        return

    global correct_users, guess_attempts, deducted_for_user, current_riddle, current_answer_revealed

    user_id = str(message.author.id)
    content = message.content.strip()

    # If no riddle is active or it's already revealed, ignore all messages (they're not guesses)
    if not current_riddle or current_answer_revealed:
        return

    # Only block submitter IF the active riddle is theirs AND they are trying to guess it
    if current_riddle.get("submitter_id") == user_id:
        user_words = clean_and_filter(content)
        answer_words = clean_and_filter(current_riddle["answer"])

        # Only block if it looks like an answer attempt
        if any(word in answer_words for word in user_words):
            try:
                await message.delete()
            except:
                pass
            await message.channel.send(
                "⛔ You submitted this riddle and cannot answer it.",
                delete_after=10
            )
            return
        else:
            return 

    # If they've already answered correctly, ignore further guesses
    if user_id in correct_users:
        try: await message.delete()
        except: pass
        await message.channel.send(
            f"✅ You already answered correctly, {message.author.mention}. No more guesses counted.",
            delete_after=5
        )
        return

    # Track how many guesses they’ve made
    attempts = guess_attempts.get(user_id, 0)
    if attempts >= 5:
        try: await message.delete()
        except: pass
        await message.channel.send(
            f"❌ You are out of guesses for this riddle, {message.author.mention}.",
            delete_after=5
        )
        return

    # Record this guess
    guess_attempts[user_id] = attempts + 1

    # Check answer words
    user_words = clean_and_filter(content)
    answer_words = clean_and_filter(current_riddle["answer"])
    
    if any(word in user_words for word in answer_words):
        # Correct
        correct_users.add(user_id)
        scores[user_id] = scores.get(user_id, 0) + 1
        streaks[user_id] = streaks.get(user_id, 0) + 1
        save_all_scores()
        try:
            await message.delete()
        except:
            pass
        correct_guess_embed = discord.Embed(
            title="You guess correctly!",
            description=f"🥳 Correct, {message.author.mention}! Your total score: {scores[user_id]}",
            color=discord.Color.green()
        )
        await message.channel.send(embed=correct_guess_embed)
    else:
        # Wrong
        remaining = 5 - guess_attempts.get(user_id, 0)
        if remaining == 0 and user_id not in deducted_for_user:
            # Penalty on 5th wrong guess
            scores[user_id] = max(0, scores.get(user_id, 0) - 1)
            streaks[user_id] = 0
            deducted_for_user.add(user_id)
            save_all_scores()
            await message.channel.send(
                f"❌ Incorrect, {message.author.mention}. You've used all guesses and lost 1 point.",
                delete_after=8
            )
        elif remaining > 0:
            await message.channel.send(
                f"❌ Incorrect, {message.author.mention}. {remaining} guess(es) left.",
                delete_after=6
            )
        try:
            await message.delete()
        except:
            pass


    # Send countdown until reveal
    now_utc = datetime.now(timezone.utc)
    reveal_dt = datetime.combine(now_utc.date(), time(23, 0), tzinfo=timezone.utc)
    if now_utc >= reveal_dt:
        reveal_dt += timedelta(days=1)
    delta = reveal_dt - now_utc
    hours, remainder = divmod(int(delta.total_seconds()), 3600)
    minutes = remainder // 60
    countdown_msg = (
        f"⏳ Answer will be revealed in {hours} hour{'s' if hours != 1 else ''} "
        f"{minutes} minute{'s' if minutes != 1 else ''}."
    )
    await message.channel.send(countdown_msg, delete_after=12)

@client.event
async def on_ready():
    print(f"Bot logged in as {client.user} (ID: {client.user.id})")
    try:
        synced = await tree.sync()
        print(f"Synced {len(synced)} commands.")
    except Exception as e:
        print(f"Failed to sync commands: {e}")


@client.event
async def on_command_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.errors.MissingPermissions):
        await interaction.response.send_message("❌ You don't have permission to use this command.", ephemeral=True)
    elif isinstance(error, app_commands.errors.CommandOnCooldown):
        await interaction.response.send_message("⏳ This command is on cooldown, please wait.", ephemeral=True)
    else:
        await interaction.response.send_message(f"⚠️ An error occurred: {error}", ephemeral=True)
        print(f"Error in command {interaction.command}: {error}")
        traceback.print_exc()

@tasks.loop(time=time(hour=11, minute=50, second=0))  # 10 minutes before daily post
async def riddle_announcement():
    channel_id = int(os.getenv("DISCORD_CHANNEL_ID") or 0)
    channel = client.get_channel(channel_id)
    if not channel:
        print("Riddle announcement skipped: Channel not found.")
        return

    embed = discord.Embed(
        title="ℹ️ Upcoming Riddle Alert!",
        description="The next riddle will be submitted soon. Get ready!\n\n💡 Submit your own riddle using the `/submitriddle` command!",
        color=discord.Color.blurple()
    )

    await channel.send(embed=embed)


@tasks.loop(time=time(hour=12, minute=0, second=0))  # Posts every day at noon UTC
async def daily_riddle_post():
    global current_riddle, current_answer_revealed, correct_users, guess_attempts, deducted_for_user

    if current_riddle is not None:
        # There is already an active riddle; skip
        return

    channel_id = int(os.getenv("DISCORD_CHANNEL_ID") or 0)
    channel = client.get_channel(channel_id)
    if not channel:
        print("Daily riddle post skipped: Channel not found.")
        return

    if not submitted_questions:
        print("No riddles available to post.")
        return

    riddle = random.choice(submitted_questions)
    current_riddle = riddle
    current_answer_revealed = False
    correct_users = set()
    guess_attempts = {}
    deducted_for_user = set()

    submitter_name = "Anonymous"
    if riddle.get("submitter_id"):
        user = client.get_user(int(riddle["submitter_id"]))
        if user:
            submitter_name = user.display_name

    embed = discord.Embed(
        title=f"🧩 Riddle of the Day #{riddle['id']}",
        description=f"**Riddle:** {riddle['question']}\n\n_(Riddle submitted by {submitter_name})_",
        color=discord.Color.blurple()
    )
    await channel.send(embed=embed)

    print(f"Posted daily riddle #{riddle['id']}")

if __name__ == "__main__":
    TOKEN = os.getenv("DISCORD_BOT_TOKEN")
    if not TOKEN:
        print("ERROR: DISCORD_BOT_TOKEN environment variable is not set.")
        exit(1)

    client.run(TOKEN)
