"""Redis cache for scores, rate limiting, and API key management."""
import logging
import redis.asyncio as redis

from src.config import settings

logger = logging.getLogger(__name__)

_redis: redis.Redis | None = None


async def connect_redis():
    global _redis
    _redis = redis.from_url(settings.redis_url, decode_responses=True)
    await _redis.ping()
    logger.info("Connected to Redis")


async def close_redis():
    global _redis
    if _redis:
        await _redis.close()
        logger.info("Redis connection closed")


def get_redis() -> redis.Redis:
    if _redis is None:
        raise RuntimeError("Redis not initialized. Call connect_redis() first.")
    return _redis


async def cache_score(target_id: str, score_data: dict, ttl: int = 300):
    """Cache a quality score for 5 minutes."""
    import json
    r = get_redis()
    await r.set(f"qo:score:{target_id}", json.dumps(score_data), ex=ttl)


async def get_cached_score(target_id: str) -> dict | None:
    """Get cached quality score."""
    import json
    r = get_redis()
    data = await r.get(f"qo:score:{target_id}")
    return json.loads(data) if data else None


async def check_rate_limit(api_key: str, limit: int) -> bool:
    """Check if API key is within rate limit. Returns True if allowed."""
    r = get_redis()
    key = f"qo:rate:{api_key}"
    current = await r.get(key)
    if current and int(current) >= limit:
        return False
    pipe = r.pipeline()
    pipe.incr(key)
    pipe.expire(key, 2592000)  # 30 days
    await pipe.execute()
    return True
