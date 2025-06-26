import discord
import datetime
import json
import logging
import os
import random
from discord.ext import tasks
from discord import app_commands
from discord.ui import View, button
from discord import ButtonStyle
from threading import Thread
from flask import Flask

logging.basicConfig(level=logging.INFO)
print("💡 Riddle bot is running")

# CONFIG
TOKEN = os.getenv('DISCORD_BOT_TOKEN')
if not TOKEN:
    raise RuntimeError("❌ DISCORD_BOT_TOKEN environment variable not set!")

CHANNEL_ID = 1387520693859782867  # Your riddle channel ID

# Flask keep alive for Railway or Replit
app = Flask('')

@app.route('/')
def home():
    return "I am alive!"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()

# Files
SCORES_FILE = "scores.json"
STREAKS_FILE = "streaks.json"
SUBMITTED_FILE = "submitted_questions.json"
USED_RIDDLES_FILE = "used_riddles.json"
SHUFFLED_ORDER_FILE = "shuffled_order.json"

def load_json(fname, default):
    if os.path.exists(fname):
        with open(fname, "r") as f:
            return json.load(f)
    return default

def save_json(fname, data):
    with open(fname, "w") as f:
        json.dump(data, f, indent=2)

scores = load_json(SCORES_FILE, {})
streaks = load_json(STREAKS_FILE, {})

all_riddles = load_json(SUBMITTED_FILE, [])

if os.path.exists(SHUFFLED_ORDER_FILE):
    shuffled_order = load_json(SHUFFLED_ORDER_FILE, list(range(len(all_riddles))))
else:
    shuffled_order = list(range(len(all_riddles)))
    random.shuffle(shuffled_order)
    save_json(SHUFFLED_ORDER_FILE, shuffled_order)

used_indices = set(load_json(USED_RIDDLES_FILE, []))

intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

current_riddle = None
correct_users = set()
leaderboard_pages = {}

def normalize_answer(ans: str) -> str:
    ans = ans.lower().strip()
    if ans.endswith("es"):
        ans = ans[:-2]
    elif ans.endswith("s"):
        ans = ans[:-1]
    return ans

def get_next_riddle():
    global used_indices, shuffled_order, all_riddles

    if len(all_riddles) != len(shuffled_order):
        shuffled_order = list(range(len(all_riddles)))
        random.shuffle(shuffled_order)
        save_json(SHUFFLED_ORDER_FILE, shuffled_order)
        used_indices.clear()
        save_json(USED_RIDDLES_FILE, [])

    for idx in shuffled_order:
        if idx not in used_indices:
            used_indices.add(idx)
            save_json(USED_RIDDLES_FILE, list(used_indices))
            return all_riddles[idx]

    # Reset once all used
    used_indices.clear()
    save_json(USED_RIDDLES_FILE, [])
    random.shuffle(shuffled_order)
    save_json(SHUFFLED_ORDER_FILE, shuffled_order)
    idx = shuffled_order[0]
    used_indices.add(idx)
    save_json(USED_RIDDLES_FILE, list(used_indices))
    return all_riddles[idx]

def get_title_and_emoji(score):
    if score <= 5:
        return "Sushi Newbie", "🍣"
    elif score <= 15:
        return "Maki Novice", "🍥"
    elif score <= 25:
        return "Sashimi Scholar", "🍱"
    elif score <= 50:
        return "Brainy Bites", "🧠"
    else:
        return "Master Omakase", "🎌"

def get_streak_title_and_desc(streak):
    if streak >= 3:
        return ("Streak Samurai", f"🔥 Solved {streak} riddles consecutively!")
    return (None, None)

def get_leader_title_and_desc(rank):
    if rank == 1:
        return ("Chopstick Champ", "🥢 Top solver on the leaderboard!")
    return (None, None)

class LeaderboardView(View):
    def __init__(self, user_id):
        super().__init__(timeout=120)
        self.user_id = user_id

    async def interaction_check(self, interaction):
        return interaction.user.id == int(self.user_id)

    @button(emoji="⬅️", style=ButtonStyle.primary)
    async def prev_page(self, interaction, button):
        if self.user_id in leaderboard_pages and leaderboard_pages[self.user_id] > 0:
            leaderboard_pages[self.user_id] -= 1
            await show_leaderboard(interaction.channel, self.user_id, interaction)

    @button(emoji="➡️", style=ButtonStyle.primary)
    async def next_page(self, interaction, button):
        if self.user_id in leaderboard_pages:
            leaderboard_pages[self.user_id] += 1
            await show_leaderboard(interaction.channel, self.user_id, interaction)

