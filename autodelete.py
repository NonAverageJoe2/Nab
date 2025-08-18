import discord
import asyncio
import json
import contextlib
from discord.ext import commands, tasks
from collections import defaultdict, deque
from typing import Optional, Dict, Deque, List
from datetime import datetime, timezone, timedelta

# ==========================
# Helper: role-gated commands
# ==========================

def has_required_role():
    async def predicate(ctx: commands.Context):
        required_roles = {"I", "II", "III"}
        return any((r.name in required_roles) for r in getattr(ctx.author, "roles", []))
    return commands.check(predicate)


# ======================
# Core AutoDelete Cog
# ======================

class AutoDelete(commands.Cog):
    """Comprehensive auto-delete system supporting count- and time-based rules.

    Features
    --------
    - Per-channel config: limit (count) + age (seconds)
    - Queue-based enforcement for count (fast, low API usage)
    - Periodic sweeps for age-based deletions
    - Bulk delete with safe fallbacks for >14 day messages
    - Resilient across restarts (bootstraps last N messages into queues)
    - Admin commands to set, view, and remove rules
    """

    BULK_DELETE_LIMIT = 100
    BULK_AGE_LIMIT = timedelta(days=14)

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.config: Dict[str, Dict[str, int]] = {}
        # recent[channel_id] = deque([Message, ...])
        self.recent: Dict[int, Deque[discord.Message]] = defaultdict(deque)
        # pending[channel_id] = list([Message, ...]) slated for deletion
        self.pending: Dict[int, List[discord.Message]] = defaultdict(list)
        # locks per channel to avoid concurrent processing
        self.locks: Dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)

        self._config_path = "autodelete.json"
        self._bootstrapped = asyncio.Event()

        self._load_config()
        self.sweeper.start()

    # -----------------
    # Config persistence
    # -----------------
    def _load_config(self) -> None:
        try:
            with open(self._config_path, "r", encoding="utf-8") as fp:
                self.config = json.load(fp)
        except FileNotFoundError:
            self.config = {}
        except json.JSONDecodeError:
            # Recover from a broken file
            self.config = {}

    async def _save_config(self) -> None:
        with open(self._config_path, "w", encoding="utf-8") as fp:
            json.dump(self.config, fp, indent=2)

    # -----------------
    # Lifecycle hooks
    # -----------------
    @commands.Cog.listener()
    async def on_ready(self):
        # Bootstrap queues once at startup with recent history so count-based rules
        # work immediately even after restart.
        if not self._bootstrapped.is_set():
            await self._bootstrap_queues()
            self._bootstrapped.set()

    async def _bootstrap_queues(self):
        for chan_id_str, cfg in list(self.config.items()):
            chan_id = int(chan_id_str)
            channel = self.bot.get_channel(chan_id)
            if channel is None:
                # Try fetching in case it's not cached
                try:
                    channel = await self.bot.fetch_channel(chan_id)
                except Exception:
                    continue

            limit = max(int(cfg.get("limit", 0)), 0)
            if limit <= 0:
                continue

            # Pull a reasonable window so we can fill the deque without heavy scanning
            window = min(max(limit * 2, 100), 1000)
            buf: List[discord.Message] = []
            try:
                async for m in channel.history(limit=window, oldest_first=False):
                    if not m.pinned and not m.author.bot:
                        buf.append(m)
            except (discord.Forbidden, discord.HTTPException):
                continue

            # Keep only newest `limit` messages in the deque (left=oldest, right=newest)
            buf = list(reversed(buf))  # oldest -> newest
            dq: Deque[discord.Message] = deque(maxlen=limit)
            for m in buf:
                dq.append(m)
            self.recent[chan_id] = dq

            # Also stage any already-expired (age-based) messages for deletion
            age_seconds = int(cfg.get("time", 0))
            if age_seconds > 0:
                cutoff = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
                expired = [m for m in list(dq) if m.created_at < cutoff]
                if expired:
                    self.pending[chan_id].extend(expired)

    def cog_unload(self):
        self.sweeper.cancel()

    # -----------------
    # Command surface
    # -----------------
    @commands.guild_only()
    @commands.bot_has_permissions(manage_messages=True, read_message_history=True)
    @has_required_role()
    @commands.command(name="autodelete")
    async def cmd_autodelete(self, ctx: commands.Context, limit: Optional[int] = None,
                              time: Optional[int] = None, unit: Optional[str] = None):
        """Configure auto-delete for this channel.

        Usage:
          ~autodelete <limit> <time> <unit>
          ~autodelete off

        Examples:
          ~autodelete 50 5 minutes
          ~autodelete 200 2 hours
          ~autodelete off
        """
        ch_key = str(ctx.channel.id)

        if isinstance(limit, str) and limit.lower() == "off":
            self.config.pop(ch_key, None)
            self.recent.pop(ctx.channel.id, None)
            self.pending.pop(ctx.channel.id, None)
            await self._save_config()
            return await ctx.send(f"🛑 Auto-delete disabled in {ctx.channel.mention}")

        if limit is None or time is None:
            return await ctx.send("❓ Usage: `~autodelete <limit> <time> <seconds|minutes|hours>` or `~autodelete off`")

        if unit is None:
            unit = "seconds"

        try:
            limit = max(0, int(limit))
            seconds = int(time)
        except (TypeError, ValueError):
            return await ctx.send("⚠️ limit and time must be integers.")

        unit = unit.lower()
        if unit.startswith("min"):
            seconds *= 60
        elif unit.startswith("hour"):
            seconds *= 3600
        elif unit.startswith("sec"):
            pass
        else:
            return await ctx.send("⚠️ unit must be one of: seconds, minutes, hours.")

        self.config[ch_key] = {"limit": limit, "time": seconds}
        await self._save_config()

        # Reset local state for this channel
        self.recent.pop(ctx.channel.id, None)
        self.pending.pop(ctx.channel.id, None)

        await ctx.send(
            f"🗑️ Auto-delete enabled in {ctx.channel.mention}: keep last **{limit}** messages; delete messages older than **{seconds}s**."
        )

        # Bootstrap just this channel
        await self._bootstrap_single(ctx.channel.id)

    async def _bootstrap_single(self, channel_id: int):
        ch_key = str(channel_id)
        cfg = self.config.get(ch_key)
        if not cfg:
            return
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(channel_id)
            except Exception:
                return

        limit = max(int(cfg.get("limit", 0)), 0)
        if limit <= 0:
            return

        window = min(max(limit * 2, 100), 1000)
        buf: List[discord.Message] = []
        try:
            async for m in channel.history(limit=window, oldest_first=False):
                if not m.pinned and not m.author.bot:
                    buf.append(m)
        except (discord.Forbidden, discord.HTTPException):
            return

        buf = list(reversed(buf))
        dq: Deque[discord.Message] = deque(maxlen=limit)
        for m in buf:
            dq.append(m)
        self.recent[channel_id] = dq

    @commands.guild_only()
    @commands.bot_has_permissions(manage_messages=True, read_message_history=True)
    @has_required_role()
    @commands.command(name="autodeletestatus")
    async def cmd_autodelete_status(self, ctx: commands.Context):
        cfg = self.config.get(str(ctx.channel.id))
        if not cfg:
            return await ctx.send("ℹ️ Auto-delete is **off** in this channel.")

        dq = self.recent.get(ctx.channel.id)
        pend = self.pending.get(ctx.channel.id, [])
        await ctx.send(
            f"📊 Auto-delete in {ctx.channel.mention}: limit=`{cfg['limit']}`, age=`{cfg['time']}s`, "
            f"cached=`{len(dq) if dq else 0}`, pending=`{len(pend)}`"
        )

    @commands.guild_only()
    @commands.bot_has_permissions(manage_messages=True, read_message_history=True)
    @has_required_role()
    @commands.command(name="clear")
    async def cmd_clear(self, ctx: commands.Context, amount: Optional[int] = None):
        """Clear messages in this channel. If no amount, clears up to 100 (excluding pinned)."""
        if amount is None:
            amount = 100
        amount = max(1, min(int(amount), 1000))

        def _check(m: discord.Message):
            return not m.pinned

        try:
            deleted = await ctx.channel.purge(limit=amount + 1, check=_check)  # includes command
            await ctx.send(f"✅ Deleted {len(deleted)-1} messages.", delete_after=5)
        except discord.Forbidden:
            await ctx.send("❌ Missing permissions to manage messages here.")
        except discord.HTTPException as e:
            await ctx.send(f"⚠️ Purge failed: {e}")

    @commands.guild_only()
    @commands.bot_has_permissions(manage_messages=True, read_message_history=True)
    @has_required_role()
    @commands.command(name="clearold")
    async def cmd_clear_old(self, ctx: commands.Context, amount: Optional[int] = 20):
        """Clear the **oldest** messages (excluding pinned)."""
        amount = max(1, min(int(amount), 1000))
        msgs: List[discord.Message] = []
        async for m in ctx.channel.history(limit=2000, oldest_first=True):
            if not m.pinned:
                msgs.append(m)
                if len(msgs) >= amount:
                    break
        if not msgs:
            return await ctx.message.delete()
        try:
            await self._delete_chunk(ctx.channel, msgs)
        except Exception as e:
            await ctx.send(f"⚠️ clearold failed: {e}")
        finally:
            with contextlib.suppress(Exception):
                await ctx.message.delete()

    # -----------------
    # Message listener
    # -----------------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # Ignore DM / bot / webhooks
        if not message.guild or message.author.bot:
            return

        cfg = self.config.get(str(message.channel.id))
        if not cfg:
            return

        ch_id = message.channel.id
        dq = self.recent[ch_id]
        limit = max(int(cfg.get("limit", 0)), 0)
        if limit <= 0:
            return

        # Track message (skip pinned)
        if not message.pinned:
            dq.append(message)

        # If we have more than limit, schedule oldest overflow for deletion
        overflow = len(dq) - limit
        if overflow > 0:
            for _ in range(overflow):
                old = dq.popleft()
                # If the message got pinned later, skip deletion
                if getattr(old, "pinned", False):
                    continue
                self.pending[ch_id].append(old)

    # -----------------
    # Background sweeper
    # -----------------
    @tasks.loop(seconds=20)
    async def sweeper(self):
        now = datetime.now(timezone.utc)
        for ch_id_str, cfg in list(self.config.items()):
            ch_id = int(ch_id_str)
            lock = self.locks[ch_id]
            if lock.locked():
                continue

            async with lock:
                await self._sweep_channel(ch_id, cfg, now)

    @sweeper.before_loop
    async def _before_sweeper(self):
        await self.bot.wait_until_ready()

    async def _sweep_channel(self, channel_id: int, cfg: Dict[str, int], now: datetime):
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(channel_id)
            except Exception:
                return

        # 1) Age-based: move expired from recent -> pending
        age_seconds = int(cfg.get("time", 0))
        if age_seconds > 0:
            cutoff = now - timedelta(seconds=age_seconds)
            dq = self.recent[channel_id]
            while dq and dq[0].created_at < cutoff:
                m = dq.popleft()
                if not getattr(m, "pinned", False):
                    self.pending[channel_id].append(m)

        # 2) If pending is large, cap how many we process this pass
        pend = self.pending[channel_id]
        if not pend:
            return

        # Separate by age for bulk vs single deletes
        younger: List[discord.Message] = []
        older: List[discord.Message] = []
        for m in pend[:1000]:  # process up to 1000 per pass to avoid long blocks
            if (now - m.created_at) < self.BULK_AGE_LIMIT:
                younger.append(m)
            else:
                older.append(m)

        # Helper: remove from pending list after attempt
        def _remove_from_pending(done: List[discord.Message]):
            done_ids = {d.id for d in done}
            self.pending[channel_id] = [x for x in self.pending[channel_id] if x.id not in done_ids]

        # Bulk delete newer ones in chunks of <=100
        # Note: Some channels (e.g., threads) support delete_messages; if not, we fall back.
        for i in range(0, len(younger), self.BULK_DELETE_LIMIT):
            chunk = younger[i:i + self.BULK_DELETE_LIMIT]
            # Skip any that got pinned since queued
            chunk = [m for m in chunk if not getattr(m, "pinned", False)]
            if not chunk:
                _remove_from_pending(chunk)
                continue
            try:
                await self._delete_chunk(channel, chunk)
            except Exception:
                # Fall back to singles if bulk fails for this chunk
                for m in chunk:
                    await self._delete_single(m)
            finally:
                _remove_from_pending(chunk)

        # Delete older-than-14-days individually
        for m in older:
            if getattr(m, "pinned", False):
                continue
            await self._delete_single(m)
        _remove_from_pending(older)

    # -----------------
    # Delete helpers
    # -----------------
    async def _delete_chunk(self, channel: discord.abc.Messageable, chunk: List[discord.Message]):
        # Some channel types may not support bulk delete; try and fall back if needed
        try:
            # Prefer raw IDs to reduce payload size
            ids = [m.id for m in chunk]
            # discord.py accepts either messages or Snowflakes
            await channel.delete_messages(ids)
        except AttributeError:
            # Fallback to purge on TextChannel / Thread
            if hasattr(channel, "purge"):
                ids_set = {m.id for m in chunk}
                await channel.purge(limit=len(chunk) + 50, check=lambda x: x.id in ids_set)
            else:
                # Last resort: singles
                for m in chunk:
                    await self._delete_single(m)
        except discord.HTTPException as e:
            # If bulk delete fails (e.g., because of scattered >14d), do singles
            if "14 days" in str(e).lower():
                for m in chunk:
                    await self._delete_single(m)
            else:
                # Re-raise to let caller decide
                raise

    async def _delete_single(self, message: discord.Message):
        try:
            await message.delete()
            # Optimized sleep for Discord's rate limit (5 deletions per 5 seconds per channel)
            await asyncio.sleep(1.0)
        except (discord.NotFound, discord.Forbidden):
            return
        except discord.HTTPException:
            # Mild backoff if we hit a rate-limit edge
            await asyncio.sleep(2.5)


# --------------
# Cog setup hook
# --------------
async def setup(bot: commands.Bot):  # discord.py 2.x style
    await bot.add_cog(AutoDelete(bot))
