"""API key management for Quality Oracle."""
import hashlib
import logging
import secrets
from datetime import datetime
from typing import Optional

from src.config import settings
from src.storage.mongodb import api_keys_col

logger = logging.getLogger(__name__)


def generate_api_key() -> str:
    """Generate a new API key."""
    return f"qo_{secrets.token_urlsafe(32)}"


def hash_api_key(key: str) -> str:
    """Hash an API key for storage."""
    salted = f"{settings.api_key_salt}:{key}"
    return hashlib.sha256(salted.encode()).hexdigest()


async def create_api_key(owner_email: str, tier: str = "free") -> dict:
    """Create a new API key and store it."""
    raw_key = generate_api_key()
    key_hash = hash_api_key(raw_key)

    doc = {
        "_id": key_hash,
        "key_prefix": raw_key[:10],
        "owner_email": owner_email,
        "tier": tier,
        "created_at": datetime.utcnow(),
        "last_used_at": None,
        "active": True,
        "used_this_month": 0,
    }
    await api_keys_col().insert_one(doc)

    logger.info(f"Created API key for {owner_email} (tier={tier})")
    return {"api_key": raw_key, "tier": tier}


async def validate_api_key(key: str) -> Optional[dict]:
    """Validate an API key. Returns key doc if valid, None if invalid."""
    key_hash = hash_api_key(key)
    doc = await api_keys_col().find_one({"_id": key_hash, "active": True})

    if doc:
        await api_keys_col().update_one(
            {"_id": key_hash},
            {"$set": {"last_used_at": datetime.utcnow()}},
        )

    return doc
