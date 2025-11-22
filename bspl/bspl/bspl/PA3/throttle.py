import asyncio
import random
# Function to throttle LLM calls to avoid error 429 (rate limit) - integrated in agents
class Throttle:
    _lock = asyncio.Lock()

    @classmethod
    async def wait(cls, min_delay=3.0, max_delay=6.0):
        async with cls._lock:
            await asyncio.sleep(random.uniform(min_delay, max_delay))