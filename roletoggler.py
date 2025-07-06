import discord
from discord.ext import commands

class RoleToggler(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    async def bot(self, ctx):
        """Gives the 🤖 role which allows you to talk with chat bots in the Bot channel."""
        role = discord.utils.get(ctx.guild.roles, name="🤖")
        if role in ctx.author.roles:
            await ctx.author.remove_roles(role)
            await ctx.send(f"{ctx.author.mention} You have been removed from the 🤖 role.", delete_after=20)
        else:
            await ctx.author.add_roles(role)
            await ctx.send(f"{ctx.author.mention} You have been added to the 🤖 role.", delete_after=20)

def setup(bot):
    bot.add_cog(RoleToggler(bot))