import asyncio
import logging
import random
from telethon import TelegramClient
from telethon.errors import FloodWaitError, ChatWriteForbiddenError
from tqdm import tqdm

from utils import retry_with_backoff
from config import BOT_TOKENS, TARGET_CHANNEL, MAX_RETRIES, MAX_CONCURRENT_TASKS, API_ID, API_HASH

logger = logging.getLogger(__name__)

class TelegramBot:
    """Telegram bot for posting to channels"""
    
    def __init__(self, bot_token):
        self.bot_token = bot_token
        self.session_name = f"bot_{bot_token.split(':')[0]}"
        self.client = None
        self.connected = False
        self.last_used = 0
        logger.info(f"Initialized bot: {self.session_name}")
    
    async def connect(self):
        """Connect to Telegram API using bot token"""
        if self.connected:
            return
        
        # Create a new client using the bot token and API credentials
        self.client = TelegramClient(self.session_name, api_id=API_ID, api_hash=API_HASH)
        await self.client.start(bot_token=self.bot_token)
        
        self.connected = True
        logger.info(f"Bot connected: {self.session_name}")
    
    async def disconnect(self):
        """Disconnect from Telegram API"""
        if self.client and self.connected:
            await self.client.disconnect()
            self.connected = False
            logger.info(f"Bot disconnected: {self.session_name}")
    
    async def post_to_channel(self, channel, message, **kwargs):
        """Post a message to a channel"""
        if not self.connected:
            await self.connect()
        
        try:
            result = await retry_with_backoff(
                self.client.send_message,
                channel, message,
                max_retries=MAX_RETRIES,
                **kwargs
            )
            self.last_used = asyncio.get_event_loop().time()
            return result
        
        except ChatWriteForbiddenError:
            logger.error(f"Bot {self.session_name} does not have permission to post in {channel}")
            raise
        
        except Exception as e:
            logger.error(f"Error posting to channel with bot {self.session_name}: {str(e)}")
            raise

class BotManager:
    """Manager for multiple Telegram bots"""
    
    def __init__(self, bot_tokens=None):
        self.bot_tokens = bot_tokens or BOT_TOKENS
        self.bots = []
        for token in self.bot_tokens:
            bot = TelegramBot(token)
            self.bots.append(bot)
        
        self.active_bots = []
        logger.info(f"Initialized bot manager with {len(self.bots)} bots")
    
    async def startup(self):
        """Connect all bots"""
        connect_tasks = []
        for bot in self.bots:
            connect_tasks.append(bot.connect())
        
        await asyncio.gather(*connect_tasks)
        self.active_bots = self.bots.copy()
        logger.info(f"All {len(self.active_bots)} bots connected")
    
    async def shutdown(self):
        """Disconnect all bots"""
        disconnect_tasks = []
        for bot in self.bots:
            disconnect_tasks.append(bot.disconnect())
        
        await asyncio.gather(*disconnect_tasks)
        self.active_bots = []
        logger.info("All bots disconnected")
    
    def get_next_bot(self):
        """Get the next available bot using a simple round-robin approach"""
        if not self.active_bots:
            raise ValueError("No active bots available")
        
        # Sort bots by last used time to balance the load
        self.active_bots.sort(key=lambda bot: bot.last_used)
        return self.active_bots[0]
    
    async def post_telegram_user_info(self, user_info, channel=None):
        """Post Telegram user information to a channel"""
        if not channel:
            channel = TARGET_CHANNEL
        
        if not user_info.get('has_telegram', False):
            logger.debug(f"Skipping non-Telegram user: {user_info['phone']}")
            return None
        
        # Format the message
        message = self._format_user_info_message(user_info)
        
        # Get the next available bot
        bot = self.get_next_bot()
        
        try:
            # Post the message
            result = await bot.post_to_channel(channel, message)
            logger.info(f"Posted info for user {user_info.get('username') or user_info['phone']} to {channel}")
            return result
        
        except FloodWaitError as e:
            # If rate limited, mark the bot as unavailable temporarily and retry with another bot
            logger.warning(f"Bot {bot.session_name} is rate limited for {e.seconds} seconds")
            self.active_bots.remove(bot)
            await asyncio.sleep(1)  # Brief delay before retrying
            
            # Schedule the bot to be added back after the wait time
            asyncio.create_task(self._reactivate_bot_after_wait(bot, e.seconds))
            
            # Retry with a different bot if available
            if self.active_bots:
                return await self.post_telegram_user_info(user_info, channel)
            else:
                logger.error("No active bots available, waiting for a bot to become available")
                await asyncio.sleep(min(e.seconds, 30))  # Wait for a reasonable time
                self.active_bots = self.bots.copy()  # Reset active bots
                return await self.post_telegram_user_info(user_info, channel)
        
        except Exception as e:
            logger.error(f"Error posting user info with bot {bot.session_name}: {str(e)}")
            # Try with a different bot
            self.active_bots.remove(bot)
            if self.active_bots:
                return await self.post_telegram_user_info(user_info, channel)
            else:
                logger.error("All bots failed to post the message")
                self.active_bots = self.bots.copy()  # Reset active bots
                raise
    
    async def _reactivate_bot_after_wait(self, bot, wait_seconds):
        """Reactivate a bot after waiting for the rate limit to expire"""
        await asyncio.sleep(wait_seconds)
        if bot not in self.active_bots:
            self.active_bots.append(bot)
            logger.info(f"Bot {bot.session_name} is now active again after waiting {wait_seconds} seconds")
    
    def _format_user_info_message(self, user_info):
        """Format the user information for posting to Telegram"""
        message = "🔍 **Telegram User Found** 🔍\n\n"
        
        # Add user information
        message += f"📱 **Phone:** `{user_info['phone']}`\n"
        
        if user_info.get('username'):
            message += f"👤 **Username:** @{user_info['username']}\n"
        
        if user_info.get('first_name'):
            message += f"📝 **First Name:** {user_info['first_name']}\n"
        
        if user_info.get('last_name'):
            message += f"📝 **Last Name:** {user_info['last_name']}\n"
        
        message += f"🆔 **User ID:** `{user_info['user_id']}`\n"
        
        # Add link to the user profile
        if user_info.get('username'):
            message += f"\n[Open Profile](https://t.me/{user_info['username']})"
        
        return message
    
    async def post_user_batch(self, users, channel=None):
        """Post a batch of user information to a channel"""
        if not channel:
            channel = TARGET_CHANNEL
        
        tasks = []
        for user in users:
            tasks.append(self.post_telegram_user_info(user, channel))
        
        # Run tasks with concurrency limit
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_TASKS)
        
        async def bounded_post(user):
            async with semaphore:
                return await self.post_telegram_user_info(user, channel)
        
        post_tasks = [bounded_post(user) for user in users]
        results = await asyncio.gather(*post_tasks, return_exceptions=True)
        
        # Count successful posts
        success_count = sum(1 for r in results if r is not None and not isinstance(r, Exception))
        logger.info(f"Posted {success_count}/{len(users)} user entries to {channel}")
        
        return results

# Example usage
async def main():
    manager = BotManager()
    await manager.startup()
    
    try:
        # Sample user information
        users = [
            {
                'phone': '01712345678',
                'user_id': 123456789,
                'username': 'sample_user',
                'first_name': 'Sample',
                'last_name': 'User',
                'has_telegram': True
            }
        ]
        
        results = await manager.post_user_batch(users)
        print(f"Posted {len([r for r in results if r is not None])} users")
    
    finally:
        await manager.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
