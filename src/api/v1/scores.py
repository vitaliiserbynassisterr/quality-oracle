"""Score lookup endpoints."""
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from src.storage.mongodb import scores_col
from src.storage.cache import get_cached_score, cache_score
from src.storage.models import ScoreResponse, QualityTier, TargetType

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/score/{target_id:path}", response_model=ScoreResponse)
async def get_score(target_id: str):
    """Get the quality score for a target (MCP server, agent, or skill)."""
    # Check cache first
    cached = await get_cached_score(target_id)
    if cached:
        return ScoreResponse(**cached)

    # Lookup in MongoDB
    doc = await scores_col().find_one({"target_id": target_id})
    if not doc:
        raise HTTPException(status_code=404, detail="No quality score found for this target")

    response = ScoreResponse(
        target_id=doc["target_id"],
        target_type=TargetType(doc.get("target_type", "mcp_server")),
        score=doc.get("current_score", 0),
        tier=QualityTier(doc.get("tier", "failed")),
        confidence=doc.get("confidence", 0),
        evaluation_count=doc.get("evaluation_count", 0),
        last_evaluated_at=doc.get("last_evaluated_at"),
    )

    # Cache for 5 min
    await cache_score(target_id, response.model_dump(mode="json"))

    return response


@router.get("/scores")
async def list_scores(
    domain: Optional[str] = None,
    min_score: int = Query(0, ge=0, le=100),
    tier: Optional[str] = None,
    sort: str = Query("score", regex="^(score|name|date)$"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """List quality scores with filtering and pagination."""
    query = {}
    if min_score > 0:
        query["current_score"] = {"$gte": min_score}
    if tier:
        query["tier"] = tier

    sort_field = {"score": "current_score", "date": "last_evaluated_at", "name": "target_id"}
    sort_key = sort_field.get(sort, "current_score")
    sort_dir = -1 if sort != "name" else 1

    cursor = scores_col().find(query).sort(sort_key, sort_dir).skip(offset).limit(limit)
    items = []
    async for doc in cursor:
        items.append({
            "target_id": doc["target_id"],
            "target_type": doc.get("target_type", "mcp_server"),
            "score": doc.get("current_score", 0),
            "tier": doc.get("tier", "failed"),
            "evaluation_count": doc.get("evaluation_count", 0),
            "last_evaluated_at": doc.get("last_evaluated_at"),
        })

    total = await scores_col().count_documents(query)

    return {"items": items, "total": total, "limit": limit, "offset": offset}
