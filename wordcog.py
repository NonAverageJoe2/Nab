import discord
import json
from discord.ext import commands

class WordCounter(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.file_name = "word_counts.json"
        # self.file_count = "word_count.json" # This variable seems unused, you might want to remove it
        self.load_word_counts()

    def load_word_counts(self):
        try:
            with open(self.file_name, "r") as file:
                self.word_counts = json.load(file)
        except FileNotFoundError:
            self.word_counts = {}

    @commands.Cog.listener()
    async def on_message(self, message):
        # IMPORTANT: You need to define your words_to_count list here!
        # Example:
        words_to_count = ["freezer", "", "sex", "lq", "based", "cunny", "mod", "groom", "~lq", "fever", "janny", "nigger", "cirno", "uoh", "meow"]
        # Or, if you want to load it from a file or configuration, do so here.

        if message.content.startswith("~count") or message.author.id == self.bot.user.id:
            return
        
        for word in words_to_count:
            if word in message.content.lower():
                if word in self.word_counts:
                    self.word_counts[word] += 1
                    
                    # Convert the current count to a string once for efficiency
                    current_count_str = str(self.word_counts[word])

                    # Check for multiples of 1000
                    if self.word_counts[word] % 1000 == 0:
                        await message.channel.send(f"Congratulations <@{message.author.id}>! You are the {self.word_counts[word]}th person to say {word}!")
                    
                    # NEW: This will now trigger for 100, 200, 300, 400, etc.
                    if self.word_counts[word] % 100 == 0:
                        await message.channel.send(f"Congratulations <@{message.author.id}>! You are the {self.word_counts[word]}th person to say {word}!")
                    
                    # Check for the most specific "nice" number first
                    if current_count_str.endswith("42069"):
                        await message.channel.send(f"@everyone @everyone @everyone GET IN HERE <@{message.author.id}> WAS THE {self.word_counts[word]}TH PERSON TO SAY {word}!")
                    # Then check for less specific "nice" numbers, using elif to prevent duplicate messages
                    elif current_count_str.endswith("420") or current_count_str.endswith("69"):
                        await message.channel.send(f"Nice <@{message.author.id}>! You are the {self.word_counts[word]}th person to say {word}!")
                    
                else:
                    self.word_counts[word] = 1
        self.save_word_counts()

    @commands.command()
    async def count(self, ctx):
        """Shows the count of tracked words."""
        message = ""
        if self.word_counts:
            message = " ".join([f"{word}: {count}" for word, count in self.word_counts.items()])
        else:
            message = "No words have been counted yet."
        await ctx.send(message)

    def save_word_counts(self):
        with open(self.file_name, "w") as file:
            json.dump(self.word_counts, file)

    def cog_unload(self):
        self.save_word_counts()

def setup(bot):
    bot.add_cog(WordCounter(bot))
