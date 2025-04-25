import random
import asyncio
import logging
import os
import time
import math
import threading
import multiprocessing
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from config import BD_PREFIXES, TOTAL_NUMBERS
from tqdm import tqdm

logger = logging.getLogger(__name__)

class BangladeshPhoneGenerator:
    """Ultra-fast generator for Bangladesh phone numbers"""
    
    def __init__(self):
        self.prefixes = BD_PREFIXES
        # Precompute prefix odds to favor more common prefixes (e.g., 017, 018, 019)
        self.prefix_weights = {
            '017': 0.25,  # Grameenphone (most common)
            '018': 0.20,  # Robi
            '019': 0.20,  # Banglalink
            '016': 0.15,  # Airtel
            '015': 0.10,  # Teletalk
            '013': 0.05,  # Citycell
            '014': 0.05   # Less common
        }
        
        # Create prefix distribution
        available_prefixes = set(self.prefixes)
        self.weighted_prefixes = []
        self.prefix_weights_norm = []
        
        # Normalize weights for available prefixes
        total_weight = sum(w for p, w in self.prefix_weights.items() if p in available_prefixes)
        for prefix in self.prefixes:
            weight = self.prefix_weights.get(prefix, 1.0/len(self.prefixes))
            if total_weight > 0:
                weight = weight / total_weight
            self.weighted_prefixes.append(prefix)
            self.prefix_weights_norm.append(weight)
            
        logger.info(f"Initialized phone generator with prefixes: {self.prefixes}")
    
    def generate_number(self):
        """Generate a single Bangladesh phone number"""
        # Use weighted choice for prefixes to simulate realistic distribution
        prefix = random.choices(self.weighted_prefixes, weights=self.prefix_weights_norm, k=1)[0]
        # Bangladesh mobile numbers are 11 digits (excluding country code)
        # Format: 01X-XXXXXXXX where X is the operator code
        suffix = ''.join(random.choices('0123456789', k=8))
        number = f"{prefix}{suffix}"
        return number
    
    def generate_batch(self, batch_size=100):
        """Generate a batch of Bangladesh phone numbers"""
        return [self.generate_number() for _ in range(batch_size)]

    def _generate_batch_process(self, args):
        """Generate a batch in a separate process (for multiprocessing)"""
        batch_size, batch_id, use_cache = args
        # Seed based on batch_id for more varied results across batches
        random.seed(int(time.time()) + batch_id)
        batch = self.generate_batch(batch_size)
        return batch
    
    async def generate_numbers_async(self, count=None, batch_size=50000, multiprocess=True):
        """
        Generate phone numbers asynchronously with progress tracking
        
        Args:
            count: Number of phone numbers to generate (defaults to TOTAL_NUMBERS from config)
            batch_size: Size of each batch
            multiprocess: Whether to use multiprocessing for generation
            
        Returns:
            List of generated phone numbers or generator for very large counts
        """
        if count is None:
            count = TOTAL_NUMBERS
            
        start_time = time.time()
        logger.info(f"Starting to generate {count:,} phone numbers using batch size {batch_size:,}")
        
        # For extremely large counts (like 700 crore), return a generator function
        if count > 100000000:  # 10 crore 
            logger.info(f"Very large count ({count:,}), returning batch generator")
            return self._create_fast_number_generator(count, batch_size)
            
        # For reasonable sizes, generate and keep in memory
        numbers = []
        total_batches = (count + batch_size - 1) // batch_size
        
        # Determine optimal execution strategy based on count
        with tqdm(total=count, desc="Generating phone numbers") as pbar:
            if multiprocess and count > 500000 and os.cpu_count() > 1:
                # Use multiprocessing for very large batches - fastest for big datasets
                cpu_count = min(os.cpu_count() or 2, 8) 
                logger.info(f"Using {cpu_count} CPU cores for parallel number generation")
                
                # Create batch generation tasks
                batch_args = [(
                    min(batch_size, count - i * batch_size), 
                    i,
                    i % 3 == 0  # Use cache for every 3rd batch to increase variety
                ) for i in range(total_batches)]
                
                with ProcessPoolExecutor(max_workers=cpu_count) as executor:
                    for batch in executor.map(self._generate_batch_process, batch_args):
                        numbers.extend(batch)
                        pbar.update(len(batch))
                        # Let other async tasks run (e.g., UI updates)
                        await asyncio.sleep(0.0001)
            
            elif count > 50000:
                # Use threading for medium-sized datasets
                thread_count = min(8, (os.cpu_count() or 2) * 2)
                logger.info(f"Using {thread_count} threads for parallel number generation")
                
                with ThreadPoolExecutor(max_workers=thread_count) as executor:
                    futures = []
                    for i in range(total_batches):
                        current_batch_size = min(batch_size, count - i * batch_size)
                        if current_batch_size <= 0:
                            break
                        futures.append(executor.submit(self.generate_batch, current_batch_size))
                    
                    for future in futures:
                        batch = future.result()
                        numbers.extend(batch)
                        pbar.update(len(batch))
                        await asyncio.sleep(0.0001)
            
            else:
                # Single process approach for smaller datasets
                for i in range(total_batches):
                    current_batch_size = min(batch_size, count - i * batch_size)
                    if current_batch_size <= 0:
                        break
                    
                    batch = self.generate_batch(current_batch_size)
                    numbers.extend(batch)
                    pbar.update(current_batch_size)
                    await asyncio.sleep(0.0001)
        
        elapsed = time.time() - start_time
        rate = count / elapsed if elapsed > 0 else 0
        rate_formatted = f"{rate:.2f}" if rate < 1000 else f"{rate/1000:.2f}K"
        logger.info(f"Generated {len(numbers):,} phone numbers in {elapsed:.2f}s ({rate_formatted} numbers/sec)")
        return numbers

    def _create_fast_number_generator(self, total_count, batch_size=50000):
        """
        Create a super-fast generator function for extremely large counts (700 crore)
        This avoids memory issues by yielding batches on demand
        """
        class BatchNumberGenerator:
            def __init__(self, generator, total, batch_size):
                self.generator = generator
                self.total = total
                self.batch_size = batch_size
                self.generated = 0
                self.last_log = time.time()
                self.log_interval = 10  # Log every 10 seconds for long runs
                self.start_time = time.time()
                
                # For multiprocessing
                self.pool = None
                self.futures = []
                self.use_multiprocessing = total > 1000000 and os.cpu_count() > 1
                
                if self.use_multiprocessing:
                    cpu_count = min(os.cpu_count() or 2, 8)
                    self.pool = ProcessPoolExecutor(max_workers=cpu_count)
                    
                    # Pre-submit some batch jobs to keep pipeline full
                    prefetch_count = min(20, math.ceil(total / batch_size))
                    logger.info(f"Prefetching {prefetch_count} batches using {cpu_count} CPU cores")
                    
                    for i in range(prefetch_count):
                        size = min(batch_size, total - i * batch_size)
                        if size <= 0: 
                            break
                        self.futures.append(self.pool.submit(
                            self.generator._generate_batch_process, 
                            (size, i, i % 2 == 0)
                        ))
            
            def __del__(self):
                if self.pool:
                    self.pool.shutdown()
            
            def __iter__(self):
                return self
            
            def __next__(self):
                if self.generated >= self.total:
                    if self.pool:
                        self.pool.shutdown()
                        self.pool = None
                    elapsed = time.time() - self.start_time
                    rate = self.generated / elapsed if elapsed > 0 else 0
                    logger.info(f"Completed generating {self.generated:,} numbers in {elapsed:.1f}s ({rate:.1f}/s)")
                    raise StopIteration

                # Determine current batch size
                current_size = min(self.batch_size, self.total - self.generated)
                
                # Generate the batch
                if self.use_multiprocessing and self.pool and self.futures:
                    # Get result from prefetched future
                    batch = self.futures.pop(0).result()
                    
                    # Submit a new future to keep pipeline full
                    next_batch_idx = math.ceil(self.generated / self.batch_size) + len(self.futures)
                    next_size = min(self.batch_size, self.total - next_batch_idx * self.batch_size)
                    
                    if next_size > 0:
                        self.futures.append(self.pool.submit(
                            self.generator._generate_batch_process,
                            (next_size, next_batch_idx, next_batch_idx % 2 == 0)
                        ))
                else:
                    # Single thread fallback
                    batch = self.generator.generate_batch(current_size)
                
                # Update progress tracking
                self.generated += len(batch)
                
                # Periodically log progress for long-running generations
                now = time.time()
                if now - self.last_log >= self.log_interval:
                    elapsed = now - self.start_time
                    percent = 100 * self.generated / self.total
                    rate = self.generated / elapsed if elapsed > 0 else 0
                    
                    # Estimate time remaining
                    if rate > 0:
                        remaining = (self.total - self.generated) / rate
                        remaining_str = f", est. {remaining/60:.1f} min remaining"
                    else:
                        remaining_str = ""
                        
                    logger.info(f"Generated {self.generated:,}/{self.total:,} numbers ({percent:.1f}%) at {rate:.1f}/s{remaining_str}")
                    self.last_log = now
                
                return batch
        
        return BatchNumberGenerator(self, total_count, batch_size)
    
    @staticmethod
    def format_international(number):
        """Format a phone number to international format for Telegram"""
        # Ensure the number starts with +880 (Bangladesh country code)
        if number.startswith('0'):
            number = '88' + number
        if not number.startswith('+'):
            number = '+' + number
        return number

# Example usage
async def main():
    generator = BangladeshPhoneGenerator()
    
    # Demo small count
    print("Generating a sample of 1000 numbers...")
    numbers = await generator.generate_numbers_async(1000)
    print(f"Sample numbers: {numbers[:5]}")
    print(f"International format: {[generator.format_international(num) for num in numbers[:5]]}")
    
    # Demo large count
    print("\nGenerating 5000 numbers for demonstration...")
    numbers_large = await generator.generate_numbers_async(5000)
    print(f"Generated {len(numbers_large)} numbers for large demo")

if __name__ == "__main__":
    asyncio.run(main())
