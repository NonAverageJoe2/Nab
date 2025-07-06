import discord
from discord.ext import commands
import asyncio
import random

class CaptchaCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.user_attempts = {}
        self.enabled = True  # Toggle CAPTCHA system

    @commands.command(name="captcha")
    @commands.has_permissions(administrator=True)
    async def toggle_captcha(self, ctx, mode: str):
        """Enable or disable CAPTCHA: !captcha on / !captcha off"""
        if mode.lower() == "on":
            self.enabled = True
            await ctx.send("✅ CAPTCHA system enabled.")
        elif mode.lower() == "off":
            self.enabled = False
            await ctx.send("⛔ CAPTCHA system disabled.")
        else:
            await ctx.send("Usage: `!captcha on` or `!captcha off`")

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if not self.enabled:
            return  # CAPTCHA is off

        try:
            challenge, answer, mode = self.generate_challenge()

            # Step 1: Try DM Verification
            try:
                dm = await member.create_dm()
                msg = await dm.send(f"**Verification Challenge**:\n{challenge}")

                def dm_check(m):
                    return m.channel == dm and m.author == member

                attempts = 0
                while attempts < 3:
                    try:
                        reply = await self.bot.wait_for("message", timeout=300, check=dm_check)
                        if reply.content.strip().lower() == answer:
                            await dm.send("✅ You passed the CAPTCHA. Welcome!")
                            return
                        else:
                            attempts += 1
                            await dm.send(f"❌ Incorrect. {3 - attempts} attempts remaining.")
                    except asyncio.TimeoutError:
                        break

                if attempts >= 3:
                    await dm.send("⛔ You failed the CAPTCHA and will be banned.")
                    await member.ban(reason="Failed CAPTCHA in DM")
                    return

            except (discord.Forbidden, discord.HTTPException):
                pass  # DM blocked or failed

            # Step 2: Fallback to purgatory
            purgatory = discord.utils.get(member.guild.text_channels, name="purgatory")
            if not purgatory:
                print("❌ 'purgatory' channel not found.")
                return

            await purgatory.set_permissions(member, read_messages=True, send_messages=True)

            prompt = await purgatory.send(f"{member.mention}\n{challenge}")
            if mode == "reaction":
                await prompt.add_reaction("✅")

            def text_check(m):
                return m.channel == purgatory and m.author == member

            def reaction_check(reaction, user):
                return user == member and reaction.message.id == prompt.id and str(reaction.emoji) == "✅"

            attempts = 0
            while attempts < 3:
                try:
                    if mode == "reaction":
                        _, user = await self.bot.wait_for("reaction_add", timeout=600.0, check=reaction_check)
                        await purgatory.send("✅ Verified! Welcome.")
                        await self.cleanup(member, purgatory)
                        return
                    else:
                        msg = await self.bot.wait_for("message", timeout=600.0, check=text_check)
                        await msg.delete()
                        if msg.content.strip().lower() == answer:
                            await purgatory.send("✅ Verified! Welcome.")
                            await self.cleanup(member, purgatory)
                            return
                        else:
                            attempts += 1
                            warn = await purgatory.send(f"❌ Incorrect. {3 - attempts} attempts remaining.")
                            await asyncio.sleep(3)
                            await warn.delete()
                except asyncio.TimeoutError:
                    break

            await purgatory.send("⛔ Verification failed. You will be banned.")
            await asyncio.sleep(2)
            await self.cleanup(member, purgatory)
            await member.ban(reason="Failed CAPTCHA in purgatory")

        except Exception as e:
            print(f"[CAPTCHA ERROR] {e}")

    def generate_challenge(self):
        challenges = [
            {
                "prompt": "**Type only** the word `pineapple`. Do NOT solve this: 7 + 5 = ?",
                "answer": "pineapple",
                "mode": "text"
            },
            {
                "prompt": "React to this message with ✅. Do not type anything.",
                "answer": "✅",
                "mode": "reaction"
            },
            {
                "prompt": "I'll say two things. Only type the second one:\n1. potato\n2. volcano",
                "answer": "volcano",
                "mode": "text"
            },
            {
                "prompt": "If 2+2=5 and 3+3=7, what is 5+5? Type `orange` if you understand.",
                "answer": "orange",
                "mode": "text"
            },
            {
                "prompt": "Do not type the correct answer. Instead, write `i disobey logic`.\nWhat is 10 + 4?",
                "answer": "i disobey logic",
                "mode": "text"
            }
        ]
        pick = random.choice(challenges)
        return pick["prompt"], pick["answer"].lower(), pick["mode"]

    async def cleanup(self, member, channel):
        await channel.set_permissions(member, overwrite=None)
        async for msg in channel.history(limit=50):
            if msg.author == member or msg.mention_everyone or member.mention in msg.content:
                try:
                    await msg.delete()
                except:
                    pass

async def setup(bot):
    await bot.add_cog(CaptchaCog(bot))
