from discord import app_commands, Interaction, Embed
from discord.ui import View, Button
import discord
import db  
from db import db_pool




async def get_streak(user_id: str) -> int:
    return await db.get_streak(user_id) or 0

async def get_rank(score):
    # You may want to make this async if needed, or pass in pre-fetched max_score/streak
    if score >= 99:
        return "🎲⛳ Plato Master"
    # Add your rank logic as needed

async def get_streak_rank(streak):
    # Stub or fill in your streak rank logic async if needed
    if streak >= 30:
        return "💚🔥 Wasabi Warlord (30+ day streak)"
    return None




class LeaderboardView(View):
    def __init__(self, client, users, per_page=10):
        super().__init__(timeout=120)
        self.client = client
        self.users = users  # list of user_id strings
        self.per_page = per_page
        self.current_page = 0
        self.max_page = (len(users) - 1) // per_page
        self.prev_button.disabled = True
        if self.max_page == 0:
            self.next_button.disabled = True

    async def update_message(self, interaction: Interaction):
        start = self.current_page * self.per_page
        end = start + self.per_page
        page_users = self.users[start:end]

        embed = Embed(
            title=f"🏆 Riddle Leaderboard (Page {self.current_page + 1} / {self.max_page + 1})",
            color=discord.Color.gold()
        )

        # Fetch all scores asynchronously for the users on this page
        scores_streaks = {}
        for uid in page_users:
            score = await get_score(uid)
            streak = await get_streak(uid)
            scores_streaks[uid] = (score, streak)

        max_score = max((score for score, _ in scores_streaks.values()), default=0)

        description_lines = []
        for idx, user_id_str in enumerate(page_users, start=start + 1):
            try:
                user = await self.client.fetch_user(int(user_id_str))
                score_val, streak_val = scores_streaks.get(user_id_str, (0, 0))

                score_line = f"{score_val}"
                if score_val == max_score and max_score > 0:
                    score_line += " - 🎲⛳ Plato Master"

                rank = await get_rank(score_val)
                streak_rank = await get_streak_rank(streak_val)
                streak_text = f"🔥{streak_val}"
                if streak_rank:
                    streak_text += f" - {streak_rank}"

                description_lines.append(f"#{idx} {user.display_name}:")
                description_lines.append(f"    • Score: {score_line}")
                description_lines.append(f"    • Rank: {rank}")
                description_lines.append(f"    • Streak: {streak_text}")
                description_lines.append("")
            except Exception:
                description_lines.append(f"#{idx} <@{user_id_str}> (failed to fetch user)")
                description_lines.append("")

        embed.description = "\n".join(description_lines) or "No users to display."

        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary)
    async def prev_button(self, interaction: Interaction, button: Button):
        if self.current_page > 0:
            self.current_page -= 1
        button.disabled = self.current_page == 0
        self.next_button.disabled = False
        await self.update_message(interaction)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: Interaction, button: Button):
        if self.current_page < self.max_page:
            self.current_page += 1
        button.disabled = self.current_page == self.max_page
        self.prev_button.disabled = False
        await self.update_message(interaction)


async def create_leaderboard_embed(client):
    # Get top scores & streaks from DB (assuming you have a DB function for top users)
    top_scores_data = await db.get_top_scores(limit=10)  # returns list of tuples (user_id:str, score:int, streak:int)

    max_score = max((score for _, score, _ in top_scores_data), default=0)

    leaderboard_embed = discord.Embed(
        title="🏆 Riddle of the Day Leaderboard",
        color=discord.Color.purple()
    )

    description_lines = []

    for idx, (user_id, score_val, streak_val) in enumerate(top_scores_data, start=1):
        try:
            user = await client.fetch_user(int(user_id))

            score_line = f"    • Score: {score_val}"
            if score_val == max_score and max_score > 0:
                score_line += " — 🎲⛳ Plato Master"

            rank = await get_rank(score_val)
            streak_title = await get_streak_rank(streak_val)
            streak_line = f"    • Streak: 🔥{streak_val}"
            if streak_title:
                streak_line += f" — {streak_title}"

            description_lines.append(f"#{idx} {user.display_name}:")
            description_lines.append(score_line)
            description_lines.append(f"    • Rank: {rank}")
            description_lines.append(streak_line)
            description_lines.append("")
        except Exception:
            description_lines.append(f"#{idx} <@{user_id}> (User data unavailable)")
            description_lines.append("")

    leaderboard_embed.description = "\n".join(description_lines)
    leaderboard_embed.set_footer(text="Ranks update automatically based on your progress.")

    return leaderboard_embed


class ListRiddlesView(View):
    def __init__(self, riddles, user_id, client, per_page=5):
        super().__init__(timeout=300)
        self.riddles = riddles  # list of riddles dicts
        self.user_id = user_id
        self.client = client
        self.per_page = per_page
        self.current_page = 0
        self.total_pages = (len(riddles) - 1) // per_page + 1

        self.prev_button = Button(label="⬅️ Previous", style=discord.ButtonStyle.secondary)
        self.next_button = Button(label="Next ➡️", style=discord.ButtonStyle.secondary)

        self.prev_button.callback = self.go_previous
        self.next_button.callback = self.go_next

        self.add_item(self.prev_button)
        self.add_item(self.next_button)

        self.update_buttons()

    def update_buttons(self):
        self.prev_button.disabled = self.current_page == 0
        self.next_button.disabled = self.current_page >= self.total_pages - 1

    async def go_previous(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("You're not authorized to control this view.", ephemeral=True)
            return

        self.current_page -= 1
        self.update_buttons()
        embed = await self.get_page_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    async def go_next(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("You're not authorized to control this view.", ephemeral=True)
            return

        self.current_page += 1
        self.update_buttons()
        embed = await self.get_page_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    async def get_page_embed(self):
        start = self.current_page * self.per_page
        end = start + self.per_page
        page_riddles = self.riddles[start:end]

        embed = Embed(
            title=f"📜 Submitted Riddles (Page {self.current_page + 1}/{self.total_pages})",
            color=discord.Color.blurple()
        )

        for riddle in page_riddles:
            submitter = self.client.get_user(int(riddle["user_id"]))
            submitter_name = submitter.display_name if submitter else f"User ID {riddle['user_id']}"
            embed.add_field(
                name=f"🧩 Riddle #{riddle['riddle_id']}",
                value=f"**Question:** {riddle['question']}\n**Answer:** ||{riddle['answer']}||\n_Submitted by: {submitter_name}_",
                inline=False
            )

        return embed

async def format_question_embed_db(qdict, submitter=None):
    embed = discord.Embed(
        title=f"🧠 Riddle #{qdict['id']}",
        description=qdict['question'],
        color=discord.Color.blurple()
    )
    embed.set_footer(text="Answer will be revealed at 23:00 UTC. Use /submitriddle to contribute your own!")

    remaining = await count_unused_questions_db()
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

 