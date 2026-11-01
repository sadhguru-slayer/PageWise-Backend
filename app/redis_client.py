import os
import time
import asyncio
import logging
from typing import Optional
import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

# Redis URL from environment. Default to localhost for local dev; Docker compose sets redis://redis:6379/0
REDIS_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")

# In-memory fallback dictionary with TTL: {key: (value, expire_timestamp)}
_in_memory_store = {}


class ResumoRedisClient:
    """Async Redis client with automatic local fallback if Redis server is temporarily unreachable."""

    def __init__(self):
        self._client: Optional[aioredis.Redis] = None
        self._connected = False
        self._attempted = False

    async def get_client(self) -> Optional[aioredis.Redis]:
        if self._client is not None and self._connected:
            return self._client

        if self._attempted and not self._connected:
            return None

        self._attempted = True
        try:
            client = aioredis.from_url(
                REDIS_URL,
                decode_responses=True,
                socket_connect_timeout=0.5,
                socket_timeout=0.5,
            )
            # Use strict timeout so host DNS never blocks
            await asyncio.wait_for(client.ping(), timeout=0.5)
            self._client = client
            self._connected = True
            logger.info(f"Connected to Redis at {REDIS_URL}")
            return self._client
        except Exception:
            self._connected = False
            self._client = None
            logger.info("Redis not active; using fast in-memory TTL store for OTP.")
            return None

    async def set(self, key: str, value: str, ex: int = 600) -> bool:
        client = await self.get_client()
        if client:
            try:
                await client.set(key, value, ex=ex)
                return True
            except Exception as e:
                logger.warning(f"Redis set failed ({e}), using in-memory store")
                self._connected = False
                self._client = None

        _in_memory_store[key] = (str(value), time.time() + ex)
        return True

    async def get(self, key: str) -> Optional[str]:
        client = await self.get_client()
        if client:
            try:
                val = await client.get(key)
                if val is not None:
                    return val
            except Exception as e:
                logger.warning(f"Redis get failed ({e}), checking in-memory store")
                self._connected = False
                self._client = None

        # Check in-memory store
        item = _in_memory_store.get(key)
        if item:
            val, expire_at = item
            if time.time() < expire_at:
                return val
            else:
                del _in_memory_store[key]
        return None

    async def delete(self, key: str) -> bool:
        client = await self.get_client()
        if client:
            try:
                await client.delete(key)
            except Exception:
                pass

        if key in _in_memory_store:
            del _in_memory_store[key]
        return True


redis_client = ResumoRedisClient()
