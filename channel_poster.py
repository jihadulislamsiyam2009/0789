import asyncio
import logging
import time
from tqdm import tqdm

from bot_manager import BotManager
from config import TARGET_CHANNEL, BATCH_SIZE, BATCH_DELAY

logger = logging.getLogger(__name__)

class ChannelPoster:
    """Class to post Telegram user information to a channel"""
    
    def __init__(self, channel=None):
        self.channel = channel or TARGET_CHANNEL
        self.bot_manager = BotManager()
        logger.info(f"Initialized channel poster for channel: {self.channel}")
    
    async def startup(self):
        """Start up the channel poster"""
        await self.bot_manager.startup()
        logger.info("Channel poster started")
    
    async def shutdown(self):
        """Shut down the channel poster"""
        await self.bot_manager.shutdown()
        logger.info("Channel poster shut down")
    
    async def post_users(self, users, batch_size=None):
        """Post multiple user information to the channel"""
        if not users:
            logger.warning("No users to post")
            return []
        
        batch_size = batch_size or BATCH_SIZE
        batches = [users[i:i+batch_size] for i in range(0, len(users), batch_size)]
        
        all_results = []
        with tqdm(total=len(users), desc="Posting to channel") as pbar:
            for i, batch in enumerate(batches):
                try:
                    results = await self.bot_manager.post_user_batch(batch, self.channel)
                    all_results.extend(results)
                    
                    # Update progress
                    pbar.update(len(batch))
                    pbar.set_postfix(posted=len([r for r in results if r is not None]))
                    
                    # Add delay between batches to avoid rate limiting
                    if i < len(batches) - 1:
                        await asyncio.sleep(BATCH_DELAY)
                
                except Exception as e:
                    logger.error(f"Error posting batch {i}: {str(e)}")
        
        # Count successful posts
        success_count = sum(1 for r in all_results if r is not None and not isinstance(r, Exception))
        logger.info(f"Posted {success_count}/{len(users)} users to channel {self.channel}")
        
        return all_results
    
    async def post_with_status_updates(self, users, batch_size=None, update_interval=50):
        """Post users with periodic status updates"""
        if not users:
            logger.warning("No users to post")
            return []
        
        start_time = time.time()
        total_users = len(users)
        
        batch_size = batch_size or BATCH_SIZE
        batches = [users[i:i+batch_size] for i in range(0, len(users), batch_size)]
        
        all_results = []
        posted_count = 0
        
        with tqdm(total=total_users, desc="Posting to channel") as pbar:
            for i, batch in enumerate(batches):
                try:
                    results = await self.bot_manager.post_user_batch(batch, self.channel)
                    batch_success = len([r for r in results if r is not None and not isinstance(r, Exception)])
                    posted_count += batch_success
                    all_results.extend(results)
                    
                    # Update progress
                    pbar.update(len(batch))
                    pbar.set_postfix(posted=posted_count)
                    
                    # Post status update periodically
                    if i > 0 and i % update_interval == 0:
                        elapsed_time = time.time() - start_time
                        remaining = total_users - (i * batch_size)
                        est_remaining_time = (elapsed_time / (i * batch_size)) * remaining if i * batch_size > 0 else 0
                        
                        status_message = (
                            f"📊 **Progress Update** 📊\n\n"
                            f"✅ Posted: {posted_count}/{total_users} users\n"
                            f"⏱️ Elapsed time: {self._format_time(elapsed_time)}\n"
                            f"⏳ Estimated remaining: {self._format_time(est_remaining_time)}\n"
                            f"🔄 Completion: {(posted_count / total_users * 100):.1f}%"
                        )
                        
                        await self.bot_manager.bots[0].post_to_channel(self.channel, status_message)
                    
                    # Add delay between batches to avoid rate limiting
                    if i < len(batches) - 1:
                        await asyncio.sleep(BATCH_DELAY)
                
                except Exception as e:
                    logger.error(f"Error posting batch {i}: {str(e)}")
        
        # Post final summary
        total_time = time.time() - start_time
        success_count = sum(1 for r in all_results if r is not None and not isinstance(r, Exception))
        
        summary_message = (
            f"🎉 **Task Completed** 🎉\n\n"
            f"✅ Successfully posted: {success_count}/{total_users} users\n"
            f"❌ Failed: {total_users - success_count} users\n"
            f"⏱️ Total time: {self._format_time(total_time)}\n"
            f"⚡ Average speed: {success_count / total_time:.2f} users/second"
        )
        
        await self.bot_manager.bots[0].post_to_channel(self.channel, summary_message)
        
        logger.info(f"Posted {success_count}/{total_users} users to channel {self.channel}")
        logger.info(f"Total time: {self._format_time(total_time)}")
        
        return all_results
    
    @staticmethod
    def _format_time(seconds):
        """Format time in seconds to a human-readable string"""
        hours, remainder = divmod(int(seconds), 3600)
        minutes, seconds = divmod(remainder, 60)
        
        if hours > 0:
            return f"{hours}h {minutes}m {seconds}s"
        elif minutes > 0:
            return f"{minutes}m {seconds}s"
        else:
            return f"{seconds}s"

# Example usage
async def main():
    poster = ChannelPoster()
    await poster.startup()
    
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
            },
            {
                'phone': '01812345678',
                'user_id': 987654321,
                'username': 'another_user',
                'first_name': 'Another',
                'last_name': 'User',
                'has_telegram': True
            }
        ]
        
        await poster.post_with_status_updates(users)
    
    finally:
        await poster.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
