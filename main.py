import discord
from discord.ext import tasks, commands
import asyncio
import json
import random
from datetime import datetime, time, timezone, timedelta

intents = discord.Intents.default()
intents.message_content = True
client = commands.Bot(command_prefix="!", intents=intents)

CHANNEL_ID = 123456789012345678  # Replace with your Discord channel ID

# File paths
SUBMITTED_QUESTIONS_FILE = "submitted_questions.json"
SCORES_FILE = "scores.json"
STREAKS_FILE = "streaks.json"

# Data holders
scores = {}
streaks = {}
submitted_questions = []
current_riddle = None
correct_users = set()
leaderboard_pages = {}

# --- Helper functions for JSON persistence ---
def load_json(path, default):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return default

def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

# Load data on startup
scores = load_json(SCORES_FILE, {})
streaks = load_json(STREAKS_FILE, {})
submitted_questions = load_json(SUBMITTED_QUESTIONS_FILE, [])

# --- Ranking system ---
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

# --- Utility to format remaining time until a UTC hour ---
def format_remaining_time(target_hour_utc):
    now = datetime.now(timezone.utc)
    target_time = now.replace(hour=target_hour_utc, minute=0, second=0, microsecond=0)
    if now >= target_time:
        target_time += timedelta(days=1)
    diff = target_time - now
    hours, remainder = divmod(int(diff.total_seconds()), 3600)
    minutes = remainder // 60
    return f"{hours}h {minutes}m"

# --- Can a user answer the current riddle? (no self-answering) ---
def can_answer(user_id):
    if not current_riddle:
        return False
    submitter_id = current_riddle.get("submitter_id")
    return submitter_id is None or str(user_id) != str(submitter_id)

# --- Posting a daily riddle ---
async def post_riddle():
    global current_riddle, correct_users

    unused = [r for r in submitted_questions if not r.get("used", False)]
    if not unused:
        # Reset usage if all riddles used
        for r in submitted_questions:
            r["used"] = False
        unused = submitted_questions

    current_riddle = random.choice(unused)
    current_riddle["used"] = True
    correct_users = set()
    save_json(SUBMITTED_QUESTIONS_FILE, submitted_questions)

    riddle_text = current_riddle["question"]
    submitter_text = current_riddle.get("submitter_text") or "Riddle of the Day bot"

    # Append note if less than 5 riddles remain
    unused_count = len([r for r in submitted_questions if not r.get("used", False)])
    if unused_count < 5:
        riddle_text += "\n\n*(Less than 5 new riddles remain - submit a new riddle with !submit_riddle to add it to the queue)*"

    countdown = format_remaining_time(23)  # 23:00 UTC is answer reveal time
    mention_everyone = "@everyone "
    answer_note = f" ***(Answer will be revealed in approx. {countdown})***"

    channel = client.get_channel(CHANNEL_ID)
    await channel.send(f"{mention_everyone}{riddle_text}{answer_note}")

# --- Reveal the answer and announce winners ---
@tasks.loop(time=time(23, 0, tzinfo=timezone.utc))
async def reveal_answer():
    global current_riddle, correct_users

    if current_riddle is None:
        return

    channel = client.get_channel(CHANNEL_ID)
    correct_answer = current_riddle.get("answer", "Unknown")
    submitter_text = current_riddle.get("submitter_text") or "Riddle of the Day bot"

    if correct_users:
        lines = [f"✅ The correct answer was **{correct_answer}**!\n"]
        lines.append(f"Submitted by: {submitter_text}\n")
        lines.append("The following users got it correct:")

        for uid in correct_users:
            uid_str = str(uid)
            scores[uid_str] = scores.get(uid_str, 0) + 1
            streaks[uid_str] = streaks.get(uid_str, 0) + 1
            user = await client.fetch_user(uid)
            rank = get_rank(scores[uid_str], streaks[uid_str])
            lines.append(f"• {user.mention} (**{scores[uid_str]}** total, 🔥 {streaks[uid_str]} streak) 🏅 {rank}")

        lines.append("\n📅 Stay tuned for tomorrow’s riddle!")
        await channel.send("\n".join(lines))
    else:
        await channel.send(f"❌ The correct answer was **{correct_answer}**. No one got it right today.\n\nSubmitted by: {submitter_text}")

    save_json(SCORES_FILE, scores)
    save_json(STREAKS_FILE, streaks)

    current_riddle = None
    correct_users = set()

# --- Post riddle daily at 6:00 UTC ---
@tasks.loop(time=time(6, 0, tzinfo=timezone.utc))
async def post_daily_riddle():
    await post_riddle()

