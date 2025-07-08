import asyncio
import discord
import os

# State variables
current_riddle = None
current_answer_revealed = False
correct_users = set()
guess_attempts = {}
deducted_for_user = set()

scores = {}   # Load your actual scores dict here
streaks = {}  # Load your actual streaks dict here

def get_rank(score, streak):
    # Example rank logic placeholder
    if score > 50:
        return "Master"
    if score > 20:
        return "Expert"
    return "Beginner"

def save_all_scores():
    # Implement your actual save logic here, e.g. write to JSON or DB
    pass

def clamp_min_zero(value):
    return max(0, value)

async def run_test_sequence(interaction, client):
    await interaction.response.defer(ephemeral=True)

    channel_id = int(os.getenv("DISCORD_CHANNEL_ID") or 0)
    channel = client.get_channel(channel_id)
    if not channel:
        await interaction.followup.send("❌ Test failed: Channel not found.", ephemeral=True)
        return

    global current_riddle, current_answer_revealed, correct_users, guess_attempts, deducted_for_user

    current_riddle = {
        "id": 9999,
        "question": "What has keys but can't open locks?",
        "answer": "piano",
        "submitter_id": None,
    }
    current_answer_revealed = False
    correct_users = set()
    guess_attempts = {}
    deducted_for_user = set()

    embed = discord.Embed(
        title=f"🧩 Riddle of the Day #{current_riddle['id']}",
        description=f"**Riddle:** {current_riddle['question']}\n\n_(Riddle submitted by **Riddle of the Day Bot**)_",
        color=discord.Color.blurple()
    )
    await channel.send(embed=embed)
    await interaction.followup.send("✅ Test riddle posted. Waiting 30 seconds before revealing answer...", ephemeral=True)

    await asyncio.sleep(30)

    answer_embed = discord.Embed(
        title=f"🔔 Answer to Riddle #{current_riddle['id']}",
        description=f"**Answer:** {current_riddle['answer']}\n\n💡 Use `/submitriddle` to submit your own riddle!",
        color=discord.Color.green()
    )
    await channel.send(embed=answer_embed)

    if correct_users:
        congrats_lines = []
        for user_id_str in correct_users:
            try:
                user = await client.fetch_user(int(user_id_str))
                uid = str(user.id)
                sv = scores.get(uid, 0)
                st = streaks.get(uid, 0)
                rank = get_rank(sv, st)
                congrats_lines.append(f"{user.mention} — Score: **{sv}**, Streak: 🔥{st}, Rank: {rank}")
            except:
                congrats_lines.append(f"<@{user_id_str}>")
        congrats_msg = "🎉 Congratulations to:\n" + "\n".join(congrats_lines)
        await channel.send(congrats_msg)
    else:
        await channel.send("😢 No one guessed the riddle correctly during the test.")

    current_answer_revealed = True
    correct_users.clear()
    guess_attempts.clear()
    deducted_for_user.clear()
    current_riddle = None

    await channel.send("✅ Test sequence completed. You can run `/run_test_sequence` again to test.")

# Similarly, implement points and streak modification logic here as functions:

async def add_points(interaction, user, amount):
    if amount <= 0:
        await interaction.response.send_message("❌ Amount must be a positive integer.", ephemeral=True)
        return
    uid = str(user.id)
    scores[uid] = scores.get(uid, 0) + amount
    save_all_scores()
    await interaction.response.send_message(f"✅ Added {amount} point(s) to {user.mention}. New score: {scores[uid]}", ephemeral=True)

async def add_streak(interaction, user, amount):
    if amount <= 0:
        await interaction.response.send_message("❌ Amount must be a positive integer.", ephemeral=True)
        return
    uid = str(user.id)
    streaks[uid] = streaks.get(uid, 0) + amount
    save_all_scores()
    await interaction.response.send_message(f"✅ Added {amount} streak day(s) to {user.mention}. New streak: {streaks[uid]}", ephemeral=True)

async def remove_points(interaction, user, amount):
    if amount <= 0:
        await interaction.response.send_message("❌ Amount must be a positive integer.", ephemeral=True)
        return
    uid = str(user.id)
    new_score = clamp_min_zero(scores.get(uid, 0) - amount)
    scores[uid] = new_score
    save_all_scores()
    await interaction.response.send_message(f"❌ Removed {amount} point(s) from {user.mention}. New score: {scores[uid]}", ephemeral=True)

async def remove_streak(interaction, user, amount):
    if amount <= 0:
        await interaction.response.send_message("❌ Amount must be a positive integer.", ephemeral=True)
        return
    uid = str(user.id)
    new_streak = clamp_min_zero(streaks.get(uid, 0) - amount)
    streaks[uid] = new_streak
    save_all_scores()
    await interaction.response.send_message(f"❌ Removed {amount} streak day(s) from {user.mention}. New streak: {streaks[uid]}", ephemeral=True)