@client.event
async def on_ready():
    print(f"✅ Logged in as {client.user}")
    await tree.sync()
    post_riddle.start()
    reveal_answer.start()

@tree.command(name="riddleoftheday", description="Show Riddle of the Day bot commands")
async def riddle_commands(interaction: discord.Interaction):
    commands_list = (
        "**Riddle of the Day Bot Commands:**\n"
        "• `/riddleoftheday` - Show this command list\n"
        "• `!score` - Show your current score and streak\n"
        "• `!leaderboard` - Show the leaderboard\n"
        "• Use arrow buttons on leaderboard to scroll pages\n"
        "• `/submit` - Submit a new riddle\n"
        "\nSubmit your answer by typing it directly in the riddle channel."
    )
    await interaction.response.send_message(commands_list, ephemeral=True)

@tree.command(name="submit", description="Submit a new riddle question and answer")
@app_commands.describe(question="Your riddle question", answer="The answer to your riddle")
async def submit_riddle(interaction: discord.Interaction, question: str, answer: str):
    user_id = str(interaction.user.id)
    formatted_question = f"@everyone {question.strip()} ***(Answer will be revealed later this evening)***"

    global all_riddles, shuffled_order, used_indices

    new_riddle = {
        "question": formatted_question,
        "answer": answer.strip(),
        "user_id": user_id
    }
    all_riddles.append(new_riddle)
    save_json(SUBMITTED_FILE, all_riddles)

    shuffled_order = list(range(len(all_riddles)))
    random.shuffle(shuffled_order)
    save_json(SHUFFLED_ORDER_FILE, shuffled_order)
    used_indices.clear()
    save_json(USED_RIDDLES_FILE, [])

    await interaction.response.send_message(
        f"✅ Thanks {interaction.user.mention}! Your riddle has been submitted. You won’t be able to answer this riddle when it appears.",
        ephemeral=True
    )

@tasks.loop(time=datetime.time(hour=15, minute=0))  # 3:00 PM UTC
async def post_riddle():
    global current_riddle, correct_users
    current_riddle = get_next_riddle()
    correct_users = set()

    channel = client.get_channel(CHANNEL_ID)
    if current_riddle and channel:
        submitter_id = current_riddle.get("user_id")
        if submitter_id is None or submitter_id == "null":
            submitter_text = "Riddle of the Day bot"
        else:
            try:
                user = await client.fetch_user(int(submitter_id))
                submitter_text = user.display_name
            except:
                submitter_text = "Riddle of the Day bot"

        # Add note if less than 5 unused riddles remain
        remaining = len(all_riddles) - len(used_indices)
        note = ""
        if remaining < 5:
            note = "\n\n⚠️ *Less than 5 new riddles remain - submit a new riddle with `/submit` to add it to the queue!*"

        question_to_send = f"{current_riddle['question']}{note}"

        await channel.send(
            f"🧠 **Riddle of the Day:**\n{question_to_send}\n\n_Submitted by {submitter_text}_\n\nSubmit your guess in this channel — your answer will be hidden!"
        )
        logging.info("✅ Riddle posted")
    else:
        logging.warning("⚠️ Riddle or channel missing")

@tasks.loop(time=datetime.time(hour=20, minute=0))  # 8:00 PM UTC
async def reveal_answer():
    global current_riddle, correct_users

    if not current_riddle:
        return

    channel = client.get_channel(CHANNEL_ID)
    correct_answer = normalize_answer(current_riddle["answer"])

    if channel:
        if correct_users:
            lines = [f"✅ The correct answer was **{correct_answer}**!\n"]
            lines.append("The following users got it correct:")

            for uid in correct_users:
                uid_str = str(uid)
                scores[uid_str] = scores.get(uid_str, 0) + 1
                streaks[uid_str] = streaks.get(uid_str, 0) + 1
                user = await client.fetch_user(uid)
                lines.append(f"• {user.mention} (**{scores[uid_str]}** total, 🔥 {streaks[uid_str]} streak)")

            lines.append("\n📅 Stay tuned for tomorrow’s riddle!")
            await channel.send("\n".join(lines))
        else:
            await channel.send(f"❌ The correct answer was **{correct_answer}**. No one got it right today.")

        # Reset streaks for users who missed
        for uid in list(scores.keys()):
            if int(uid) not in correct_users:
                streaks[uid] = 0

        save_json(SCORES_FILE, scores)
        save_json(STREAKS_FILE, streaks)

    current_riddle = None
    correct_users.clear()

