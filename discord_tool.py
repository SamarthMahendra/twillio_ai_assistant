import asyncio
import os
import discord
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Discord bot credentials
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
DISCORD_GUILD_ID = os.getenv("DISCORD_GUILD_ID")
DISCORD_CHANNEL_ID = os.getenv("DISCORD_CHANNEL_ID")




import discord

intents = discord.Intents.default()
intents.messages = True
intents.guilds = True

class DiscordSender(discord.Client):
    def __init__(self, message, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.message = message
        self.channel_id = int(DISCORD_CHANNEL_ID)
        self.done = False

    async def on_ready(self):
        print(f"Logged in as {self.user}")
        channel = self.get_channel(self.channel_id)
        if channel:
            print(f"Channel found: {channel.name} ({channel.id})")
            await channel.send(self.message)
            print(f"Message sent to channel {self.channel_id}")
        else:
            print(f"Channel {self.channel_id} not found.")
        await self.close()
        self.done = True

async def send_message_to_channel(message):
    intents = discord.Intents.default()
    intents.messages = True
    intents.guilds = True
    client = DiscordSender(message, intents=intents)
    await client.start(DISCORD_TOKEN)

def ask_and_get_reply(prompt_message, wait_user_id=None, timeout=120):
    import asyncio
    intents = discord.Intents.default()
    intents.messages = True
    intents.guilds = True
    intents.message_content = True

    class AskReplyBot(discord.Client):
        def __init__(self, prompt_message, wait_user_id=None, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.prompt_message = prompt_message
            self.wait_user_id = wait_user_id
            self.channel_id = int(DISCORD_CHANNEL_ID)
            self.reply = None
            self.reply_event = asyncio.Event()
            self.ready_event = asyncio.Event()

        async def on_ready(self):
            print(f"[AskReplyBot] Logged in as {self.user}")
            channel = self.get_channel(self.channel_id)
            if channel:
                await channel.send(self.prompt_message)
                print(f"[AskReplyBot] Prompt sent to channel {self.channel_id}")
            else:
                print(f"[AskReplyBot] Channel {self.channel_id} not found.")
            self.ready_event.set()

        async def on_message(self, message):
            if message.author.id == self.user.id:
                return
            if message.channel.id != self.channel_id:
                return
            if self.wait_user_id is None or str(message.author.id) == str(self.wait_user_id):
                print(f"[AskReplyBot] Received reply from {message.author}: {message.content}")
                self.reply = message.content
                self.reply_event.set()
                await self.close()

    async def run_bot():
        bot = AskReplyBot(prompt_message, wait_user_id, intents=intents)
        # Start Discord client in background
        start_task = asyncio.create_task(bot.start(DISCORD_TOKEN, reconnect=False))
        try:
            # Wait for bot to be ready and for a reply
            await asyncio.wait_for(bot.ready_event.wait(), timeout=30)
            await asyncio.wait_for(bot.reply_event.wait(), timeout=timeout)
        except Exception as e:
            print(f"[AskReplyBot] Timeout or error: {e}")
        finally:
            # Ensure client closes and background task finishes
            await bot.close()
            await start_task
        # Return the reply or fallback message
        return bot.reply or "Samarth didn't respond, he is away, but go ahead and schedule if its meeting"

    return asyncio.run(run_bot())
