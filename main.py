# Add this ranking logic near the top, after loading scores/streaks

def get_rank(score, streak):
    # Define sushi-themed ranks
    # Score-based ranks:
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
    
    # Special streak ranks if streak >= 3:
    if streak >= 3:
        rank = f"🔥 Streak Samurai (Solved {streak} riddles consecutively)"
    return rank

# Inside your async def on_message(message): handler

if msg == "!score":
    score = scores.get(user_id, 0)
    streak = streaks.get(user_id, 0)
    rank = get_rank(score, streak)
    await message.channel.send(
        f"📊 {message.author.display_name}'s score: **{score}**, 🔥 Streak: {streak}\n🏅 Rank: {rank}"
    )
    return

# Your show_leaderboard function stays async

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

    for i, (uid, score) in enumerate(sorted_scores[start:start+10], start=start + 1):
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

    embed.set_footer(text="Use !next and !prev to navigate pages")
    await channel.send(embed=embed)

# In your reveal_answer task, keep this code inside the async function that runs the reveal:

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
