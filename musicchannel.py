import discord
from discord.ext import commands
from discord import app_commands
import yt_dlp
import asyncio
from urllib.parse import urlparse
import re
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Suppress noise about console usage from errors
yt_dlp.utils.bug_reports_message = lambda: ''

ytdl_format_options = {
    'format': 'bestaudio/best',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0',
    # YouTube specific options
    'extract_flat': False,
    'writethumbnail': False,
    'writeinfojson': False,
    'playlistend': 1,
    # Additional options for better compatibility
    'age_limit': None,
    'cookiefile': None,
    'extractor_retries': 3,
    'fragment_retries': 3,
    'skip_unavailable_fragments': True,
}

ffmpeg_options = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn',
}

ytdl = yt_dlp.YoutubeDL(ytdl_format_options)

class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('url')
        self.duration = data.get('duration')
        self.uploader = data.get('uploader')

    @classmethod
    async def create_source(cls, search, *, loop=None, stream=False):
        loop = loop or asyncio.get_event_loop()
        
        # Check if it's a URL or search term
        if not re.match(r'https?://', search):
            search = f"ytsearch:{search}"
        
        # Create a new YoutubeDL instance for each request to avoid threading issues
        ytdl_instance = yt_dlp.YoutubeDL(ytdl_format_options)
        
        try:
            # Completely isolate the extraction function
            def extract_info():
                try:
                    logger.info(f"Extracting info for: {search}")
                    result = ytdl_instance.extract_info(search, download=not stream)
                    logger.info(f"Successfully extracted info")
                    return result
                except Exception as e:
                    logger.error(f"Error in extract_info: {str(e)}")
                    raise e
            
            # Extract info in executor to avoid blocking
            data = await loop.run_in_executor(None, extract_info)
            
            if 'entries' in data and data['entries']:
                # Take first item from a playlist/search results
                data = data['entries'][0]
                logger.info(f"Selected first entry: {data.get('title', 'Unknown')}")
            
            if data is None:
                raise commands.CommandError("Could not find any audio to play")
            
            # Log the data for debugging
            logger.info(f"Title: {data.get('title')}")
            logger.info(f"URL: {data.get('url')}")
            logger.info(f"Extractor: {data.get('extractor')}")
            
            # Use the URL for streaming, filename for downloaded files
            if stream:
                url = data.get('url')
                if not url:
                    # Try alternative URL fields
                    url = data.get('webpage_url') or data.get('original_url')
                    if not url:
                        raise commands.CommandError("Could not get streaming URL")
                
                logger.info(f"Using stream URL: {url[:100]}...")
                
                # Create FFmpeg source with error handling
                try:
                    source = discord.FFmpegPCMAudio(
                        url,
                        before_options=ffmpeg_options['before_options'],
                        options=ffmpeg_options['options']
                    )
                    logger.info("Created FFmpeg source with full options")
                except Exception as ffmpeg_error:
                    # Fallback without before_options if there's an issue
                    logger.warning(f"FFmpeg before_options failed, trying without: {ffmpeg_error}")
                    try:
                        source = discord.FFmpegPCMAudio(
                            url,
                            options=ffmpeg_options['options']
                        )
                        logger.info("Created FFmpeg source with basic options")
                    except Exception as fallback_error:
                        # Final fallback - basic FFmpeg source
                        logger.warning(f"FFmpeg options failed, using basic source: {fallback_error}")
                        source = discord.FFmpegPCMAudio(url)
                        logger.info("Created basic FFmpeg source")
            else:
                filename = ytdl_instance.prepare_filename(data)
                logger.info(f"Using downloaded file: {filename}")
                try:
                    source = discord.FFmpegPCMAudio(
                        filename,
                        before_options=ffmpeg_options['before_options'],
                        options=ffmpeg_options['options']
                    )
                except Exception as ffmpeg_error:
                    logger.warning(f"FFmpeg options failed for file, using basic source: {ffmpeg_error}")
                    source = discord.FFmpegPCMAudio(filename)
            
            return cls(source, data=data)
            
        except yt_dlp.utils.DownloadError as e:
            logger.error(f"yt-dlp download error: {str(e)}")
            raise commands.CommandError(f"Could not download audio: {str(e)}")
        except yt_dlp.utils.ExtractorError as e:
            logger.error(f"yt-dlp extractor error: {str(e)}")
            raise commands.CommandError(f"Could not extract audio info: {str(e)}")
        except Exception as e:
            logger.error(f"Error in create_source: {str(e)}")
            raise commands.CommandError(f"Error processing audio: {str(e)}")
        finally:
            # Clean up the ytdl instance
            try:
                ytdl_instance.close()
            except:
                pass

