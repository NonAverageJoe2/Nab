import discord
from discord.ext import commands, tasks
from discord import app_commands
import sqlite3
from datetime import datetime, timedelta
from typing import List


GUILD_ID = 1385991417393844224  # Replace with your server's ID
LUNATIC_ROLE_ID = 1385993304834838548  # Replace with your "Lunatic" role ID

class InactivityCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = sqlite3.connect("inactivity.db")
        self.cursor = self.db.cursor()
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_activity (
                user_id INTEGER,
                guild_id INTEGER,
                last_active TEXT,
                warned_7d INTEGER DEFAULT 0,
                warned_21d INTEGER DEFAULT 0,
                role_removed INTEGER DEFAULT 0,
                PRIMARY KEY (user_id, guild_id)
            )
        """)
        self.db.commit()
        self.check_inactivity.start()

    def update_activity(self, user_id, guild_id):
        now = datetime.utcnow().isoformat()
        self.cursor.execute("""
            INSERT INTO user_activity (user_id, guild_id, last_active)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id, guild_id) DO UPDATE SET last_active=excluded.last_active
        """, (user_id, guild_id, now))
        self.db.commit()

    def is_exempt(self, member: discord.Member) -> bool:
        if member.id == member.guild.owner_id:
            return True
        if member.guild_permissions.administrator:
            return True
        for role in member.roles:
            if role.is_premium_subscriber():
                return True
        return False

    # Message activity
    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.guild:
            return
        self.update_activity(message.author.id, message.guild.id)

    # Reaction activity
    @commands.Cog.listener()
    async def on_reaction_add(self, reaction: discord.Reaction, user: discord.User):
        if user.bot or reaction.message.guild is None:
            return
        self.update_activity(user.id, reaction.message.guild.id)

    # VC activity
    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if member.bot or member.guild is None:
            return
        if before.channel != after.channel:
            self.update_activity(member.id, member.guild.id)

    # Typing activity
    @commands.Cog.listener()
    async def on_typing(self, channel, user, when):
        if user.bot or not hasattr(channel, "guild") or channel.guild is None:
            return
        self.update_activity(user.id, channel.guild.id)

    # Slash command to check inactivity
    @app_commands.command(name="inactivity", description="Check how long a user has been inactive.")
    async def inactivity(self, interaction: discord.Interaction, member: discord.Member):
        self.cursor.execute(
            "SELECT last_active FROM user_activity WHERE user_id = ? AND guild_id = ?",
            (member.id, interaction.guild.id)
        )
        row = self.cursor.fetchone()
        if row:
            last_active = datetime.fromisoformat(row[0])
            delta = datetime.utcnow() - last_active
            days = delta.days
            hours = delta.seconds // 3600
            minutes = (delta.seconds % 3600) // 60
            await interaction.response.send_message(
                f"🕒 **{member.display_name}** was last active `{days}d {hours}h {minutes}m` ago.",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"No activity data found for {member.display_name}.", ephemeral=True
            )
            
    @app_commands.command(name="inactivitylist", description="View the most inactive users in the server.")
    async def inactivitylist(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        self.cursor.execute("""
            SELECT user_id, last_active FROM user_activity
            WHERE guild_id = ?
        """, (guild.id,))
        rows = self.cursor.fetchall()
        
        now = datetime.utcnow()
        data = []

        for user_id, last_active_str in rows:
            member = guild.get_member(user_id)
            if not member or member.bot or self.is_exempt(member):
                continue
            last_active = datetime.fromisoformat(last_active_str)
            delta = now - last_active
            data.append((member, delta))

        data.sort(key=lambda x: x[1], reverse=True)
        
        if not data:
            await interaction.followup.send("No inactive members found.", ephemeral=True)
            return

        pages = []
        for i in range(0, len(data), 10):
            chunk = data[i:i+10]
            desc = ""
            for idx, (member, delta) in enumerate(chunk, start=i+1):
                days = delta.days
                hours = delta.seconds // 3600
                minutes = (delta.seconds % 3600) // 60
                desc += f"`{idx}.` **{member.display_name}** — `{days}d {hours}h {minutes}m`\n"
            embed = discord.Embed(
                title="📉 Most Inactive Members",
                description=desc,
                color=discord.Color.orange()
            )
            embed.set_footer(text=f"Page {len(pages)+1}")
            pages.append(embed)

        msg = await interaction.followup.send(embed=pages[0], ephemeral=True)
        if len(pages) == 1:
            return

        for emoji in ['⏮️', '⬅️', '➡️', '⏭️']:
            await msg.add_reaction(emoji)

        def check(reaction, user):
            return user == interaction.user and reaction.message.id == msg.id and str(reaction.emoji) in ['⏮️', '⬅️', '➡️', '⏭️']

        current = 0
        while True:
            try:
                reaction, user = await self.bot.wait_for("reaction_add", timeout=60.0, check=check)
                await msg.remove_reaction(reaction.emoji, user)
                if str(reaction.emoji) == '⏮️':
                    current = 0
                elif str(reaction.emoji) == '⬅️':
                    current = max(0, current - 1)
                elif str(reaction.emoji) == '➡️':
                    current = min(len(pages) - 1, current + 1)
                elif str(reaction.emoji) == '⏭️':
                    current = len(pages) - 1

                await msg.edit(embed=pages[current])
            except asyncio.TimeoutError:
                break

        try:
            await msg.clear_reactions()
        except discord.Forbidden:
            pass


    @tasks.loop(hours=6)
    async def check_inactivity(self):
        now = datetime.utcnow()
        guild = self.bot.get_guild(GUILD_ID)
        if guild is None:
            return
        role = guild.get_role(LUNATIC_ROLE_ID)
        if role is None:
            return

        self.cursor.execute("SELECT user_id, last_active, warned_7d, role_removed, warned_21d FROM user_activity WHERE guild_id = ?", (GUILD_ID,))
        rows = self.cursor.fetchall()

        for user_id, last_active_str, warned_7d, role_removed, warned_21d in rows:
            member = guild.get_member(user_id)
            if not member or member.bot or self.is_exempt(member):
                continue

            last_active = datetime.fromisoformat(last_active_str)
            inactivity_days = (now - last_active).days

            try:
                if inactivity_days >= 7 and not warned_7d:
                    await member.send("🔕 You've been inactive for 7 days. You will lose the **Lunatic** role in 7 more days if you stay inactive.")
                    self.cursor.execute("UPDATE user_activity SET warned_7d = 1 WHERE user_id = ? AND guild_id = ?", (user_id, GUILD_ID))

                elif inactivity_days >= 14 and not role_removed:
                    if role in member.roles:
                        await member.remove_roles(role, reason="Inactive for 14 days")
                        await member.send("You've lost the **Lunatic** role due to 14 days of inactivity. You will be kicked in 14 more days if inactive.")
                    self.cursor.execute("UPDATE user_activity SET role_removed = 1 WHERE user_id = ? AND guild_id = ?", (user_id, GUILD_ID))

                elif inactivity_days >= 21 and role_removed and not warned_21d:
                    await member.send("You've been inactive for 21 days. You will be **kicked** from the server in 7 days if you don't return.")
                    self.cursor.execute("UPDATE user_activity SET warned_21d = 1 WHERE user_id = ? AND guild_id = ?", (user_id, GUILD_ID))

                elif inactivity_days >= 28 and role_removed:
                    await member.send("You've been kicked from the server due to 28 days of inactivity.")
                    await member.kick(reason="Inactive for 28 days")
                    self.cursor.execute("DELETE FROM user_activity WHERE user_id = ? AND guild_id = ?", (user_id, GUILD_ID))

            except discord.Forbidden:
                continue
            except discord.HTTPException:
                continue

        self.db.commit()

    @check_inactivity.before_loop
    async def before_loop(self):
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(InactivityCog(bot))
