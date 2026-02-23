"""MongoDB connection and collection accessors for Quality Oracle."""
import logging
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from src.config import settings

logger = logging.getLogger(__name__)

_client: AsyncIOMotorClient | None = None
_db: AsyncIOMotorDatabase | None = None


async def connect_db():
    global _client, _db
    _client = AsyncIOMotorClient(settings.mongodb_uri)
    _db = _client[settings.mongodb_database]
    # Create indexes
    await _db.quality__evaluations.create_index("target_id")
    await _db.quality__evaluations.create_index("status")
    await _db.quality__scores.create_index("target_id", unique=True)
    await _db.quality__attestations.create_index("evaluation_id")
    logger.info(f"Connected to MongoDB: {settings.mongodb_database}")


async def close_db():
    global _client
    if _client:
        _client.close()
        logger.info("MongoDB connection closed")


def get_db() -> AsyncIOMotorDatabase:
    if _db is None:
        raise RuntimeError("Database not initialized. Call connect_db() first.")
    return _db


# Collection accessors
def evaluations_col():
    return get_db().quality__evaluations


def scores_col():
    return get_db().quality__scores


def attestations_col():
    return get_db().quality__attestations


def question_banks_col():
    return get_db().quality__question_banks


def api_keys_col():
    return get_db().quality__api_keys
