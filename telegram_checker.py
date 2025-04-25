import asyncio
import logging
import time
import random
import os
from telethon import TelegramClient
from telethon.errors import (
    FloodWaitError, PhoneNumberInvalidError, PhoneNumberBannedError, 
    UserDeactivatedError, AuthKeyUnregisteredError
)
from telethon.tl.functions.contacts import ImportContactsRequest
from telethon.tl.types import InputPhoneContact
from tqdm import tqdm

from utils import retry_with_backoff, rate_limited_gather, format_phone_international
from config import API_IDS, API_HASHES, MAX_CONCURRENT_TASKS, BATCH_SIZE, BATCH_DELAY, MAX_RETRIES, NUM_WORKERS

logger = logging.getLogger(__name__)

class TelegramUserChecker:
    """Class to check if a phone number is associated with a Telegram account"""
    
    def __init__(self, api_id, api_hash, session_name=None):
        self.api_id = api_id
        self.api_hash = api_hash
        self.session_name = session_name or f"checker_{api_id}_{random.randint(1000, 9999)}"
        self.client = None
        self.connected = False
        self.rate_limited_until = 0
        self.total_checked = 0
        self.total_found = 0
        logger.info(f"Initialized Telegram checker with API ID: {api_id}")
    
    async def connect(self):
        """Connect to Telegram API"""
        if self.connected:
            return
        
        try:
            self.client = TelegramClient(self.session_name, self.api_id, self.api_hash)
            await self.client.connect()
            self.connected = True
            logger.info(f"Connected to Telegram API with session: {self.session_name}")
        except Exception as e:
            logger.error(f"Failed to connect to Telegram API: {str(e)}")
            raise
    
    async def disconnect(self):
        """Disconnect from Telegram API"""
        if self.client and self.connected:
            try:
                await self.client.disconnect()
                self.connected = False
                logger.info(f"Disconnected from Telegram API: {self.session_name}")
            except Exception as e:
                logger.error(f"Error disconnecting from Telegram API: {str(e)}")
    
    def is_rate_limited(self):
        """Check if the client is currently rate limited"""
        return time.time() < self.rate_limited_until
    
    async def check_phone_number(self, phone_number):
        """Check if a phone number is associated with a Telegram account"""
        if not self.connected:
            await self.connect()
        
        if self.is_rate_limited():
            wait_time = self.rate_limited_until - time.time()
            if wait_time > 0:
                logger.debug(f"Checker {self.session_name} is rate limited. Waiting {wait_time:.1f}s")
                await asyncio.sleep(wait_time)
        
        self.total_checked += 1
        
        try:
            # Format the phone number for Telegram
            formatted_number = format_phone_international(phone_number)
            
            # Check if the phone number has a Telegram account
            result = await retry_with_backoff(
                self.client.get_entity, formatted_number,
                max_retries=MAX_RETRIES
            )
            
            # Collect and return user information
            user_info = {
                'phone': phone_number,
                'user_id': result.id,
                'username': result.username,
                'first_name': result.first_name,
                'last_name': result.last_name,
                'has_telegram': True,
                'timestamp': int(time.time())
            }
            
            self.total_found += 1
            if self.total_found % 10 == 0:  # Log every 10 users found
                logger.info(f"Checker {self.session_name} found {self.total_found} users out of {self.total_checked} checked")
            else:
                logger.debug(f"Found Telegram user: {user_info.get('username') or user_info['phone']}")
                
            return user_info
            
        except PhoneNumberInvalidError:
            logger.debug(f"Invalid phone number: {phone_number}")
            return {'phone': phone_number, 'has_telegram': False}
        
        except PhoneNumberBannedError:
            logger.warning(f"Banned phone number: {phone_number}")
            return {'phone': phone_number, 'has_telegram': False, 'banned': True}
        
        except UserDeactivatedError:
            logger.debug(f"Deactivated user: {phone_number}")
            return {'phone': phone_number, 'has_telegram': False, 'deactivated': True}
        
        except AuthKeyUnregisteredError:
            logger.error(f"Auth key unregistered. Reconnecting session {self.session_name}")
            self.connected = False
            await self.connect()
            return {'phone': phone_number, 'has_telegram': False, 'error': 'auth_key_unregistered'}
            
        except FloodWaitError as e:
            wait_time = e.seconds
            logger.warning(f"Rate limited for {wait_time} seconds on {self.session_name}")
            self.rate_limited_until = time.time() + wait_time
            return {'phone': phone_number, 'has_telegram': False, 'error': f'flood_wait:{wait_time}'}
            
        except Exception as e:
            logger.debug(f"Error checking phone number {phone_number}: {str(e)}")
            return {'phone': phone_number, 'has_telegram': False, 'error': str(e)}
    
    async def process_batch(self, phone_numbers):
        """
        Process a batch of phone numbers
        
        Args:
            phone_numbers: List of phone numbers to check
            
        Returns:
            List of users with Telegram accounts
        """
        if not self.connected:
            await self.connect()
        
        # Process in smaller chunks to avoid memory issues
        results = []
        chunk_size = min(50, len(phone_numbers))
        chunks = [phone_numbers[i:i+chunk_size] for i in range(0, len(phone_numbers), chunk_size)]
        
        for chunk in chunks:
            tasks = [self.check_phone_number(phone) for phone in chunk]
            chunk_results = await rate_limited_gather(tasks, limit=MAX_CONCURRENT_TASKS)
            results.extend(chunk_results)
            await asyncio.sleep(0.1)  # Small delay between chunks
        
        # Filter out failures and non-Telegram users
        valid_users = [r for r in results if isinstance(r, dict) and r.get('has_telegram', False)]
        
        if valid_users:
            logger.info(f"Checker {self.session_name} found {len(valid_users)} Telegram users in batch of {len(phone_numbers)}")
        
        return valid_users

