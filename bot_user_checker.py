import asyncio
import logging
import random
import time
from typing import List, Dict, Any, Optional, Tuple
import json
import os

from telethon import TelegramClient
from telethon.errors import (
    FloodWaitError, PhoneNumberInvalidError, 
    PhoneNumberBannedError, PhoneNumberUnoccupiedError,
    UsernameInvalidError, ChatAdminRequiredError
)
from telethon.tl.functions.channels import GetParticipantsRequest
from telethon.tl.functions.contacts import SearchRequest
from telethon.tl.types import ChannelParticipantsSearch, User, InputPeerEmpty

from config import BOT_TOKENS
from utils import retry_with_backoff, time_it

logger = logging.getLogger(__name__)

class BotUserChecker:
    """
    Class to check user information using Telegram Bot API
    This uses a custom approach since bots have limited access to user data
    """
    
    def __init__(self, bot_token: str, session_name: Optional[str] = None):
        self.bot_token = bot_token
        self.session_name = session_name or f"bot_checker_{random.randint(1000, 9999)}"
        self.client = None
        self.rate_limited_until = 0
        self.last_request_time = 0
        self.connected = False
        self.total_requests = 0
        self.successful_requests = 0
        
    async def connect(self) -> bool:
        """Connect to Telegram API using bot token"""
        try:
            # Use default api_id and api_hash for bots
            self.client = TelegramClient(self.session_name, api_id=1, api_hash="1")
            await self.client.start(bot_token=self.bot_token)
            me = await self.client.get_me()
            logger.info(f"Connected bot: {me.username} (@{me.username})")
            self.connected = True
            return True
        except Exception as e:
            logger.error(f"Failed to connect bot: {e}")
            self.connected = False
            return False
    
    async def disconnect(self) -> None:
        """Disconnect from Telegram API"""
        if self.client:
            await self.client.disconnect()
            self.connected = False
            logger.info(f"Disconnected bot checker: {self.session_name}")
    
    def is_rate_limited(self) -> bool:
        """Check if the bot is currently rate limited"""
        return time.time() < self.rate_limited_until
    
    @time_it
    async def check_chat_member(self, chat_id: str, user_id: int) -> Optional[Dict[str, Any]]:
        """
        Check if a user is a member of a chat
        
        Args:
            chat_id: The chat ID or username
            user_id: The user ID to check
            
        Returns:
            User information or None if not found
        """
        if self.is_rate_limited() or not self.connected:
            return None
        
        try:
            # Ensure minimum time between requests to avoid rate limits (300ms)
            now = time.time()
            if now - self.last_request_time < 0.3:
                await asyncio.sleep(0.3 - (now - self.last_request_time))
            
            self.total_requests += 1
            self.last_request_time = time.time()
            
            # Get chat member
            chat_member = await self.client.get_entity(user_id)
            
            if isinstance(chat_member, User):
                self.successful_requests += 1
                
                # Extract user information
                user_info = {
                    "id": chat_member.id,
                    "first_name": chat_member.first_name,
                    "last_name": chat_member.last_name,
                    "username": chat_member.username,
                    "phone": None,  # Bots cannot access phone numbers
                    "is_bot": chat_member.bot,
                    "is_active": not chat_member.deleted,
                    "checked_on": int(time.time())
                }
                return user_info
            
            return None
        
        except FloodWaitError as e:
            # Handle rate limiting
            wait_time = e.seconds
            logger.warning(f"Rate limited, need to wait {wait_time} seconds")
            self.rate_limited_until = time.time() + wait_time
            return None
        
        except (UsernameInvalidError, ValueError):
            # User/chat not found
            return None
        
        except Exception as e:
            logger.error(f"Error checking chat member: {e}")
            return None
    
    async def search_users(self, query: str) -> List[Dict[str, Any]]:
        """
        Search for users with a given query
        
        Args:
            query: Search query (username or name)
            
        Returns:
            List of matching user information
        """
        if self.is_rate_limited() or not self.connected:
            return []
        
        try:
            # Ensure minimum time between requests to avoid rate limits
            now = time.time()
            if now - self.last_request_time < 0.3:
                await asyncio.sleep(0.3 - (now - self.last_request_time))
            
            self.total_requests += 1
            self.last_request_time = time.time()
            
            # Search for users (this has limited functionality for bots)
            result = await self.client(SearchRequest(
                q=query,
                limit=100
            ))
            
            self.successful_requests += 1
            users = []
            
            for user in result.users:
                if isinstance(user, User):
                    users.append({
                        "id": user.id,
                        "first_name": user.first_name,
                        "last_name": user.last_name,
                        "username": user.username,
                        "phone": None,  # Bots cannot access phone numbers
                        "is_bot": user.bot,
                        "is_active": not user.deleted,
                        "checked_on": int(time.time())
                    })
            
            return users
        
        except FloodWaitError as e:
            # Handle rate limiting
            wait_time = e.seconds
            logger.warning(f"Rate limited, need to wait {wait_time} seconds")
            self.rate_limited_until = time.time() + wait_time
            return []
        
        except Exception as e:
            logger.error(f"Error searching users: {e}")
            return []
    
    async def check_phone_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        """
        Try to find information about a user by their username
        
        Args:
            username: Username to check (without @)
            
        Returns:
            User information or None if not found
        """
        if self.is_rate_limited() or not self.connected:
            return None
        
        try:
            # Ensure minimum time between requests to avoid rate limits
            now = time.time()
            if now - self.last_request_time < 0.3:
                await asyncio.sleep(0.3 - (now - self.last_request_time))
            
            self.total_requests += 1
            self.last_request_time = time.time()
            
            # Resolve username
            user = await self.client.get_entity(username)
            
            if isinstance(user, User):
                self.successful_requests += 1
                
                # Extract user information
                user_info = {
                    "id": user.id,
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                    "username": user.username,
                    "phone": None,  # Bots cannot access phone numbers
                    "is_bot": user.bot,
                    "is_active": not user.deleted,
                    "checked_on": int(time.time())
                }
                return user_info
            
            return None
        
        except (UsernameInvalidError, ValueError):
            # Username not found
            return None
        
        except FloodWaitError as e:
            # Handle rate limiting
            wait_time = e.seconds
            logger.warning(f"Rate limited, need to wait {wait_time} seconds")
            self.rate_limited_until = time.time() + wait_time
            return None
        
        except Exception as e:
            logger.error(f"Error checking username: {e}")
            return None
    
    async def scrape_group_members(self, group_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Scrape members from a group or channel
        
        Args:
            group_id: Group/channel ID or username
            limit: Maximum number of members to retrieve
            
        Returns:
            List of user information
        """
        if self.is_rate_limited() or not self.connected:
            return []
        
        try:
            # Get the channel entity
            channel = await self.client.get_entity(group_id)
            
            # Fetch participants
            participants = await self.client(GetParticipantsRequest(
                channel=channel,
                filter=ChannelParticipantsSearch(''),
                offset=0,
                limit=limit,
                hash=0
            ))
            
            users = []
            for user in participants.users:
                if isinstance(user, User):
                    users.append({
                        "id": user.id,
                        "first_name": user.first_name,
                        "last_name": user.last_name,
                        "username": user.username,
                        "phone": None,  # Bots cannot access phone numbers
                        "is_bot": user.bot,
                        "is_active": not user.deleted,
                        "checked_on": int(time.time())
                    })
            
            return users
            
        except ChatAdminRequiredError:
            logger.error(f"Admin permissions required to access members of {group_id}")
            return []
            
        except FloodWaitError as e:
            # Handle rate limiting
            wait_time = e.seconds
            logger.warning(f"Rate limited, need to wait {wait_time} seconds")
            self.rate_limited_until = time.time() + wait_time
            return []
        
        except Exception as e:
            logger.error(f"Error scraping group members: {e}")
            return []

class BotCheckerPool:
    """Pool of bot checkers for distributed user data checking"""
    
    def __init__(self):
        self.bots = []
        self.active_index = 0
        self.initialized = False
        
        # Load bot tokens from config
        self.bot_tokens = BOT_TOKENS
        if not self.bot_tokens:
            logger.warning("No bot tokens configured for checker pool")
    
    async def startup(self) -> None:
        """Connect all bot checkers"""
        if self.initialized:
            return
        
        logger.info(f"Initializing bot checker pool with {len(self.bot_tokens)} bots")
        
        # Create and connect bots
        for i, token in enumerate(self.bot_tokens):
            bot_checker = BotUserChecker(token, f"checker_{i}")
            self.bots.append(bot_checker)
        
        # Connect bots in parallel
        connect_tasks = [bot.connect() for bot in self.bots]
        results = await asyncio.gather(*connect_tasks, return_exceptions=True)
        
        # Count successful connections
        successful = sum(1 for r in results if r is True)
        logger.info(f"Connected {successful} out of {len(self.bots)} bot checkers")
        
        self.initialized = successful > 0
    
    async def shutdown(self) -> None:
        """Disconnect all bot checkers"""
        disconnect_tasks = [bot.disconnect() for bot in self.bots]
        await asyncio.gather(*disconnect_tasks, return_exceptions=True)
        logger.info("All bot checkers disconnected")
    
    def get_active_checker(self) -> Optional[BotUserChecker]:
        """Get an active checker that's not rate limited"""
        if not self.bots:
            return None
        
        # Try to find a non-rate-limited bot
        for _ in range(len(self.bots)):
            bot = self.bots[self.active_index]
            self.active_index = (self.active_index + 1) % len(self.bots)
            
            if bot.connected and not bot.is_rate_limited():
                return bot
        
        # If all are rate limited, return the one with the earliest expiry
        return min(self.bots, key=lambda b: b.rate_limited_until if b.connected else float('inf'))
    
    @retry_with_backoff
    async def search_users_by_query(self, query: str) -> List[Dict[str, Any]]:
        """
        Search for users with a given query using all available bots
        
        Args:
            query: Search query (username or name)
            
        Returns:
            List of matching user information
        """
        checker = self.get_active_checker()
        if not checker:
            logger.error("No active bot checkers available")
            return []
        
        return await checker.search_users(query)
    
    @retry_with_backoff
    async def get_user_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        """
        Get user information by username
        
        Args:
            username: Username to check (without @)
            
        Returns:
            User information or None if not found
        """
        checker = self.get_active_checker()
        if not checker:
            logger.error("No active bot checkers available")
            return None
        
        return await checker.check_phone_by_username(username)
    
    @retry_with_backoff
    async def get_group_members(self, group_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Get members from a group or channel
        
        Args:
            group_id: Group/channel ID or username
            limit: Maximum number of members to retrieve
            
        Returns:
            List of user information
        """
        checker = self.get_active_checker()
        if not checker:
            logger.error("No active bot checkers available")
            return []
        
        return await checker.scrape_group_members(group_id, limit)
    
    async def search_batch(self, queries: List[str]) -> List[Dict[str, Any]]:
        """
        Search for users with multiple queries
        
        Args:
            queries: List of search queries
        
        Returns:
            List of user information
        """
        all_results = []
        
        # Process queries in batches
        batch_size = 5
        for i in range(0, len(queries), batch_size):
            batch = queries[i:i+batch_size]
            tasks = [self.search_users_by_query(query) for query in batch]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for result in results:
                if isinstance(result, list):
                    all_results.extend(result)
                else:
                    logger.error(f"Error in batch search: {result}")
        
        # Remove duplicates by user ID
        unique_users = {}
        for user in all_results:
            if user["id"] not in unique_users:
                unique_users[user["id"]] = user
        
        return list(unique_users.values())
    
    async def check_usernames(self, usernames: List[str]) -> List[Dict[str, Any]]:
        """
        Check information for multiple usernames
        
        Args:
            usernames: List of usernames (without @)
        
        Returns:
            List of user information
        """
        found_users = []
        
        # Process usernames in batches
        batch_size = 5
        for i in range(0, len(usernames), batch_size):
            batch = usernames[i:i+batch_size]
            tasks = [self.get_user_by_username(username) for username in batch]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for result in results:
                if isinstance(result, dict):
                    found_users.append(result)
        
        return found_users
    
    async def save_users_to_file(self, users: List[Dict[str, Any]], filename: str = "found_users.json") -> None:
        """
        Save found users to a JSON file
        
        Args:
            users: List of user information
            filename: Output filename
        """
        # Load existing data if the file exists
        existing_users = {}
        if os.path.exists(filename):
            try:
                with open(filename, 'r') as f:
                    existing_users = {user["id"]: user for user in json.load(f)}
            except (json.JSONDecodeError, KeyError) as e:
                logger.error(f"Error loading existing users: {e}")
        
        # Update with new data
        for user in users:
            existing_users[user["id"]] = user
        
        # Write back to file
        with open(filename, 'w') as f:
            json.dump(list(existing_users.values()), f, indent=2)
        
        logger.info(f"Saved {len(users)} users to {filename}")

# Example usage
async def main():
    # Initialize the bot checker pool
    pool = BotCheckerPool()
    await pool.startup()
    
    try:
        # Example 1: Search by query
        users = await pool.search_users_by_query("telegram")
        print(f"Found {len(users)} users by search")
        
        # Example 2: Get user by username
        user = await pool.get_user_by_username("BotFather")
        if user:
            print(f"Found user: {user['first_name']} (@{user['username']})")
        
        # Example 3: Get group members
        members = await pool.get_group_members("telegram")
        print(f"Found {len(members)} group members")
        
        # Save results
        all_users = users + ([user] if user else []) + members
        await pool.save_users_to_file(all_users)
        
    finally:
        # Clean up
        await pool.shutdown()

if __name__ == "__main__":
    asyncio.run(main())