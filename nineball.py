# -*- coding: utf-8 -*-
import discord
from discord.ext import commands, tasks
from discord import app_commands
import asyncio

class NineBall(commands.Cog, name="9ball"):
    def __init__(self, bot):
        self.bot = bot
        self.channel_owners = {}
        self.channel_banned = {}
        self.channel_timers = {}
        self.cleanup_empty_channels.start()

    def cog_unload(self):
        self.cleanup_empty_channels.cancel()

    def get_nineball_channel_count(self, guild):
        count = 0
        for channel in guild.voice_channels:
            if " 9ball" in channel.name:
                count += 1
        return count

    def get_available_superscript_number(self, guild, base_name):
        existing_channel_names = [channel.name for channel in guild.voice_channels]
        superscripts = ["¹", "²", "³", "⁴", "⁵", "⁶", "⁷", "⁸", "⁹", "¹⁰"]

        if f"{base_name} 9ball" not in existing_channel_names:
            return ""

        for superscript in superscripts:
            if f"{base_name} 9ball{superscript}" not in existing_channel_names:
                return superscript
        return None

    async def auto_delete_empty_channel(self, channel_id, delay=120):
        try:
            await asyncio.sleep(delay)
            channel = self.bot.get_channel(channel_id)
            if channel and len(channel.members) == 0:
                if channel_id in self.channel_owners:
                    del self.channel_owners[channel_id]
                if channel_id in self.channel_banned:
                    del self.channel_banned[channel_id]
                if channel_id in self.channel_timers:
                    del self.channel_timers[channel_id]

                await channel.delete(reason="Auto-deleted: No one joined within 2 minutes")
        except discord.NotFound:
            pass
        except discord.Forbidden:
            pass
        except Exception:
            pass

    @tasks.loop(minutes=5)
    async def cleanup_empty_channels(self):
        try:
            for guild in self.bot.guilds:
                channels_to_delete = []

                for channel in guild.voice_channels:
                    if channel.id in self.channel_owners and len(channel.members) == 0:
                        channels_to_delete.append(channel)

                for channel in channels_to_delete:
                    try:
                        self.channel_owners.pop(channel.id, None)
                        self.channel_banned.pop(channel.id, None)
                        if channel.id in self.channel_timers:
                            timer_task = self.channel_timers.pop(channel.id)
                            if not timer_task.done():
                                timer_task.cancel()

                        await channel.delete(reason="Periodic cleanup: Empty 9ball channel")
                    except (discord.NotFound, discord.Forbidden):
                        pass
                    except Exception:
                        pass
        except Exception:
            pass

    @cleanup_empty_channels.before_loop
    async def before_cleanup(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name='create9ball', description='Create a personal 9ball voice channel')
    @app_commands.describe(user_limit='Maximum number of users (1-99, default: 2)')
    async def create_nineball_channel(self, interaction: discord.Interaction, user_limit: int = 2):
        guild = interaction.guild
        member = interaction.user

        if user_limit < 1 or user_limit > 99:
            await interaction.response.send_message("User limit must be between 1 and 99!", ephemeral=True)
            return

        if self.get_nineball_channel_count(guild) >= 10:
            await interaction.response.send_message("Maximum number of 9ball channels (10) already exist! Please wait for some to be deleted.", ephemeral=True)
            return

        user_channels = [ch_id for ch_id, owner_id in self.channel_owners.items()
                        if owner_id == member.id and guild.get_channel(ch_id)]

        if user_channels:
            await interaction.response.send_message("You already own a 9ball channel! You can only own one at a time.", ephemeral=True)
            return

        base_name = member.display_name

        superscript = self.get_available_superscript_number(guild, base_name)
        if superscript is None:
            await interaction.response.send_message("Too many 9ball channels with your name exist! Please try again later.", ephemeral=True)
            return

        channel_name = f"{base_name} 9ball{superscript}"

        fweezer_category = discord.utils.get(guild.categories, name="Rwabbit talk")
        if not fweezer_category:
            try:
                fweezer_category = await guild.create_category("Rwabbit talk")
            except discord.Forbidden:
                await interaction.response.send_message("I don't have permission to create the Rwabbit talk category!", ephemeral=True)
                return

        # Get the "lunatic" role
        lunatic_role = discord.utils.get(guild.roles, name="lunatic")
        if not lunatic_role:
            await interaction.response.send_message("The 'lunatic' role does not exist!", ephemeral=True)
            return

        try:
            # Correct Overwrites:  Crucially, allow @everyone to connect.
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(
                    connect=False,  # Deny everyone to connect
                    send_messages=False,
                    read_messages=False,
                    view_channel=False # Ensure everyone can't see the channel
                ),
                lunatic_role: discord.PermissionOverwrite(
                    connect=True,  # Allow "lunatic" role to connect
                    view_channel=True # Allow "lunatic" role to see the channel
                ),
                member: discord.PermissionOverwrite(
                    connect=True,
                    manage_channels=True,
                    move_members=True,
                    mute_members=True,
                    deafen_members=True,
                    send_messages=False,
                    read_messages=False,
                    view_channel=True # Ensure the owner can see the channel
                )
            }

            new_channel = await guild.create_voice_channel(
                name=channel_name,
                user_limit=user_limit,
                category=fweezer_category,
                overwrites=overwrites,
                reason=f"9ball channel created by {member.display_name}"
            )

            # Store channel ownership
            self.channel_owners[new_channel.id] = member.id
            self.channel_banned[new_channel.id] = []

            # Start the 2-minute auto-delete timer
            timer_task = asyncio.create_task(self.auto_delete_empty_channel(new_channel.id))
            self.channel_timers[new_channel.id] = timer_task

            await interaction.response.send_message(
                f"Created your 9ball channel: **{channel_name}** (limit: {user_limit})!\n"
                f"Only users with the 'lunatic' role can see and join this channel.\n"
                f"You can use `/kick9ball` and `/ban9ball` to moderate it.\n"
                f"Use `/limit9ball` to change the user limit.\n"
                f"Text chat is disabled in 9ball channels.",
                ephemeral=True
            )

            if member.voice:
                await member.move_to(new_channel)

        except discord.Forbidden:
            await interaction.response.send_message("I don't have permission to create voice channels or set permissions!", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"An error occurred: {str(e)}", ephemeral=True)

    @app_commands.command(name='kick9ball', description='Kick a user from your 9ball channel')
    @app_commands.describe(member='The user to kick from your channel')
    async def kick_from_nineball(self, interaction: discord.Interaction, member: discord.Member):
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message("You need to be in a voice channel to use this command!", ephemeral=True)
            return

        channel = interaction.user.voice.channel

        if self.channel_owners.get(channel.id) != interaction.user.id:
            await interaction.response.send_message("You can only kick users from your own 9ball channel!", ephemeral=True)
            return

        if not member.voice or member.voice.channel != channel:
            await interaction.response.send_message(f"{member.display_name} is not in your channel!", ephemeral=True)
            return

        if member.id == interaction.user.id:
            await interaction.response.send_message("You can't kick yourself!", ephemeral=True)
            return

        try:
            await member.move_to(None)
            await interaction.response.send_message(f"Kicked {member.display_name} from the channel!", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("I don't have permission to move that user!", ephemeral=True)

    @app_commands.command(name='ban9ball', description='Ban a user from your 9ball channel')
    @app_commands.describe(member='The user to ban from your channel')
    async def ban_from_nineball(self, interaction: discord.Interaction, member: discord.Member):
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message("You need to be in a voice channel to use this command!", ephemeral=True)
            return

        channel = interaction.user.voice.channel

        if self.channel_owners.get(channel.id) != interaction.user.id:
            await interaction.response.send_message("You can only ban users from your own 9ball channel!", ephemeral=True)
            return

        if member.id == interaction.user.id:
            await interaction.response.send_message("You can't ban yourself!", ephemeral=True)
            return

        if channel.id not in self.channel_banned:
            self.channel_banned[channel.id] = []

        if member.id in self.channel_banned[channel.id]:
            await interaction.response.send_message(f"{member.display_name} is already banned from this channel!", ephemeral=True)
            return

        self.channel_banned[channel.id].append(member.id)

        await channel.set_permissions(member, connect=False, reason=f"Banned by {interaction.user.display_name}")

        if member.voice and member.voice.channel == channel:
            try:
                await member.move_to(None)
            except discord.Forbidden:
                pass

        await interaction.response.send_message(f"Banned {member.display_name} from the channel!", ephemeral=True)

    @app_commands.command(name='rename9ball', description='Rename your 9ball channel')
    @app_commands.describe(new_name='New name for your 9ball channel')
    async def rename_nineball(self, interaction: discord.Interaction, new_name: str):
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message("You need to be in a voice channel to use this command!", ephemeral=True)
            return

        channel = interaction.user.voice.channel

        if self.channel_owners.get(channel.id) != interaction.user.id:
            await interaction.response.send_message("You can only rename your own 9ball channel!", ephemeral=True)
            return

        if len(new_name) > 90:
            await interaction.response.send_message("New name is too long! Please use 90 characters or fewer.", ephemeral=True)
            return

        try:
            await channel.edit(name=new_name, reason=f"Renamed by {interaction.user.display_name}")
            await interaction.response.send_message(f"Channel renamed to **{new_name}**!", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("I don't have permission to rename this channel!", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"An error occurred: {str(e)}", ephemeral=True)

    @app_commands.command(name='unban9ball', description='Unban a user from your 9ball channel')
    @app_commands.describe(member='The user to unban from your channel')
    async def unban_from_nineball(self, interaction: discord.Interaction, member: discord.Member):
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message("You need to be in a voice channel to use this command!", ephemeral=True)
            return

        channel = interaction.user.voice.channel

        if self.channel_owners.get(channel.id) != interaction.user.id:
            await interaction.response.send_message("You can only unban users from your own 9ball channel!", ephemeral=True)
            return

        if channel.id not in self.channel_banned or member.id not in self.channel_banned[channel.id]:
            await interaction.response.send_message(f"{member.display_name} is not banned from this channel!", ephemeral=True)
            return

        self.channel_banned[channel.id].remove(member.id)

        await channel.set_permissions(member,
                                    connect=True,
                                    send_messages=False,
                                    read_messages=False,
                                    view_channel=True,
                                    reason=f"Unbanned by {interaction.user.display_name}")

        await interaction.response.send_message(f"Unbanned {member.display_name} from the channel!", ephemeral=True)

    @app_commands.command(name='limit9ball', description='Change the user limit of your 9ball channel')
    @app_commands.describe(new_limit='New user limit (1-99)')
    async def change_nineball_limit(self, interaction: discord.Interaction, new_limit: int):
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message("You need to be in a voice channel to use this command!", ephemeral=True)
            return

        channel = interaction.user.voice.channel

        if self.channel_owners.get(channel.id) != interaction.user.id:
            await interaction.response.send_message("You can only change the limit of your own 9ball channel!", ephemeral=True)
            return

        if new_limit < 1 or new_limit > 99:
            await interaction.response.send_message("User limit must be between 1 and 99!", ephemeral=True)
            return

        try:
            await channel.edit(user_limit=new_limit, reason=f"Limit changed by {interaction.user.display_name}")
            await interaction.response.send_message(f"Changed channel limit to {new_limit} users!", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("I don't have permission to edit this channel!", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"An error occurred: {str(e)}", ephemeral=True)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):

        if (after.channel is not None and
            after.channel.id in self.channel_owners and
            after.channel.id in self.channel_timers):

            timer_task = self.channel_timers[after.channel.id]
            if not timer_task.done():
                timer_task.cancel()
            del self.channel_timers[after.channel.id]

        if before.channel is not None:
            if before.channel.id in self.channel_owners and len(before.channel.members) == 0:
                try:
                    del self.channel_owners[before.channel.id]
                    if before.channel.id in self.channel_banned:
                        del self.channel_banned[before.channel.id]
                    if before.channel.id in self.channel_timers:
                        timer_task = self.channel_timers[before.channel.id]
                        if not timer_task.done():
                            timer_task.cancel()
                        del self.channel_timers[before.channel.id]

                    await before.channel.delete(reason="Empty 9ball channel cleanup")
                except discord.Forbidden:
                    pass
                except discord.NotFound:
                    pass

        if (after.channel is not None and
            after.channel.id in self.channel_banned and
            member.id in self.channel_banned[after.channel.id]):

            try:
                await member.move_to(None)
                try:
                    await member.send(f"You are banned from the channel **{after.channel.name}**.")
                except discord.Forbidden:
                    pass
            except discord.Forbidden:
                pass

async def setup(bot):
    await bot.add_cog(NineBall(bot)) 
