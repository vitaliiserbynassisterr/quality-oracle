"""Rate limiting middleware for API keys."""
from src.storage.cache import check_rate_limit

TIER_LIMITS = {
    "free": 10,
    "developer": 100,
    "team": 500,
    "marketplace": 999999,
}


async def is_rate_limited(api_key: str, tier: str) -> bool:
    """Check if an API key has exceeded its rate limit. Returns True if blocked."""
    limit = TIER_LIMITS.get(tier, 10)
    allowed = await check_rate_limit(api_key, limit)
    return not allowed
