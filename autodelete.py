import discord
import asyncio
import json
from discord.ext import commands, tasks
from collections import defaultdict
from typing import Optional
from datetime import datetime, timezone, timedelta

def has_i_role():
    async def predicate(ctx):
        return discord.utils.get(ctx.author.roles, name="I") is not None
    return commands.check(predicate)

class AutoDelete(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.watchdog.start()
        self.config = {}
        self.deletion_queues = defaultdict(list)  # channel_id: list[discord.Message]
        self.queue_task = self.process_queues.start()

        try:
            with open("autodelete.json", "r") as f:
                self.config = json.load(f)
        except FileNotFoundError:
            self.config = {}

    def cog_unload(self):
        self.queue_task.cancel()

    async def save_config(self):
        with open("autodelete.json", "w") as f:
            json.dump(self.config, f)
            
    @commands.Cog.listener()
    async def on_ready(self):
        if not self.process_queues.is_running():
            self.process_queues.start()
            print("[AutoDelete] Restarted process_queues loop on ready")


    @commands.command()
    @has_i_role()
    async def autodelete(self, ctx, limit: int, time: int, unit: str):
        """Sets an autodelete limit and timer for chat, e.g., ~autodelete 50 5 hours"""
        channel = ctx.channel
        if unit == "minutes":
            time *= 60
        elif unit == "hours":
            time *= 3600

        self.config[str(channel.id)] = {"limit": limit, "time": time}
        await self.save_config()
        await ctx.send(f"🗑️ Auto delete set to delete messages after {limit} messages or {time} seconds in {channel.mention}")

    @commands.command()
    @commands.has_permissions(manage_messages=True)
    async def clear(self, ctx, amount: Optional[int] = None):
        """Clears the given amount of messages in chat, e.g., ~clear 20"""
        if amount is None:
            async for message in ctx.channel.history(limit=None):
                if message.id == ctx.message.id:
                    break
                await message.delete()
            return

        amount = min(amount, 100)
        messages = []
        async for message in ctx.channel.history(limit=amount):
            messages.append(message)

        await ctx.channel.delete_messages(messages)

    @commands.command()
    @commands.has_permissions(manage_messages=True)
    async def clearold(self, ctx, amount: Optional[int] = None):
        """Clears the given amount of **oldest** messages in chat, e.g., ~clearold 20"""
        if amount is None:
            async for message in ctx.channel.history(limit=None, oldest_first=True):
                if message.id == ctx.message.id:
                    break
                await message.delete()
                await asyncio.sleep(1.1)
        else:
            amount = min(amount, 100)
            messages = []
            async for message in ctx.channel.history(limit=1000, oldest_first=True):
                if message.id == ctx.message.id or message.pinned:
                    continue
                messages.append(message)
                if len(messages) >= amount:
                    break
            for msg in messages:
                await msg.delete()
                await asyncio.sleep(1.1)

        await ctx.message.delete()

    @commands.Cog.listener()
    @commands.has_permissions(manage_messages=True)
    async def on_message(self, message):
        try:
            if message.author.bot:
                return

            config = self.config.get(str(message.channel.id))
            if not config:
                return

            limit = config["limit"]
            messages = []

            async for msg in message.channel.history(limit=limit):
                if not msg.pinned:
                    messages.append(msg)

            if len(messages) >= limit:
                self.deletion_queues[message.channel.id].append(messages[-1])
        except Exception as e:
            print(f"[AutoDelete] Error in on_message: {e}")

           
    @commands.command()
    @commands.has_permissions(manage_messages=True)
    async def autodeletestatus(self, ctx):
        """Check if the autodelete loop is running"""
        running = self.process_queues.is_running()
        await ctx.send(f"🟢 AutoDelete loop running: `{running}`")
        
    @tasks.loop(minutes=5)
    async def watchdog(self):
        if not self.process_queues.is_running():
            try:
                self.process_queues.start()
                print("[AutoDelete] Watchdog restarted process_queues loop")
            except RuntimeError:
                # Already running
                pass

    @tasks.loop(seconds=10)
    async def process_queues(self):
        try:
            for channel_id, queue in list(self.deletion_queues.items()):
                if not queue:
                    continue

                channel = self.bot.get_channel(channel_id)
                if channel is None:
                    continue

                messages_to_delete = []
                while queue and len(messages_to_delete) < 100:
                    msg = queue.pop(0)
                    if (datetime.now(timezone.utc) - msg.created_at) < timedelta(days=14):
                        messages_to_delete.append(msg)

                if messages_to_delete:
                    try:
                        await channel.delete_messages(messages_to_delete)
                    except discord.HTTPException as e:
                        print(f"[AutoDelete] Bulk delete failed: {e}")
                        for msg in messages_to_delete:
                            try:
                                await msg.delete()
                                await asyncio.sleep(1.1)
                            except Exception as e:
                                print(f"[AutoDelete] Failed individual delete: {e}")
        except Exception as e:
            print(f"[AutoDelete] Error in process_queues loop: {e}")


def setup(bot):
    bot.add_cog(AutoDelete(bot))
