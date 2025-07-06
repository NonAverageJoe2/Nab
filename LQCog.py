import random
import discord
from discord.ext import commands
import asyncio
import time

class LQCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.allowed_roles = ["II", "I"]
        self.last_use = {}
        self.log_channel_id = 1390515965380268163  # <- Set your log channel ID here

    @commands.command()
    async def lq(self, ctx, member: discord.Member = None, *, reason: str = None):
        """Assigns the 'lq' role and silently drops rep, with reason logged."""
        if not any(role.name in self.allowed_roles for role in ctx.author.roles):
            return await ctx.send(f"{ctx.author.mention} you can't do shit.")

        if not member:
            return await ctx.send("You must specify a member to LQ.")

        if not reason:
            return await ctx.send("You must provide a reason to LQ this person.")

        lq_role = discord.utils.get(member.guild.roles, name="low quality")
        lunatic_role = discord.utils.get(member.guild.roles, name="lunatic")

        if lq_role not in member.roles:
            try:
                # Remove lunatic role if present
                if lunatic_role and lunatic_role in member.roles:
                    await member.remove_roles(lunatic_role)

                # Add low quality role
                await member.add_roles(lq_role)

                # Adjust reputation silently
                rep_cog = self.bot.get_cog("ReputationCog")
                if rep_cog:
                    rep_cog.adjust_rep(member.id, ctx.guild.id, -5)

                # Log reason in log channel
                log_channel = self.bot.get_channel(self.log_channel_id)
                if log_channel:
                    await log_channel.send(
                        f"🔇 **LQ'd**: {member.mention} by {ctx.author.mention}\n📄 **Reason**: {reason}"
                    )

            except discord.errors.Forbidden:
                return await ctx.send("I can't cracka'")

        await ctx.message.add_reaction('\U0001F642')

    @commands.command()
    async def ulq(self, ctx, member: discord.Member = None):
        """Removes the 'lq' role and gives 'lunatic' back."""
        if not any(role.name in self.allowed_roles for role in ctx.author.roles):
            return await ctx.send(f"{ctx.author.mention} you can't do shit.")
        
        if not member:
            member = ctx.author
        
        lq_role = discord.utils.get(member.guild.roles, name="low quality")
        lunatic_role = discord.utils.get(member.guild.roles, name="lunatic")
        
        if lq_role in member.roles:
            try:
                await member.remove_roles(lq_role)
                if lunatic_role:
                    await member.add_roles(lunatic_role)
            except discord.errors.Forbidden:
                return await ctx.send("I can't cracka'")
                
        await ctx.message.add_reaction('\U0001f607')

    @commands.Cog.listener()
    async def on_message(self, message):
        # Ignore bots
        if message.author.bot:
            return

        # Delete user messages in log channel
        if message.channel.id == self.log_channel_id:
            await asyncio.sleep(3)
            await message.delete()
            return

        queries = ["what's lq", "what is lq", "whats lq", "what does lq mean"]
        if message.content.lower().strip() in queries:
            if self.last_use.get(message.author.id, 0) + 60 > time.time():
                return
            self.last_use[message.author.id] = time.time()

            guild = message.guild
            role = discord.utils.get(guild.roles, name="low quality")
            lunatic = discord.utils.get(guild.roles, name="lunatic")

            try:
                if lunatic and lunatic in message.author.roles:
                    await message.author.remove_roles(lunatic)

                await message.channel.send(f"Let me show you, {message.author.mention}.")
                await asyncio.sleep(5)
                await message.author.add_roles(role)
                await asyncio.sleep(30)
                await message.author.remove_roles(role)

                if lunatic:
                    await message.author.add_roles(lunatic)
            except discord.errors.Forbidden:
                pass

async def setup(bot):
    await bot.add_cog(LQCog(bot))
