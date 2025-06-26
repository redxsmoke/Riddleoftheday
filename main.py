@client.event
async def on_message(message):
    if message.author.bot:
        return

    channel_id = int(os.getenv("DISCORD_CHANNEL_ID", "0"))
    if channel_id == 0:
        print("DISCORD_CHANNEL_ID not set.")
        return

    # Only respond in the allowed channel
    if message.channel.id != channel_id:
        return

    content = message.content.strip()
    user_id = str(message.author.id)

    # Commands
    if content == "!score":
        score = scores.get(user_id, 0)
        streak = streaks.get(user_id, 0)
        rank = get_rank(score, streak)
        await message.channel.send(
            f"📊 {message.author.display_name}'s score: **{score}**, 🔥 Streak: {streak}\n🏅 Rank: {rank}"
        )
        return

    if content == "!leaderboard":
        leaderboard_pages[user_id] = 0
        await show_leaderboard(message.channel, user_id)
        return

    if content.startswith("!submit_riddle "):
        try:
            _, rest = content.split(" ", 1)
            question, answer = rest.split("|", 1)
            question = question.strip()
            answer = answer.strip()
            if not question or not answer:
                await message.channel.send("\u274c Please provide both a question and an answer, separated by '|'.")
                return
        except Exception:
            await message.channel.send("\u274c Invalid format. Use: `!submit_riddle Your question here | The answer here`")
            return

        new_id = str(int(datetime.utcnow().timestamp() * 1000)) + "_" + user_id
        submitted_questions.append({
            "id": new_id,
            "question": question,
            "answer": answer,
            "submitter_id": user_id
        })
        save_json(QUESTIONS_FILE, submitted_questions)
        await message.channel.send(f"✅ Thanks {message.author.mention}, your riddle has been submitted! It will appear in the queue soon.")
        return

    # Skip deletion for commands
    if content.startswith("!"):
        return

    # Guessing logic
    if current_riddle and not current_answer_revealed:
        guess = content.lower()
        correct_answer = current_riddle["answer"].lower()

        user_attempts = guess_attempts.get(user_id, 0)
        if user_attempts >= 5:
            await message.channel.send(f"❌ You're out of attempts for today's riddle, {message.author.mention}.")
            try:
                await message.delete()
            except Exception:
                pass
            return

        guess_attempts[user_id] = user_attempts + 1

        guess_simple = guess.rstrip("s")
        answer_simple = correct_answer.rstrip("s")

        if guess == correct_answer or guess_simple == answer_simple:
            correct_users.add(message.author.id)
            scores[user_id] = scores.get(user_id, 0) + 1
            streaks[user_id] = streaks.get(user_id, 0) + 1
            save_all_scores()

            await message.channel.send(
                f"🎉 Correct, {message.author.mention}! Keep it up! 🏅 Your current score: {scores[user_id]}"
            )
        else:
            remaining = 5 - guess_attempts[user_id]
            if remaining == 0:
                await message.channel.send(
                    f"❌ Sorry, that answer is incorrect, {message.author.mention}. You have no attempts left. "
                    "If you guess incorrectly again, you will lose 1 point."
                )
            elif remaining < 0:
                old_score = scores.get(user_id, 0)
                new_score = max(old_score - 1, 0)
                scores[user_id] = new_score
                save_all_scores()
                await message.channel.send(
                    f"❌ Sorry, that answer is incorrect again, {message.author.mention}. "
                    f"You lost 1 point. Your current score: {new_score}"
                )
            else:
                await message.channel.send(
                    f"❌ Sorry, that answer is incorrect, {message.author.mention} ({remaining} guesses remaining)."
                )

        try:
            await message.delete()
        except Exception:
            pass