@client.event
async def on_ready():
    print(f"Logged in as {client.user}")
    if not post_daily_riddle.is_running():
        post_daily_riddle.start()
    if not reveal_answer.is_running():
        reveal_answer.start()

# --- Command: Submit a new riddle ---
@client.command(name="submit_riddle")
async def submit_riddle(ctx, *, arg=None):
    if arg is None:
        await ctx.send("❌ Usage: !submit_riddle question | answer")
        return
    parts = [p.strip() for p in arg.split("|")]
    if len(parts) < 2:
        await ctx.send("❌ Please provide both question and answer separated by `|`.")
        return
    question, answer = parts[0], parts[1]
    submitter_id = str(ctx.author.id)

    if not question.startswith("@everyone"):
        question = "@everyone " + question
    if "***(" not in question:
        question += " ***(Answer will be revealed later this evening)***"

    new_riddle = {
        "question": question,
        "answer": answer,
        "submitter_id": submitter_id,
        "submitter_text": ctx.author.display_name,
        "used": False,
    }
    submitted_questions.append(new_riddle)
    save_json(SUBMITTED_QUESTIONS_FILE, submitted_questions)
    await ctx.send(f"✅ Thanks {ctx.author.mention}, your riddle has been added! You won't be able to answer this one yourself.")

# --- Command: Show user's score and rank ---
@client.command(name="score")
async def score_command(ctx):
    user_id = str(ctx.author.id)
    score = scores.get(user_id, 0)
    streak = streaks.get(user_id, 0)
    rank = get_rank(score, streak)
    await ctx.send(f"📊 {ctx.author.display_name}'s score: **{score}**, 🔥 Streak: {streak}\n🏅 Rank: {rank}")

# --- Leaderboard with button scrolling ---
class LeaderboardView(discord.ui.View):
    def __init__(self, user_id):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.page = leaderboard_pages.get(user_id, 0)

    async def update_message(self, interaction):
        embed = await generate_leaderboard_embed(self.user_id, self.page)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(emoji="⬅️", style=discord.ButtonStyle.primary)
    async def previous(self, button, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ This is not your leaderboard view.", ephemeral=True)
            return
        if self.page > 0:
            self.page -= 1
            leaderboard_pages[self.user_id] = self.page
            await self.update_message(interaction)

    @discord.ui.button(emoji="➡️", style=discord.ButtonStyle.primary)
    async def next(self, button, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ This is not your leaderboard view.", ephemeral=True)
            return
        max_page = max((len(scores) - 1) // 10, 0)
        if self.page < max_page:
            self.page += 1
            leaderboard_pages[self.user_id] = self.page
            await self.update_message(interaction)

async def generate_leaderboard_embed(user_id, page):
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
        try:
            user = await client.fetch_user(int(uid))
            streak = streaks.get(uid, 0)
            rank = get_rank(score, streak)
            if uid in top_scorers:
                rank += " 👑 Chopstick Champ (Top Solver)"
            embed.add_field(
                name=f"{i}. {user.display_name}",
                value=f"Correct: **{score}**, 🔥 Streak: {streak}\n🏅 Rank: {rank}",
                inline=False
            )
        except:
            # In case user cannot be fetched (deleted, etc)
            embed.add_field(
                name=f"{i}. Unknown User",
                value=f"Correct: **{score}**, 🔥 Streak: {streaks.get(uid, 0)}\n🏅 Rank: Unknown",
                inline=False
            )

    embed.set_footer(text="Use arrows to navigate pages")
    return embed

@client.command(name="leaderboard")
async def leaderboard_command(ctx):
    user_id = str(ctx.author.id)
    leaderboard_pages[user_id] = 0
    embed = await generate_leaderboard_embed(user_id, 0)
    view = LeaderboardView(user_id)
    await ctx.send(embed=embed, view=view)

# --- On message to detect correct answers ---
@client.event
async def on_message(message):
    await client.process_commands(message)

    if message.author == client.user:
        return

    if not current_riddle:
        return

    if not can_answer(message.author.id):
        # User submitted this riddle, ignore their answers
        return

    if message.content.startswith("!"):
        return

    guess = message.content.strip().lower()
    correct_answer = current_riddle.get("answer", "").lower()

    if guess == correct_answer:
        if message.author.id not in correct_users:
            correct_users.add(message.author.id)
            await message.channel.send(f"✅ {message.author.mention}, you got it right! 🏅")

# --- Run the bot ---
client.run("YOUR_BOT_TOKEN")
