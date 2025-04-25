#!/usr/bin/env python3
import os
import asyncio
import logging
import argparse
import time
import datetime
import signal
import json
from tqdm import tqdm

from phone_generator import BangladeshPhoneGenerator
from bot_user_checker import BotCheckerPool
from channel_poster import ChannelPoster
from username_extractor import UsernameGenerator, save_progress, load_progress
from config import TARGET_CHANNEL, BATCH_SIZE, TOTAL_NUMBERS, NUM_WORKERS

logger = logging.getLogger(__name__)

# Global variable to store the running tasks for graceful shutdown
running_tasks = []
exit_flag = False

# Signal handler for graceful shutdown
def signal_handler(sig, frame):
    global exit_flag
    print("\nReceived shutdown signal. Completing current batch and saving progress...")
    exit_flag = True

# Register signal handlers
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

async def save_progress(found_users, progress_file='progress.json'):
    """Save found users to a JSON file for resuming later"""
    with open(progress_file, 'w') as f:
        json.dump({
            'timestamp': datetime.datetime.now().isoformat(),
            'users_count': len(found_users),
            'users': found_users
        }, f)
    logger.info(f"Progress saved to {progress_file}: {len(found_users)} users")

async def load_progress(progress_file='progress.json'):
    """Load previously found users from a JSON file"""
    if os.path.exists(progress_file):
        try:
            with open(progress_file, 'r') as f:
                data = json.load(f)
            logger.info(f"Loaded {len(data['users'])} users from previous run ({data['timestamp']})")
            return data['users']
        except Exception as e:
            logger.error(f"Error loading progress file: {e}")
    return []

# Flask app import - only import if web interface is needed
try:
    from app import app
except ImportError:
    logger.info("Flask web interface not available, continuing with CLI mode")

