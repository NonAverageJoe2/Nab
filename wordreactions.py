import discord
import json
from discord.ext import commands

class WordReactions(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.config_file = "word_reactions.json"
        self.load_reactions()
        
        # Default word reactions - you can customize these
        if not self.word_reactions:
            self.word_reactions = {
                "bunny": "\U0001F62D",
                "child": "\U0001F62D",
                "meow": "<:glape:1387575837133377628>",
                "plap": "\U0001F346",
                "trans": "\U0001F3F3\ufe0f\u200d\u26a7\ufe0f"
            }
            self.save_reactions()
    
    def load_reactions(self):
        """Load word reactions from JSON file"""
        try:
            with open(self.config_file, "r") as file:
                self.word_reactions = json.load(file)
        except FileNotFoundError:
            self.word_reactions = {}
    
    def save_reactions(self):
        """Save word reactions to JSON file"""
        try:
            with open(self.config_file, "w") as file:
                json.dump(self.word_reactions, file, indent=2)
        except Exception as e:
            print(f"Error saving reactions: {e}")
    
    @commands.Cog.listener()
    async def on_message(self, message):
        """React to messages containing trigger words"""
        # Ignore bot messages and commands
        if message.author.bot or message.content.startswith('~'):
            return
        
        message_lower = message.content.lower()
        
        # Check each word in the message
        for trigger_word, emoji in self.word_reactions.items():
            if trigger_word.lower() in message_lower:
                try:
                    await message.add_reaction(emoji)
                    # Only react once per message to avoid spam
                    break
                except discord.HTTPException:
                    # Ignore if we can't add reaction (permissions, invalid emoji, etc.)
                    continue
                except Exception as e:
                    print(f"Error adding reaction: {e}")
                    continue
    
    def cog_unload(self):
        """Save reactions when cog is unloaded"""
        self.save_reactions()

def setup(bot):
    bot.add_cog(WordReactions(bot))