@client.event
async def on_message(message):
    if message.author == client.user:
        return

    user_id = str(message.author.id)
    msg = message.content.lower().strip()

    # Don't delete command messages
    if msg in ("!score", "!leaderboard", "!next", "!prev"):
        pass
    else:
        # Delete guesses only in the riddle channel and only while riddle is active
        if current_riddle and message.channel.id == CHANNEL_ID:
            try:
                await message.delete()
            except:
                pass

    if msg == "!score":
        score = scores.get(user_id, 0)
        streak = streaks.get(user_id, 0)
        title, emoji = get_title_and_emoji(score)
        streak_title, streak_desc = get_streak_title_and_desc(streak)

        lines = [f"📊 {message.author.display_name}'s score: **{score}**, {emoji} *{title}*"]
        if streak_title:
            lines.append(f"🔥 Streak: **{streak}** — *{streak_title}*: {streak_desc}")
        else:
            lines.append(f"🔥 Streak: **{streak}**")

        await message.channel.send("\n".join(lines))
        return

    elif msg == "!leaderboard":
        leaderboard_pages[user_id] = 0
        await show_leaderboard(message.channel, user_id)
        return

    elif msg == "!next":
        if user_id in leaderboard_pages:
            leaderboard_pages[user_id] += 1
            await show_leaderboard(message.channel, user_id)
        return

    elif msg == "!prev":
        if user_id in leaderboard_pages and leaderboard_pages[user_id] > 0:
            leaderboard_pages[user_id] -= 1
            await show_leaderboard(message.channel, user_id)
        return

    # Answer submission
    if current_riddle and message.channel.id == CHANNEL_ID:
        # Prevent submitter from answering their own riddle
        submitter_id = current_riddle.get("user_id")
        if submitter_id == user_id:
            # Let them know they can't answer their own riddle
            await message.channel.send(
                f"{message.author.mention} ❌ You cannot answer your own submitted riddle!",
                delete_after=10
            )
            return

        user_answer = normalize_answer(message.content)
        correct_answer = normalize_answer(current_riddle["answer"])

        if user_answer == correct_answer:
            correct_users.add(message.author.id)
            await message.channel.send(
                f"{message.author.mention} ✅ Thanks for your submission! The answer will be revealed at 20:00 UTC.",
                delete_after=10
            )
        else:
            # Optionally respond to wrong answers or just silently ignore
            pass

async def show_leaderboard(channel, user_id, interaction=None):
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
    for i, (uid, score) in enumerate(sorted_scores[start:start+10], start=start + 1):
        user = await client.fetch_user(int(uid))
        streak = streaks.get(uid, 0)
        title, emoji = get_title_and_emoji(score)
        streak_title, streak_desc = get_streak_title_and_desc(streak)
        leader_title, leader_desc = get_leader_title_and_desc(i)

        line_title = f"{i}. {user.display_name} {emoji} *{title}*"
        line_value = f"Correct: **{score}**, 🔥 Streak: {streak}"
        if streak_title:
            line_value += f"\n*{streak_title}*: {streak_desc}"
        if leader_title:
            line_value += f"\n**{leader_title}**: {leader_desc}"

        embed.add_field(name=line_title, value=line_value, inline=False)

    embed.set_footer(text="Use the arrow buttons below to navigate pages")

    view = LeaderboardView(user_id)

    if interaction:
        await interaction.response.edit_message(embed=embed, view=view)
    else:
        await channel.send(embed=embed, view=view)

# Start keep alive server
keep_alive()

# Run bot
client.run(TOKEN)
