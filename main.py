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
    base = f"@everyone {qdict['question']} ***(Answer will be revealed at 23:00 UTC)***"
    remaining = count_unused_questions()
    if remaining < 5:
        base += "\n\n⚠️ Less than 5 new riddles remain - submit a new riddle with /submitriddle to add it to the queue!"
    return base

# --- Load data ---
submitted_questions = load_json(QUESTIONS_FILE)
scores = load_json(SCORES_FILE)
streaks = load_json(STREAKS_FILE)

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
            lines.append(f"{idx}. {q['question']}")
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
                    await modal_interaction.response.send_message(f"⚠️ Invalid question number `{num}`.", ephemeral=True)
                    return
                removed = submitted_questions.pop(num - 1)
                save_json(QUESTIONS_FILE, submitted_questions)
                await modal_interaction.response.send_message(f"✅ Removed riddle #{num}: \"{removed['question']}\"", ephemeral=True)
            except:
                await modal_interaction.response.send_message("⚠️ Invalid input.", ephemeral=True)
    await interaction.response.send_modal(RemoveQuestionModal())

@tree.command(name="submitriddle", description="Submit a new riddle step-by-step")
async def submitriddle(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    def check(m): return m.author.id == interaction.user.id and isinstance(m.channel, discord.DMChannel)

    try:
        dm = await interaction.user.create_dm()
        await dm.send("✍️ Please enter your riddle question:")

        q = (await client.wait_for('message', timeout=120.0, check=check)).content.strip()
        q_normalized = q.lower().replace(" ", "")
        for existing in submitted_questions:
            existing_q = existing["question"].strip().lower().replace(" ", "")
            if existing_q == q_normalized:
                await dm.send("⚠️ This riddle has already been submitted. Please try a different one.")
                return

        await dm.send("💡 Now enter the answer:")
        a = (await client.wait_for('message', timeout=120.0, check=check)).content.strip()

        if not q or not a:
            await dm.send("⚠️ Both question and answer are required.")
            return

        uid = str(interaction.user.id)
        new_id = f"{int(datetime.utcnow().timestamp()*1000)}_{uid}"
        submitted_questions.append({
            "id": new_id,
            "question": q,
            "answer": a,
            "submitter_id": uid
        })
        save_json(QUESTIONS_FILE, submitted_questions)

        await dm.send("✅ Your riddle has been submitted and added to the queue!\n⚠️ You will **not** be able to answer your own riddle when it is posted.")
        await interaction.followup.send("✅ Riddle submitted via DM!", ephemeral=True)

    except asyncio.TimeoutError:
        await interaction.followup.send("⏰ Timed out. Try /submitriddle again.", ephemeral=True)
    except discord.Forbidden:
        await interaction.followup.send("❌ I couldn’t DM you. Please enable DMs from server members and try again.", ephemeral=True)

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

@tree.command(name="score", description="View your score and rank")
async def score(interaction: discord.Interaction):
    uid = str(interaction.user.id)
    sv = scores.get(uid, 0)
    st = streaks.get(uid, 0)
    await interaction.response.send_message(
        f"📊 {interaction.user.display_name}'s score: **{sv}**, 🔥 Streak: {st}\n🏅 {get_rank(sv, st)}",
        ephemeral=True
    )

@tree.command(name="leaderboard", description="Show the top solvers")
async def leaderboard(interaction: discord.Interaction):
    uid = str(interaction.user.id)
    leaderboard_pages[uid] = 0
    await show_leaderboard(interaction.channel, uid)
    await interaction.response.send_message("📋 Showing leaderboard...", ephemeral=True)

async def show_leaderboard(channel, user_id):
    sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    total_pages = max((len(sorted_scores) - 1) // 10 + 1, 1)
    page = leaderboard_pages.get(user_id, 0)
    page = min(page, total_pages - 1)
    embed = discord.Embed(title=f"🏆 Riddle Leaderboard ({page+1}/{total_pages})", color=discord.Color.gold())
    start = page * 10
    for i, (uid, sv) in enumerate(sorted_scores[start:start+10], start=start+1):
        try:
            user = await client.fetch_user(int(uid))
            st = streaks.get(uid, 0)
            embed.add_field(name=f"{i}. {user.display_name}", value=f"Score: {sv} | Streak: {st}\nRank: {get_rank(sv, st)}", inline=False)
        except:
            embed.add_field(name=f"{i}. Unknown", value=f"Score: {sv}", inline=False)
    await channel.send(embed=embed)
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

    # Block submitter from answering their own riddle
    if current_riddle.get("submitter_id") == user_id:
        try: await message.delete()
        except: pass
        await message.channel.send(f"⛔ You submitted this riddle and cannot answer it, {message.author.mention}.", delete_after=10)
        return

    if user_id in correct_users:
        try: await message.delete()
        except: pass
        await message.channel.send(f"✅ You already answered correctly, {message.author.mention}. No more guesses counted.", delete_after=5)
        return

    attempts = guess_attempts.get(user_id, 0)
    if attempts >= 5:
        try: await message.delete()
        except: pass
        await message.channel.send(f"❌ You are out of guesses for this riddle, {message.author.mention}.", delete_after=5)
        return

    guess_attempts[user_id] = attempts + 1
    guess = content.lower()
    correct_answer = current_riddle["answer"].lower()

    # Accept basic singular/plural matching
    if guess == correct_answer or guess.rstrip("s") == correct_answer.rstrip("s"):
        correct_users.add(user_id)
        scores[user_id] = scores.get(user_id, 0) + 1
        streaks[user_id] = streaks.get(user_id, 0) + 1
        save_all_scores()
        try: await message.delete()
        except: pass
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
        try: await message.delete()
        except: pass

    # Countdown to answer reveal
    now_utc = datetime.now(timezone.utc)
    reveal_dt = datetime.combine(now_utc.date(), time(23, 0), tzinfo=timezone.utc)
    if now_utc >= reveal_dt:
        reveal_dt += timedelta(days=1)
    delta = reveal_dt - now_utc
    hours, remainder = divmod(int(delta.total_seconds()), 3600)
    minutes = remainder // 60
    countdown_msg = f"⏳ Answer will be revealed in {hours} hour{'s' if hours != 1 else ''} {minutes} minute{'s' if minutes != 1 else ''}."
    await message.channel.send(countdown_msg, delete_after=12)

# --- Scheduled tasks ---

@tasks.loop(time=time(6, 55, tzinfo=timezone.utc))
async def daily_purge():
    ch_id = int(os.getenv("DISCORD_CHANNEL_ID") or 0)
    channel = client.get_channel(ch_id)
    if not channel:
        print("Channel not found for daily purge.")
        return
    try:
        async for msg in channel.history(limit=100):
            await msg.delete()
        print("Daily purge completed.")
    except Exception as e:
        print(f"Error during purge: {e}")

@tasks.loop(time=time(6, 57, tzinfo=timezone.utc))
async def notify_upcoming_riddle():
    ch_id = int(os.getenv("DISCORD_CHANNEL_ID") or 0)
    channel = client.get_channel(ch_id)
    if channel:
        await channel.send("⏳ The next riddle will be posted soon!")

@tasks.loop(time=time(7, 0, tzinfo=timezone.utc))
async def post_riddle():
    global current_riddle, current_answer_revealed, correct_users, guess_attempts, deducted_for_user
    ch_id = int(os.getenv("DISCORD_CHANNEL_ID") or 0)
    channel = client.get_channel(ch_id)
    if not channel:
        print("Channel not found for posting riddles.")
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

@tasks.loop(time=time(23, 0, tzinfo=timezone.utc))
async def reveal_answer():
    global current_answer_revealed
    ch_id = int(os.getenv("DISCORD_CHANNEL_ID") or 0)
    channel = client.get_channel(ch_id)
    if not channel or not current_riddle:
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

# --- Ready and Main ---

@client.event
async def on_ready():
    print(f"Logged in as {client.user} (ID: {client.user.id})")
    guild_id = os.getenv("DISCORD_GUILD_ID")
    if guild_id:
        await tree.sync(guild=discord.Object(id=int(guild_id)))
        print(f"Commands synced to guild {guild_id}")
    else:
        await tree.sync()
        print("Global commands synced")

    ch_id = int(os.getenv("DISCORD_CHANNEL_ID") or 0)
    if ch_id == 0:
        print("DISCORD_CHANNEL_ID not set or invalid.")
        return

    global current_riddle, current_answer_revealed, correct_users, guess_attempts, deducted_for_user
    current_riddle = pick_next_riddle()
    current_answer_revealed = False
    correct_users.clear()
    guess_attempts.clear()
    deducted_for_user.clear()

    daily_purge.start()
    notify_upcoming_riddle.start()
    post_riddle.start()
    reveal_answer.start()

if __name__ == "__main__":
    token = os.getenv("DISCORD_BOT_TOKEN")
    if token:
        client.run(token)
    else:
        print("Bot token not found. Please set the DISCORD_BOT_TOKEN environment variable.")
