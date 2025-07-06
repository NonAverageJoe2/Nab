# -*- coding: utf-8 -*-
import asyncio
import discord
from discord.ext import commands

class BoostCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.check_task = None
        # Define the emoji as a Unicode escape sequence for better compatibility
        self.boost_emoji = "\U0001F338"  # 🌸 cherry blossom
        # Alternative: self.boost_emoji = "🌸"
        
    @commands.Cog.listener()
    async def on_ready(self):
        """Start the background task once the bot is ready"""
        print(f"BoostCog ready! Using emoji: {self.boost_emoji}")
        if self.check_task is None:
            self.check_task = asyncio.create_task(self.check_role_loop())

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        """Handle real-time role changes"""
        try:
            role = discord.utils.get(after.guild.roles, name="☆")
            if role is None:
                return

            had_role = role in before.roles
            has_role = role in after.roles

            if not had_role and has_role:
                # Role was added — simulate "boost"
                if self.boost_emoji not in after.display_name:
                    new_nick = f"{after.display_name}{self.boost_emoji}"
                    await self.safe_edit_nick(after, new_nick)
                    print(f"Added boost emoji to {after.display_name}")
            elif had_role and not has_role:
                # Role was removed — unboosted
                if self.boost_emoji in after.display_name:
                    new_nick = after.display_name.replace(self.boost_emoji, "")
                    await self.safe_edit_nick(after, new_nick)
                    print(f"Removed boost emoji from {after.display_name}")
        except Exception as e:
            print(f"Error in on_member_update: {e}")

    async def check_role_loop(self):
        """Background task to sync nicknames with roles"""
        await self.bot.wait_until_ready()
        print("Starting role check loop...")
        
        while not self.bot.is_closed():
            try:
                for guild in self.bot.guilds:
                    role = discord.utils.get(guild.roles, name="☆")
                    if role is None:
                        continue

                    print(f"Checking guild: {guild.name}")
                    updates_made = 0
                    
                    for member in guild.members:
                        if member.bot:  # Skip bots
                            continue
                            
                        has_role = role in member.roles
                        has_emoji = self.boost_emoji in member.display_name
                        
                        if has_role and not has_emoji:
                            new_nick = f"{member.display_name}{self.boost_emoji}"
                            await self.safe_edit_nick(member, new_nick)
                            updates_made += 1
                        elif not has_role and has_emoji:
                            new_nick = member.display_name.replace(self.boost_emoji, "")
                            await self.safe_edit_nick(member, new_nick)
                            updates_made += 1
                        
                        # Small delay to avoid rate limits
                        await asyncio.sleep(0.2)
                    
                    if updates_made > 0:
                        print(f"Made {updates_made} nickname updates in {guild.name}")
                        
            except Exception as e:
                print(f"Error in check_role_loop: {e}")
            
            print("Waiting 10 minutes before next check...")
            await asyncio.sleep(600)  # Check every 10 minutes

    async def safe_edit_nick(self, member, new_nick):
        """Safely edit a member's nickname with error handling"""
        try:
            # Clean up the nickname (remove extra spaces, etc.)
            new_nick = new_nick.strip()
            
            # Discord nickname length limit is 32 characters
            if len(new_nick) > 32:
                # Keep the emoji and truncate the name part
                if self.boost_emoji in new_nick:
                    max_name_length = 32 - len(self.boost_emoji)
                    base_name = new_nick.replace(self.boost_emoji, "").strip()
                    new_nick = f"{base_name[:max_name_length]}{self.boost_emoji}"
                else:
                    new_nick = new_nick[:32]
            
            # Don't edit if nickname is already correct
            if member.display_name == new_nick:
                return
            
            # Debug print to see what we're trying to set
            print(f"Attempting to update: '{member.display_name}' -> '{new_nick}'")
            
            await member.edit(nick=new_nick)
            print(f"✅ Successfully updated nickname for {member.display_name}")
            
        except discord.Forbidden:
            print(f"❌ Permission denied: Cannot edit nickname for {member.display_name} (ID: {member.id})")
        except discord.HTTPException as e:
            print(f"❌ HTTP error editing nickname for {member.display_name}: {e}")
        except Exception as e:
            print(f"❌ Unexpected error editing nickname for {member.display_name}: {e}")

    def cog_unload(self):
        """Clean up when the cog is unloaded"""
        print("Unloading BoostCog...")
        if self.check_task:
            self.check_task.cancel()

# Modern discord.py setup function
async def setup(bot):
    """Modern discord.py setup function"""
    await bot.add_cog(BoostCog(bot))
    print("BoostCog loaded successfully!")

# Backwards compatibility for older discord.py versions
def setup(bot):
    """Legacy setup function"""
    bot.add_cog(BoostCog(bot))
    print("BoostCog loaded successfully (legacy mode)!")