class TelegramCheckerPool:
    """Pool of Telegram user checkers for efficient processing"""
    
    def __init__(self, num_workers=None):
        """
        Initialize the checker pool
        
        Args:
            num_workers: Number of checker workers to use (defaults to NUM_WORKERS from config)
        """
        if num_workers is None:
            num_workers = NUM_WORKERS
            
        # Limit number of workers to available API credentials
        num_workers = min(num_workers, len(API_IDS))
        
        self.checkers = []
        for i in range(num_workers):
            checker_id = i % len(API_IDS)
            checker = TelegramUserChecker(
                API_IDS[checker_id], 
                API_HASHES[checker_id],
                session_name=f"checker_{i}"
            )
            self.checkers.append(checker)
        
        logger.info(f"Initialized checker pool with {len(self.checkers)} checkers")
        self.active_checkers = []
    
    async def startup(self):
        """Connect all checkers"""
        connect_tasks = []
        for checker in self.checkers:
            connect_tasks.append(checker.connect())
        
        await asyncio.gather(*connect_tasks, return_exceptions=True)
        self.active_checkers = self.checkers.copy()
        logger.info(f"Connected {len(self.active_checkers)} checkers")
    
    async def shutdown(self):
        """Disconnect all checkers"""
        disconnect_tasks = []
        for checker in self.checkers:
            disconnect_tasks.append(checker.disconnect())
        
        await asyncio.gather(*disconnect_tasks, return_exceptions=True)
        self.active_checkers = []
        logger.info("All checkers disconnected")
        
        # Clean up session files
        for checker in self.checkers:
            session_file = f"{checker.session_name}.session"
            if os.path.exists(session_file):
                try:
                    os.remove(session_file)
                    logger.debug(f"Removed session file: {session_file}")
                except:
                    pass
    
    def get_active_checker(self):
        """Get an active checker that's not rate limited"""
        available_checkers = [c for c in self.active_checkers if not c.is_rate_limited()]
        
        if not available_checkers:
            if not self.active_checkers:
                raise ValueError("No active checkers available")
                
            # All checkers are rate limited, get the one with minimum wait time
            self.active_checkers.sort(key=lambda c: c.rate_limited_until)
            checker = self.active_checkers[0]
            logger.warning(f"All checkers are rate limited. Using {checker.session_name} with minimum wait time")
            return checker
            
        # Sort by number of checks to balance load
        available_checkers.sort(key=lambda c: c.total_checked)
        return available_checkers[0]
    
    async def process_numbers(self, phone_numbers):
        """
        Process a list or batch of phone numbers using all available checkers
        
        Args:
            phone_numbers: List of phone numbers to check
            
        Returns:
            List of users with Telegram accounts
        """
        if not self.active_checkers:
            raise ValueError("No active checkers available. Call startup() first.")
        
        all_telegram_users = []
        
        # Convert to list if it's an iterable
        if not isinstance(phone_numbers, list):
            phone_numbers = list(phone_numbers)
            
        batches = [phone_numbers[i:i+BATCH_SIZE] for i in range(0, len(phone_numbers), BATCH_SIZE)]
        
        with tqdm(total=len(phone_numbers), desc="Checking Telegram users") as pbar:
            for i, batch in enumerate(batches):
                # Select a checker that's not rate limited
                checker = self.get_active_checker()
                
                try:
                    # Process the batch with the selected checker
                    users = await checker.process_batch(batch)
                    all_telegram_users.extend(users)
                    
                    # Update progress
                    pbar.update(len(batch))
                    pbar.set_postfix(found=len(all_telegram_users))
                    
                    # Add delay between batches to avoid rate limiting
                    if i < len(batches) - 1:
                        await asyncio.sleep(BATCH_DELAY)
                    
                except FloodWaitError as e:
                    # If rate limited, mark the checker as rate limited and retry with a different one
                    logger.warning(f"Rate limited for {e.seconds} seconds on checker {checker.session_name}")
                    checker.rate_limited_until = time.time() + e.seconds
                    # Retry the same batch with a different checker
                    i -= 1
                    
                except Exception as e:
                    logger.error(f"Error processing batch {i} with checker {checker.session_name}: {str(e)}")
                    # If the checker fails, remove it from the active list
                    if checker in self.active_checkers:
                        self.active_checkers.remove(checker)
                        logger.warning(f"Removed failed checker {checker.session_name}. {len(self.active_checkers)} checkers remain active")
                    
                    # If we still have active checkers, retry the batch, otherwise skip it
                    if self.active_checkers:
                        i -= 1
                    else:
                        logger.error("No more active checkers. Skipping remaining batches.")
                        break
        
        logger.info(f"Found a total of {len(all_telegram_users)} Telegram users")
        return all_telegram_users

# Example usage
async def main():
    # For testing
    checker_pool = TelegramCheckerPool(num_workers=1)  # Use single worker for testing
    await checker_pool.startup()
    
    # Sample phone numbers for demonstration
    phone_numbers = [
        '01712345678', '01812345678', '01912345678',
        '01612345678', '01712345679', '01812345670'
    ]
    
    try:
        users = await checker_pool.process_numbers(phone_numbers)
        print(f"Found {len(users)} users with Telegram accounts")
        for user in users:
            print(user)
    finally:
        await checker_pool.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
