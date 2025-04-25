import asyncio
import logging
import time
from functools import wraps
from telethon.errors import FloodWaitError, PhoneNumberInvalidError, ApiIdInvalidError

logger = logging.getLogger(__name__)

async def retry_with_backoff(func, *args, max_retries=3, initial_backoff=1, **kwargs):
    """
    Retry a function with exponential backoff
    
    Args:
        func: The function to retry
        max_retries: Maximum number of retries
        initial_backoff: Initial backoff time in seconds
        
    Returns:
        The result of the function call
    """
    retries = 0
    backoff = initial_backoff
    
    while retries <= max_retries:
        try:
            return await func(*args, **kwargs)
        except FloodWaitError as e:
            wait_time = e.seconds
            logger.warning(f"Rate limited, waiting for {wait_time} seconds")
            await asyncio.sleep(wait_time)
            retries += 1
        except (ConnectionError, asyncio.TimeoutError) as e:
            logger.warning(f"Connection error: {e}, retrying in {backoff} seconds")
            await asyncio.sleep(backoff)
            retries += 1
            backoff *= 2
        except Exception as e:
            if isinstance(e, (PhoneNumberInvalidError, ApiIdInvalidError)):
                logger.error(f"Fatal error: {e}")
                raise e
            logger.warning(f"Error: {e}, retrying in {backoff} seconds")
            await asyncio.sleep(backoff)
            retries += 1
            backoff *= 2
            
    logger.error(f"Failed after {max_retries} retries")
    raise Exception(f"Failed after {max_retries} retries")

def time_it(func):
    """Decorator to time a function"""
    @wraps(func)
    async def wrapper(*args, **kwargs):
        start_time = time.time()
        result = await func(*args, **kwargs)
        end_time = time.time()
        logger.info(f"{func.__name__} took {end_time - start_time:.2f} seconds")
        return result
    return wrapper

async def rate_limited_gather(tasks, limit=10):
    """
    Run tasks with a concurrency limit
    
    Args:
        tasks: List of tasks to run
        limit: Maximum number of concurrent tasks
        
    Returns:
        List of task results
    """
    semaphore = asyncio.Semaphore(limit)
    
    async def semaphore_task(task):
        async with semaphore:
            return await task
    
    return await asyncio.gather(
        *[semaphore_task(task) for task in tasks],
        return_exceptions=True
    )

def format_phone_international(number):
    """Format a phone number to international format for Telegram"""
    # Ensure the number starts with +880 (Bangladesh country code)
    if number.startswith('0'):
        number = '88' + number
    if not number.startswith('+'):
        number = '+' + number
    return number
