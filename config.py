import os
import logging
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("telegram_scanner.log")
    ]
)
logger = logging.getLogger(__name__)

# Telegram API credentials - set your own API ID and HASH here
API_ID = 0  # টেলিগ্রাম অ্যাপ API ID (Replace with your own)
API_HASH = ""  # টেলিগ্রাম অ্যাপ API Hash (Replace with your own)

# সিস্টেম চালানোর সময় এই মানগুলি সেট করুন
if os.environ.get("TELEGRAM_API_ID"):
    API_ID = int(os.environ.get("TELEGRAM_API_ID"))
if os.environ.get("TELEGRAM_API_HASH"):
    API_HASH = os.environ.get("TELEGRAM_API_HASH")

# Bot tokens - set your own telegram bot tokens here or use environment variables
# You can set these as environment variables, e.g. export BOT_TOKEN_1=your_token_here
BOT_TOKEN_1 = os.environ.get("BOT_TOKEN_1", "")
BOT_TOKEN_2 = os.environ.get("BOT_TOKEN_2", "")
BOT_TOKEN_3 = os.environ.get("BOT_TOKEN_3", "")
BOT_TOKEN_4 = os.environ.get("BOT_TOKEN_4", "")
BOT_TOKEN_5 = os.environ.get("BOT_TOKEN_5", "")

BOT_TOKENS = [
    BOT_TOKEN_1,
    BOT_TOKEN_2,
    BOT_TOKEN_3,
    BOT_TOKEN_4,
    BOT_TOKEN_5
]

# Remove empty tokens
BOT_TOKENS = [token for token in BOT_TOKENS if token]

# For multi-client API usage
API_IDS = [API_ID] * len(BOT_TOKENS) if BOT_TOKENS else [API_ID]
API_HASHES = [API_HASH] * len(BOT_TOKENS) if BOT_TOKENS else [API_HASH]

# Target channel where information will be posted
TARGET_CHANNEL = os.environ.get("TARGET_CHANNEL", "https://t.me/+lPc8JNy3Tis4Yzll")

# Bangladesh phone number prefixes (operators)
BD_PREFIXES = [
    "013", "014", "015", "016", "017", "018", "019"  # Bangladesh mobile prefixes
]

# Number of workers to use for concurrent processing - recommended 50-100 for VPS
NUM_WORKERS = int(os.environ.get("NUM_WORKERS", "50"))

# Delay between batches (to avoid rate limiting)
BATCH_DELAY = int(os.environ.get("BATCH_DELAY", "1"))

# Number of numbers to check in each batch - recommended 100-500 for VPS
BATCH_SIZE = int(os.environ.get("BATCH_SIZE", "200"))

# Maximum number of retries for failed operations
MAX_RETRIES = int(os.environ.get("MAX_RETRIES", "3"))

# Maximum concurrent tasks
MAX_CONCURRENT_TASKS = int(os.environ.get("MAX_CONCURRENT_TASKS", "50"))

# Total number of phone numbers to process
TOTAL_NUMBERS = int(os.environ.get("TOTAL_NUMBERS", "7000000000"))  # 700 crore by default

if not API_ID or not API_HASH:
    logger.warning("API credentials not set. Set the API_ID and API_HASH in config.py or as environment variables")

if not BOT_TOKENS:
    logger.warning("No bot tokens configured. Set bot tokens in config.py or as environment variables")

if not TARGET_CHANNEL:
    logger.warning("Target channel not set. Set TARGET_CHANNEL in config.py or as environment variable")

logger.info(f"Configured with {len(API_IDS)} API credentials and {len(BOT_TOKENS)} bot tokens")

# Test message format
TEST_MESSAGE = """
🇧🇩 *বাংলাদেশী টেলিগ্রাম ইউজার স্ক্যানার সিস্টেম*

✅ সিস্টেম সফলভাবে ইনস্টল করা হয়েছে!
✅ এই মেসেজটি সিস্টেম টেস্টের জন্য পাঠানো হয়েছে।
✅ এখন আপনি টেলিগ্রাম ব্যবহারকারীদের স্ক্যান করতে পারবেন।

📊 *সিস্টেম তথ্য:*
- মোট চেক করার সংখ্যা: ৭০০ কোটি (৭ বিলিয়ন)
- বট টোকেন সংখ্যা: {bot_count}টি
- টার্গেট চ্যানেল: {channel}

⏰ টাইমস্ট্যাম্প: {timestamp}
"""