class MusicQueue:
    def __init__(self):
        self.queue = []
        self.current = None
        
    def add(self, item):
        self.queue.append(item)
        
    def next(self):
        if self.queue:
            self.current = self.queue.pop(0)
            return self.current
        return None
        
    def clear(self):
        self.queue.clear()
        self.current = None

class MusicChannelCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.queues = {}  # Guild ID -> MusicQueue
        
    def get_queue(self, guild_id):
        if guild_id not in self.queues:
            self.queues[guild_id] = MusicQueue()
        return self.queues[guild_id]

    async def connect_with_retry(self, channel, max_retries=3):
        """Connect to voice channel with retry logic"""
        for attempt in range(max_retries):
            try:
                # Clean up any existing connection first
                if channel.guild.voice_client:
                    logger.info(f"Disconnecting existing voice client before reconnecting")
                    await channel.guild.voice_client.disconnect(force=True)
                    await asyncio.sleep(2)  # Longer pause to ensure cleanup
                
                logger.info(f"Attempting to connect to {channel.name} (attempt {attempt + 1}/{max_retries})")
                voice_client = await channel.connect(timeout=15.0, reconnect=True)
                logger.info(f"Successfully connected to {channel.name} on attempt {attempt + 1}")
                return voice_client
                
            except discord.errors.ConnectionClosed as e:
                logger.warning(f"Connection attempt {attempt + 1} failed with code {e.code}: {e}")
                if e.code == 4006:
                    logger.info("Trying to switch voice region may help with code 4006")
                elif e.code == 4014:
                    logger.error("Bot lacks permission to connect to this channel")
                    raise  # Don't retry permission errors
                
                if attempt < max_retries - 1:
                    wait_time = (2 ** attempt) + 1
                    logger.info(f"Waiting {wait_time} seconds before retry...")
                    await asyncio.sleep(wait_time)
                else:
                    raise
            except asyncio.TimeoutError:
                logger.warning(f"Connection attempt {attempt + 1} timed out")
                if attempt < max_retries - 1:
                    await asyncio.sleep(3)
                else:
                    raise commands.CommandError("Connection timed out after multiple attempts")
            except Exception as e:
                logger.error(f"Unexpected error during connection attempt {attempt + 1}: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                else:
                    raise

    @commands.Cog.listener()
    async def on_message(self, message):
        # Keep original message filtering logic
        if message.channel.name != "music":
            if message.content.startswith("<@1073858663585947659>"):
                await message.delete()
        else:
            if message.content.startswith("<@1073858663585947659>"):
                if "https" not in message.content:
                    await message.delete()

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        """Handle voice state updates to manage bot disconnection"""
        if member == self.bot.user:
            # Bot's voice state changed
            if before.channel and not after.channel:
                logger.info(f"Bot was disconnected from {before.channel.name}")
                # Clear the queue when bot gets disconnected
                if before.channel.guild.id in self.queues:
                    self.queues[before.channel.guild.id].clear()
            return
            
        # Check if bot is alone in voice channel
        voice_client = member.guild.voice_client
        if voice_client and voice_client.channel:
            # Count non-bot members in the channel
            members = [m for m in voice_client.channel.members if not m.bot]
            if len(members) == 0:
                logger.info(f"Bot is alone in {voice_client.channel.name}, starting disconnect timer")
                # Bot is alone, disconnect after a delay
                await asyncio.sleep(300)  # Wait 5 minutes
                if voice_client.is_connected():
                    members = [m for m in voice_client.channel.members if not m.bot]
                    if len(members) == 0:  # Still alone
                        logger.info(f"Bot still alone after 5 minutes, disconnecting from {voice_client.channel.name}")
                        queue = self.get_queue(member.guild.id)
                        queue.clear()
                        await voice_client.disconnect()

    @app_commands.command(name="join", description="Join your voice channel")
    async def join(self, interaction: discord.Interaction):
        """Join the user's voice channel"""
        if not interaction.user.voice:
            await interaction.response.send_message("❌ You need to be in a voice channel!", ephemeral=True)
            return
            
        channel = interaction.user.voice.channel
        
        try:
            if interaction.guild.voice_client:
                if interaction.guild.voice_client.channel == channel:
                    await interaction.response.send_message("✅ Already connected to your voice channel!", ephemeral=True)
                    return
                else:
                    await interaction.guild.voice_client.move_to(channel)
            else:
                await interaction.response.defer()
                await self.connect_with_retry(channel)
                
            await interaction.followup.send(f"🎵 Joined **{channel.name}**!")
            
        except discord.errors.ConnectionClosed as e:
            error_msg = f"❌ Failed to connect to voice channel (Error {e.code}). "
            if e.code == 4006:
                error_msg += "Try switching your server's voice region in Server Settings."
            elif e.code == 4014:
                error_msg += "The bot doesn't have permission to connect to this channel."
            
            if interaction.response.is_done():
                await interaction.followup.send(error_msg, ephemeral=True)
            else:
                await interaction.response.send_message(error_msg, ephemeral=True)
                
        except Exception as e:
            error_msg = f"❌ Unexpected error connecting to voice channel: {str(e)}"
            if interaction.response.is_done():
                await interaction.followup.send(error_msg, ephemeral=True)
            else:
                await interaction.response.send_message(error_msg, ephemeral=True)

    @app_commands.command(name="leave", description="Leave the voice channel")
    async def leave(self, interaction: discord.Interaction):
        """Leave the voice channel and clear queue"""
        if not interaction.guild.voice_client:
            await interaction.response.send_message("❌ I'm not connected to a voice channel!", ephemeral=True)
            return
            
        queue = self.get_queue(interaction.guild.id)
        queue.clear()
        
        try:
            await interaction.guild.voice_client.disconnect()
            await interaction.response.send_message("👋 Left the voice channel and cleared the queue!")
        except Exception as e:
            await interaction.response.send_message(f"❌ Error leaving voice channel: {str(e)}", ephemeral=True)

    @app_commands.command(name="play", description="Play music from YouTube or other sources")
    @app_commands.describe(query="YouTube URL, song name, or search term")
    async def play(self, interaction: discord.Interaction, query: str):
        """Play music from various sources"""
        # Check if user is in voice channel
        if not interaction.user.voice:
            await interaction.response.send_message("❌ You need to be in a voice channel to play music!", ephemeral=True)
            return
            
        await interaction.response.defer()
        
        # Join voice channel if not connected
        if not interaction.guild.voice_client:
            try:
                await self.connect_with_retry(interaction.user.voice.channel)
            except Exception as e:
                await interaction.followup.send(f"❌ Failed to connect to voice channel: {str(e)}")
                return
        
        try:
            # Log the query for debugging
            logger.info(f"Processing play request for: {query}")
            
            # Create audio source
            source = await YTDLSource.create_source(query, loop=self.bot.loop, stream=True)
            queue = self.get_queue(interaction.guild.id)
            
            # Add to queue
            queue.add(source)
            
            # If nothing is playing, start playing
            if not interaction.guild.voice_client.is_playing():
                await self._play_next(interaction.guild)
                embed = discord.Embed(
                    title="🎵 Now Playing",
                    description=f"**{source.title}**",
                    color=0x00ff00
                )
                if source.uploader:
                    embed.add_field(name="Channel", value=source.uploader, inline=True)
                if source.duration:
                    mins, secs = divmod(source.duration, 60)
                    embed.add_field(name="Duration", value=f"{mins}:{secs:02d}", inline=True)
            else:
                embed = discord.Embed(
                    title="➕ Added to Queue",
                    description=f"**{source.title}**",
                    color=0x0099ff
                )
                embed.add_field(name="Position", value=f"{len(queue.queue)}", inline=True)
                
            await interaction.followup.send(embed=embed)
            
        except commands.CommandError as e:
            # These are our custom errors with user-friendly messages
            await interaction.followup.send(f"❌ {str(e)}")
        except Exception as e:
            # Unexpected errors
            logger.error(f"Unexpected error in play command: {str(e)}")
            await interaction.followup.send(f"❌ An unexpected error occurred while trying to play music. Please try again or contact support.")

    async def _play_next(self, guild):
        """Play the next song in queue"""
        queue = self.get_queue(guild.id)
        source = queue.next()
        
        if source and guild.voice_client and guild.voice_client.is_connected():
            try:
                def after_playing(error):
                    if error:
                        logger.error(f'Player error: {error}')
                    # Schedule the next song
                    coro = self._song_finished(guild, error)
                    future = asyncio.run_coroutine_threadsafe(coro, self.bot.loop)
                    try:
                        future.result()  # Wait for completion
                    except Exception as e:
                        logger.error(f"Error in after_playing callback: {e}")
                
                guild.voice_client.play(source, after=after_playing)
                logger.info(f"Started playing: {source.title}")
            except Exception as e:
                logger.error(f"Error starting playback: {e}")
                # Try to play next song if this one failed
                if queue.queue:
                    await asyncio.sleep(1)
                    await self._play_next(guild)
        elif not guild.voice_client or not guild.voice_client.is_connected():
            logger.warning("Voice client disconnected, clearing queue")
            queue.clear()

    async def _song_finished(self, guild, error):
        """Called when a song finishes playing"""
        if error:
            logger.error(f'Player error: {error}')
            
        queue = self.get_queue(guild.id)
        if queue.queue and guild.voice_client and guild.voice_client.is_connected():
            await self._play_next(guild)

    @app_commands.command(name="pause", description="Pause the current song")
    async def pause(self, interaction: discord.Interaction):
        """Pause the current song"""
        if interaction.guild.voice_client and interaction.guild.voice_client.is_playing():
            interaction.guild.voice_client.pause()
            await interaction.response.send_message("⏸️ Paused the music!")
        else:
            await interaction.response.send_message("❌ Nothing is currently playing!", ephemeral=True)

    @app_commands.command(name="resume", description="Resume the paused song")
    async def resume(self, interaction: discord.Interaction):
        """Resume the paused song"""
        if interaction.guild.voice_client and interaction.guild.voice_client.is_paused():
            interaction.guild.voice_client.resume()
            await interaction.response.send_message("▶️ Resumed the music!")
        else:
            await interaction.response.send_message("❌ Music is not paused!", ephemeral=True)

    @app_commands.command(name="stop", description="Stop the music and clear queue")
    async def stop(self, interaction: discord.Interaction):
        """Stop the music and clear the queue"""
        if interaction.guild.voice_client:
            queue = self.get_queue(interaction.guild.id)
            queue.clear()
            interaction.guild.voice_client.stop()
            await interaction.response.send_message("⏹️ Stopped the music and cleared the queue!")
        else:
            await interaction.response.send_message("❌ Nothing is currently playing!", ephemeral=True)

    @app_commands.command(name="skip", description="Skip the current song")
    async def skip(self, interaction: discord.Interaction):
        """Skip the current song"""
        if interaction.guild.voice_client and interaction.guild.voice_client.is_playing():
            interaction.guild.voice_client.stop()  # This will trigger _song_finished
            await interaction.response.send_message("⏭️ Skipped the current song!")
        else:
            await interaction.response.send_message("❌ Nothing is currently playing!", ephemeral=True)

    @app_commands.command(name="queue", description="Show the current music queue")
    async def show_queue(self, interaction: discord.Interaction):
        """Display the current music queue"""
        queue = self.get_queue(interaction.guild.id)
        
        if not queue.current and not queue.queue:
            await interaction.response.send_message("📭 The queue is empty!", ephemeral=True)
            return
            
        embed = discord.Embed(title="📋 Music Queue", color=0x0099ff)
        
        if queue.current:
            embed.add_field(name="🎵 Now Playing", value=queue.current.title, inline=False)
            
        if queue.queue:
            queue_list = []
            for i, song in enumerate(queue.queue[:10], 1):  # Show first 10 songs
                queue_list.append(f"{i}. {song.title}")
            
            embed.add_field(name="⏭️ Up Next", value="\n".join(queue_list), inline=False)
            
            if len(queue.queue) > 10:
                embed.add_field(name="", value=f"...and {len(queue.queue) - 10} more songs", inline=False)
                
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="volume", description="Set the music volume (0-100)")
    @app_commands.describe(volume="Volume level from 0 to 100")
    async def volume(self, interaction: discord.Interaction, volume: int):
        """Change the volume of the music"""
        if not 0 <= volume <= 100:
            await interaction.response.send_message("❌ Volume must be between 0 and 100!", ephemeral=True)
            return
            
        if interaction.guild.voice_client and hasattr(interaction.guild.voice_client.source, 'volume'):
            interaction.guild.voice_client.source.volume = volume / 100
            await interaction.response.send_message(f"🔊 Set volume to {volume}%!")
        else:
            await interaction.response.send_message("❌ Nothing is currently playing!", ephemeral=True)

    @app_commands.command(name="nowplaying", description="Show information about the current song")
    async def now_playing(self, interaction: discord.Interaction):
        """Show information about the currently playing song"""
        queue = self.get_queue(interaction.guild.id)
        
        if not queue.current:
            await interaction.response.send_message("❌ Nothing is currently playing!", ephemeral=True)
            return
            
        embed = discord.Embed(
            title="🎵 Now Playing",
            description=f"**{queue.current.title}**",
            color=0x00ff00
        )
        
        if queue.current.uploader:
            embed.add_field(name="Channel", value=queue.current.uploader, inline=True)
            
        if queue.current.duration:
            mins, secs = divmod(queue.current.duration, 60)
            embed.add_field(name="Duration", value=f"{mins}:{secs:02d}", inline=True)
            
        await interaction.response.send_message(embed=embed)

async def setup(bot):
    await bot.add_cog(MusicChannelCog(bot))