async def main():
    """Main function to run the Telegram phone scanner"""
    parser = argparse.ArgumentParser(description="Scan Bangladesh phone numbers for Telegram accounts")
    parser.add_argument("--total", type=int, default=TOTAL_NUMBERS, 
                      help=f"Total numbers to generate and check (default: {TOTAL_NUMBERS:,})")
    parser.add_argument("--batch", type=int, default=BATCH_SIZE, 
                      help=f"Batch size for processing (default: {BATCH_SIZE})")
    parser.add_argument("--workers", type=int, default=NUM_WORKERS,
                      help=f"Number of concurrent workers (default: {NUM_WORKERS})")
    parser.add_argument("--channel", type=str, default=TARGET_CHANNEL,
                      help="Target Telegram channel")
    parser.add_argument("--only-generate", action="store_true", 
                      help="Only generate numbers, don't check or post")
    parser.add_argument("--only-check", action="store_true",
                      help="Only check numbers, don't post")
    parser.add_argument("--resume", action="store_true",
                      help="Resume from previous run (loads users from progress.json)")
    parser.add_argument("--save-interval", type=int, default=1000,
                      help="Save progress after finding this many new users (default: 1000)")
    
    args = parser.parse_args()
    
    start_time = time.time()
    logger.info(f"Starting Bangladesh phone number scanner for Telegram users")
    logger.info(f"Target: {args.total:,} numbers, batch size: {args.batch}, workers: {args.workers}")
    
    # Load previous progress if resuming
    found_users = []
    if args.resume:
        found_users = await load_progress()
        if found_users:
            logger.info(f"Resuming with {len(found_users)} previously found users")
    
    # Step 1: Generate Bangladesh phone numbers
    logger.info("Step 1: Generating phone numbers")
    phone_generator = BangladeshPhoneGenerator()
    
    # Generate phone numbers
    phone_numbers = await phone_generator.generate_numbers_async(args.total, batch_size=args.batch)
    
    if args.only_generate:
        # Just display a sample of the generated numbers
        sample_size = min(5, len(phone_numbers))
        logger.info(f"Generated {len(phone_numbers)} phone numbers. Sample: {phone_numbers[:sample_size]}")
        logger.info("Phone number generator is working. Exiting as requested.")
        return
    
    # Step 2: Generate usernames from phone numbers
    logger.info("Step 2: Generating potential usernames from phone numbers")
    username_generator = UsernameGenerator()
    usernames = await username_generator.generate_usernames_from_phones(phone_numbers, max_variants_per_number=2)
    
    # Print sample of generated usernames
    sample_size = min(5, len(usernames))
    if sample_size > 0:
        sample = usernames[:sample_size]
        logger.info(f"Generated {len(usernames)} potential usernames. Sample: {sample}")
    
    # Step 3: Check if usernames have Telegram accounts
    logger.info("Step 3: Checking for Telegram accounts using bot API")
    checker_pool = BotCheckerPool()
    await checker_pool.startup()
    
    try:
        # Process the usernames in batches
        batch_counter = 0
        numbers_checked = 0
        users_found = 0
        save_counter = 0
        
        logger.info(f"Starting to check usernames for Telegram accounts")
        
        # Process in batches to avoid memory issues and rate limits
        batch_size = min(args.batch, 20)  # Keep batches smaller for bot API
        batches = [usernames[i:i+batch_size] for i in range(0, len(usernames), batch_size)]
        
        for i, batch in enumerate(batches):
            if exit_flag:
                logger.info("Exit flag detected. Stopping further processing.")
                break
                
            batch_counter += 1
            try:
                batch_users = await checker_pool.check_usernames(batch)
                numbers_checked += len(batch)
                users_found += len(batch_users)
                found_users.extend(batch_users)
                save_counter += len(batch_users)
                
                logger.info(f"Batch {batch_counter}: Checked {len(batch)} numbers, found {len(batch_users)} users " +
                           f"(Total: {numbers_checked:,} checked, {users_found:,} users found)")
                
                # Save progress periodically
                if save_counter >= args.save_interval:
                    await save_progress(found_users)
                    save_counter = 0
                    
            except Exception as e:
                logger.error(f"Error processing batch {batch_counter}: {str(e)}")
    
    except Exception as e:
        logger.error(f"Error during number checking: {str(e)}")
    finally:
        # Save progress before shutting down
        if found_users:
            await save_progress(found_users)
        await checker_pool.shutdown()
    
    if args.only_check or not found_users:
        logger.info(f"Found {len(found_users)} Telegram users. Exiting as requested or no users found.")
        return
    
    # Step 3: Post information to Telegram channel
    if args.channel:
        logger.info(f"Step 3: Posting {len(found_users)} users to channel {args.channel}")
        poster = ChannelPoster(args.channel)
        await poster.startup()
        
        try:
            await poster.post_with_status_updates(found_users, batch_size=args.batch)
        except Exception as e:
            logger.error(f"Error during posting: {str(e)}")
        finally:
            await poster.shutdown()
    else:
        logger.warning("No channel specified. Skipping posting step.")
    
    # Final summary
    total_time = time.time() - start_time
    hours, remainder = divmod(int(total_time), 3600)
    minutes, seconds = divmod(remainder, 60)
    
    logger.info(f"Completed scan in {hours}h {minutes}m {seconds}s")
    logger.info(f"Found a total of {len(found_users)} Telegram users")

    # Write a final report
    with open('scan_report.txt', 'w') as f:
        f.write(f"Bangladesh Phone Number Scanner Report\n")
        f.write(f"Generated on: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write(f"Total time: {hours}h {minutes}m {seconds}s\n")
        f.write(f"Total users found: {len(found_users)}\n\n")
        f.write(f"Sample users:\n")
        for user in found_users[:10]:  # Show first 10 users
            f.write(f"- Phone: {user['phone']}, Username: {user.get('username', 'None')}\n")
        f.write("\nFull results saved in progress.json\n")
        
    logger.info(f"Report written to scan_report.txt")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received. Exiting gracefully...")
    except Exception as e:
        logger.error(f"Unhandled exception: {str(e)}", exc_info=True)