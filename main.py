from discord.ui import View, Button

class LeaderboardView(View):
    def __init__(self, user_id_str):
        super().__init__(timeout=120)  # 2 minutes timeout
        self.user_id_str = user_id_str
        self.page = leaderboard_pages.get(user_id_str, 0)

    async def update_message(self, interaction):
        await interaction.response.edit_message(embed=await build_leaderboard_embed(self.user_id_str, self.page), view=self)

    @discord.ui.button(emoji="⬅️", style=discord.ButtonStyle.primary)
    async def previous_button(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != int(self.user_id_str):
            await interaction.response.send_message("❌ You can't control someone else's leaderboard.", ephemeral=True)
            return
        if self.page > 0:
            self.page -= 1
            leaderboard_pages[self.user_id_str] = self.page
            await self.update_message(interaction)

    @discord.ui.button(emoji="➡️", style=discord.ButtonStyle.primary)
    async def next_button(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != int(self.user_id_str):
            await interaction.response.send_message("❌ You can't control someone else's leaderboard.", ephemeral=True)
            return
        sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        total_pages = max((len(sorted_scores) - 1) // 10 + 1, 1)
        if self.page < total_pages - 1:
            self.page += 1
            leaderboard_pages[self.user_id_str] = self.page
            await self.update_message(interaction)

async def build_leaderboard_embed(user_id_str, page):
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
        is_top_solver = (i == 1)
        title, description = get_title(uid, is_top_solver=is_top_solver)
        embed.add_field(
            name=f"{i}. {user.display_name}",
            value=f"Correct: **{score}**, 🔥 Streak: {streak} {title}",
            inline=False
        )
    embed.set_footer(text="Use the buttons below to navigate pages")
    return embed

# Update the !leaderboard command handler:

@client.event
async def on_message(message):
    if message.author == client.user:
        return
    user_id_str = str(message.author.id)
    msg = message.content.lower().strip()

    # ... other commands ...

    if msg.startswith("!leaderboard"):
        leaderboard_pages[user_id_str] = 0
        view = LeaderboardView(user_id_str)
        embed = await build_leaderboard_embed(user_id_str, 0)
        await message.channel.send(embed=embed, view=view)
        return

    # Remove old !next and !prev handlers, since buttons replace them

    # ... rest of on_message ...
