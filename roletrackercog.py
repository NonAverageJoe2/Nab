import discord
import json
from discord.ext import commands

class RoleTracker(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.roles_by_user = {}

        # Check for tracked user on startup
        bot.loop.create_task(self.give_special_role_to_existing_user())

    async def give_special_role_to_existing_user(self):
        await self.bot.wait_until_ready()
        for guild in self.bot.guilds:
            member = guild.get_member(1387430259498156103)
            if member:
                role = discord.utils.get(guild.roles, name="冰淇淋")
                if role and role not in member.roles:
                    try:
                        await member.add_roles(role)
                        print(f"Gave 冰淇淋 role to {member} (already in server)")
                    except discord.Forbidden:
                        print(f"Missing permissions to give 冰淇淋 role to {member}")
                    except Exception as e:
                        print(f"Error giving role to {member}: {e}")

    def load_user_roles(self, user_id):
        try:
            with open("user_roles.json", "r") as f:
                self.roles_by_user = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self.roles_by_user = {}
        return self.roles_by_user.get(str(user_id), [])

    async def save_user_roles(self, member):
        self.roles_by_user[str(member.id)] = [role.id for role in member.roles]
        with open("user_roles.json", "w") as f:
            json.dump(self.roles_by_user, f)

    async def add_roles_to_user(self, member):
        stored_role_ids = self.roles_by_user.get(str(member.id))
        if stored_role_ids is None:
            return

        guild = member.guild
        roles = [role for role in guild.roles if role.id in stored_role_ids]

        for role in roles:
            if role not in member.roles:
                try:
                    await member.add_roles(role)
                except discord.Forbidden:
                    print(f"Error adding role {role} to user {member}")
                except discord.NotFound:
                    print(f"Role {role} not found, removing from stored roles")
                    self.roles_by_user[str(member.id)].remove(role.id)

    @commands.Cog.listener()
    async def on_member_join(self, member):
        # Restore saved roles
        await self.add_roles_to_user(member)

        # Special user gets the 冰淇淋 role
        if member.id == 1387430259498156103:
            role = discord.utils.get(member.guild.roles, name="冰淇淋")
            if role:
                try:
                    await member.add_roles(role)
                    print(f"Gave 冰淇淋 role to {member}")
                except discord.Forbidden:
                    print(f"Missing permissions to give 冰淇淋 role to {member}")
            else:
                print("Role 冰淇淋 not found in guild.")

        # Low quality message
        if discord.utils.get(member.guild.roles, name="low quality") in member.roles:
            channel = discord.utils.get(member.guild.text_channels, name="lq")
            if channel:
                await channel.send(f"{member.mention} Lmao you aren't going anywhere")
            else:
                try:
                    await member.send("Lmao you aren't going anywhere")
                except discord.Forbidden:
                    pass

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        await self.save_user_roles(member)

def setup(bot):
    bot.add_cog(RoleTracker(bot))
