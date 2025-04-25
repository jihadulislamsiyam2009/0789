import asyncio
import logging
import random
import time
import re
import os
import json
from tqdm import tqdm
from typing import List, Dict, Any, Set, Optional

from config import NUM_WORKERS, BATCH_SIZE, MAX_RETRIES
from utils import retry_with_backoff, time_it, rate_limited_gather
from phone_generator import BangladeshPhoneGenerator

logger = logging.getLogger(__name__)

class UsernameGenerator:
    """Generates potential usernames from Bangladesh phone numbers"""
    
    def __init__(self):
        self.pattern_variants = [
            # Common username patterns for Bangladeshi users
            lambda num: num[-8:],  # last 8 digits
            lambda num: f"bd{num[-6:]}",  # bd prefix
            lambda num: f"bd_{num[-6:]}",  # bd_ prefix
            lambda num: f"user_{num[-6:]}",  # user_ prefix
            lambda num: f"{num[-6:]}_bd",  # _bd suffix
            lambda num: f"{num[-4:]}",  # last 4 digits
            lambda num: f"bangladesh_{num[-4:]}",  # bangladesh_ prefix
            lambda num: f"bn{num[-6:]}",  # bn prefix
            lambda num: f"{num[3:]}",  # without country prefix
            lambda num: f"{num[-5:]}{random.choice(['1', '2', '3', '4', '5'])}",  # last 5 digits + random digit
            lambda num: f"{random.choice(['a', 'b', 'c', 'd'])}{num[-7:]}",  # random letter + last 7 digits
            lambda num: f"{num[3:5]}{num[-6:]}",  # operator code + last 6 digits
            lambda num: f"{num[-6:]}_{random.choice(['bd', 'bn', 'bgd'])}",  # last 6 digits + _bd/bn/bgd
        ]
        
        # Name parts for generating random name-based usernames
        self.common_bd_names = [
            "ahmed", "rahman", "khan", "hossain", "islam", "mohammad", "alam",
            "karim", "akter", "siddique", "chowdhury", "sarkar", "begum", "ali",
            "miah", "roy", "jahan", "uddin", "mojumder", "kabir", "islam", "rahim"
        ]
        
        # Common words in usernames
        self.common_words = [
            "cool", "smart", "pro", "king", "queen", "star", "tech", "fan", 
            "boss", "gamer", "trader", "official", "real", "original"
        ]
    
    def generate_name_based_username(self) -> str:
        """Generate a username based on common Bangladeshi names"""
        name = random.choice(self.common_bd_names)
        
        # Add variations
        if random.random() < 0.7:  # 70% chance to add suffix
            if random.random() < 0.5:  # 50% chance for a word
                suffix = random.choice(self.common_words)
            else:  # 50% chance for numbers
                num_digits = random.randint(1, 4)
                suffix = "".join(random.choices("0123456789", k=num_digits))
            
            # Connect with underscore sometimes
            if random.random() < 0.3:
                username = f"{name}_{suffix}"
            else:
                username = f"{name}{suffix}"
        else:
            username = name
        
        return username
        
    def generate_username_variants(self, phone_number: str) -> List[str]:
        """Generate possible username variants from a phone number"""
        variants = []
        
        # Apply all pattern variants
        for pattern in self.pattern_variants:
            try:
                variant = pattern(phone_number)
                variants.append(variant)
            except (IndexError, ValueError):
                continue
                
        # Add some name-based variants
        for _ in range(3):
            variants.append(self.generate_name_based_username())
        
        # Remove duplicates and ensure valid username format
        clean_variants = []
        for variant in variants:
            # Username requirements: 5-30 characters, only letters, numbers and underscores
            if 5 <= len(variant) <= 30 and re.match(r'^[a-zA-Z0-9_]+$', variant):
                clean_variants.append(variant)
        
        return clean_variants
    
    async def generate_usernames_from_phones(self, phone_numbers: List[str], max_variants_per_number: int = 3) -> List[str]:
        """Generate a list of possible usernames from phone numbers"""
        all_usernames = []
        
        for phone in phone_numbers:
            variants = self.generate_username_variants(phone)
            # Limit variants per number to avoid too many usernames
            selected_variants = random.sample(variants, min(max_variants_per_number, len(variants)))
            all_usernames.extend(selected_variants)
        
        # Remove duplicates while preserving order
        unique_usernames = []
        seen = set()
        for username in all_usernames:
            if username not in seen:
                seen.add(username)
                unique_usernames.append(username)
        
        return unique_usernames
    
    async def generate_username_batch(self, count: int = 1000) -> List[str]:
        """Generate a batch of usernames both from random names and patterns"""
        usernames = []
        
        # Generate some completely random name-based usernames
        for _ in range(count // 3):
            usernames.append(self.generate_name_based_username())
        
        # Generate phone-based usernames
        phone_generator = BangladeshPhoneGenerator()
        phone_count = count - len(usernames)
        phone_numbers = await phone_generator.generate_numbers_async(phone_count)
        
        # Generate variants from the phone numbers
        phone_usernames = await self.generate_usernames_from_phones(phone_numbers)
        usernames.extend(phone_usernames)
        
        # Remove duplicates and ensure we have enough
        usernames = list(set(usernames))
        
        # If we don't have enough, add more name-based usernames
        while len(usernames) < count:
            usernames.append(self.generate_name_based_username())
            # Remove duplicates
            usernames = list(set(usernames))
        
        # Trim to exact count
        return usernames[:count]

async def save_progress(found_usernames: List[Dict[str, Any]], filename: str = 'found_users.json') -> None:
    """Save found usernames to a JSON file for resuming later"""
    try:
        # Create user dictionary by ID for deduplication
        user_dict = {}
        for user in found_usernames:
            user_dict[user.get('id', str(random.randint(1000000, 9999999)))] = user
        
        # Write to file
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(list(user_dict.values()), f, indent=2)
        
        logger.info(f"Progress saved: {len(user_dict)} users saved to {filename}")
    except Exception as e:
        logger.error(f"Error saving progress: {e}")

async def load_progress(filename: str = 'found_users.json') -> List[Dict[str, Any]]:
    """Load previously found usernames from a JSON file"""
    if not os.path.exists(filename):
        logger.info(f"No progress file found: {filename}")
        return []
    
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            users = json.load(f)
        logger.info(f"Loaded {len(users)} previously found users from {filename}")
        return users
    except Exception as e:
        logger.error(f"Error loading progress: {e}")
        return []

async def main():
    # Example usage
    generator = UsernameGenerator()
    usernames = await generator.generate_username_batch(100)
    
    print(f"Generated {len(usernames)} usernames")
    print("Sample usernames:")
    for username in usernames[:20]:
        print(f"- {username}")

if __name__ == "__main__":
    asyncio.run(main())