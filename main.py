import discord
from discord.ext import tasks
import asyncio
import json
import os
from datetime import datetime, time, timezone, timedelta
import random
from discord import app_commands

# --- Timezone Setup ---
EST = timezone(timedelta(hours=-5))  # Fixed EST offset UTC-5 (no DST)

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
    base = f"@everyone {qdict['question']} ***(Answer will be revealed in 1 minute)***"
    remaining = count_unused_questions()
    if remaining < 5:
        base += "\n\n⚠️ Less than 5 new riddles remain - submit a new riddle with /submitriddle to add it to the queue!"
    return base

# --- Load data ---
submitted_questions = load_json(QUESTIONS_FILE)
scores = load_json(SCORES_FILE)
streaks = load_json(STREAKS_FILE)

# --- Debug prints on startup ---
print("Starting bot...")
token = os.getenv("DISCORD_BOT_TOKEN")
channel_id = os.getenv("DISCORD_CHANNEL_ID")
guild_id = os.getenv("DISCORD_GUILD_ID")
print(f"Token set? {'Yes' if token else 'No'}")
print(f"Channel ID: {channel_id}")
print(f"Guild ID: {guild_id}")

if not token:
    print("ERROR: DISCORD_BOT_TOKEN environment variable is NOT set!")

# --- Events ---

@client.event
async def on_ready():
    global current_riddle, current_answer_revealed, correct_users, guess_attempts, deducted_for_user

    print(f"Logged in as {client.user} (ID: {client.user.id})")
    print("------")

    if guild_id:
        guild_obj = discord.Object(id=int(guild_id))
        await tree.sync(guild=guild_obj)
        print(f"Synced commands to guild {guild_id}")
    else:
        await tree.sync()
        print("Synced global commands")

    ch_id = int(channel_id or 0)
    if ch_id == 0:
        print("DISCORD_CHANNEL_ID not set or invalid.")
        return

    channel = client.get_channel(ch_id)
    if not channel:
        print("Channel not found.")
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

    post_riddle.start()
    reveal_answer.start()

# ... OMITTED unchanged functions for brevity ...

@tree.command(name="submitriddle", description="Submit a new riddle step-by-step")
async def submitriddle(interaction: discord.Interaction):
    await interaction.response.send_message("✍️ Check your DMs to submit a riddle!", ephemeral=True)

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

    except asyncio.TimeoutError:
        await interaction.user.send("⏰ Timed out. Try /submitriddle again.")

# --- Run bot ---
if token:
    client.run(token)
else:
    print("Bot token not found. Please set the DISCORD_BOT_TOKEN environment variable.")
