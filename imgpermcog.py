import discord
from discord.ext import commands
import asyncio
import datetime
import time
import re
import json

class ImgPermCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.imgperm_timers = {}
        self.filename = 'imgperm_timers.json'
        try:
            with open(self.filename, 'r') as f:
                self.imgperm_timers = json.load(f)
        except FileNotFoundError:
            pass

    async def save_imgperm_timers(self):
        with open(self.filename, 'w') as f:
            json.dump(self.imgperm_timers, f)

    @commands.command(name='imgperm')
    @commands.has_any_role('I', 'II')
    async def imgperm(self, ctx, user: discord.Member, time: str = None):
        """Takes away user's image perms."""
        role = discord.utils.get(ctx.guild.roles, name='imgperm')
        await user.add_roles(role)
        if time is not None:
            time_match = re.match(r'(\d+)([smhd]?)', time)
            if time_match:
                time_amount = int(time_match.group(1))
                time_unit = time_match.group(2)
                if time_unit == 's':
                    time_delta = datetime.timedelta(seconds=time_amount)
                elif time_unit == 'm':
                    time_delta = datetime.timedelta(minutes=time_amount)
                elif time_unit == 'h':
                    time_delta = datetime.timedelta(hours=time_amount)
                elif time_unit == 'd':
                    time_delta = datetime.timedelta(days=time_amount)
                else:
                    time_delta = datetime.timedelta(seconds=time_amount)
                remove_time = datetime.datetime.now() + time_delta
                self.imgperm_timers[str(user.id)] = remove_time.timestamp()
                await asyncio.sleep(time_delta.total_seconds())
                await user.remove_roles(role)
                await ctx.send(f'imgperm role has been removed from {user.mention}')
                del self.imgperm_timers[str(user.id)]
                await self.save_imgperm_timers()
        else:
            await ctx.send(f'imgperm role has been added to {user.mention} indefinitely')

    @commands.command(name='uimgperm')
    @commands.has_any_role('I', 'II')
    async def uimgperm(self, ctx, user: discord.Member):
        """Gives back user's image perms."""
        role = discord.utils.get(ctx.guild.roles, name='imgperm')
        await user.remove_roles(role)
        await ctx.send(f'imgperm role has been removed from {user.mention}')

def setup(bot):
    bot.add_cog(ImgPermCog(bot))