import json
import os

import discord
from discord.ext import commands

class ProhibitedWordsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.bad_words = []
        self.enabled = False
        self.load_words()
    
    def load_words(self):
        if os.path.exists("prohibited_words.json"):
            with open("prohibited_words.json", "r") as f:
                self.bad_words = json.load(f)

    def save_words(self):
        with open("prohibited_words.json", "w") as f:
            json.dump(self.bad_words, f)

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author == self.bot.user or not self.enabled:
            return

        for word in self.bad_words:
            if word in message.content:
                await message.delete()
                break

    @commands.group(name="prohibited", aliases=["profanity"])
    @commands.has_any_role("I", "II", "III")
    async def prohibited_group(self, ctx):
        """Prohibited on, off & other commands."""
        if ctx.invoked_subcommand is None:
            await ctx.send("Invalid command")

    @prohibited_group.command(name="add")
    async def prohibited_add(self, ctx, *, word: str):
        self.bad_words.append(word)
        self.save_words()
        await ctx.send(f"Added `{word}` to the prohibited words list")

    @prohibited_group.command(name="remove")
    async def prohibited_remove(self, ctx, *, word: str):
        if word in self.bad_words:
            self.bad_words.remove(word)
            self.save_words()
            await ctx.send(f"Removed `{word}` from the prohibited words list")
        else:
            await ctx.send(f"`{word}` is not in the prohibited words list")

    @prohibited_group.command(name="list")
    async def prohibited_list(self, ctx):
        words = ", ".join(self.bad_words)
        await ctx.send(f"Prohibited words: {words}")

    @prohibited_group.command(name="on")
    async def prohibited_on(self, ctx):
        self.enabled = True
        await ctx.send("Prohibited word check is enabled")

    @prohibited_group.command(name="off")
    async def prohibited_off(self, ctx):
        self.enabled = False
        await ctx.send("Prohibited word check is disabled")

def setup(bot):
    bot.add_cog(ProhibitedWordsCog(bot))
