"""Evaluation endpoints — submit and check evaluation status."""
import logging
from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, HTTPException

from src.storage.models import (
    EvaluateRequest,
    EvaluateResponse,
    EvaluationStatus,
    EvalStatus,
    EvalLevel,
)
from src.storage.mongodb import evaluations_col, scores_col
from src.core.evaluator import Evaluator
from src.core.llm_judge import LLMJudge
from src.core.attestation import create_attestation
from src.core.scoring import aggregate_scores
from src.core.question_pools import determine_tier
from src.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()


def _get_judge() -> LLMJudge:
    return LLMJudge(
        api_key=settings.deepseek_api_key or None,
        model=settings.deepseek_model,
        provider="deepseek",
        base_url=settings.deepseek_base_url,
        fallback_key=settings.groq_api_key or None,
        fallback_model=settings.groq_model,
    )


@router.post("/evaluate", response_model=EvaluateResponse)
async def submit_evaluation(
    request: EvaluateRequest,
    background_tasks: BackgroundTasks,
):
    """Submit an MCP server or agent for quality evaluation."""
    evaluation_id = str(uuid4())
    target_id = request.target_url  # Use URL as target_id for now

    doc = {
        "_id": evaluation_id,
        "target_id": target_id,
        "target_type": request.target_type.value,
        "target_url": request.target_url,
        "status": EvalStatus.PENDING.value,
        "level": request.level.value,
        "domains": request.domains,
        "webhook_url": request.webhook_url,
        "created_at": datetime.utcnow(),
    }
    await evaluations_col().insert_one(doc)

    background_tasks.add_task(
        _run_evaluation, evaluation_id, request
    )

    estimated = {EvalLevel.MANIFEST: 5, EvalLevel.FUNCTIONAL: 60, EvalLevel.DOMAIN_EXPERT: 180}
    return EvaluateResponse(
        evaluation_id=evaluation_id,
        status=EvalStatus.PENDING,
        estimated_time_seconds=estimated.get(request.level, 60),
    )


@router.get("/evaluate/{evaluation_id}", response_model=EvaluationStatus)
async def get_evaluation_status(evaluation_id: str):
    """Check the status of an evaluation."""
    doc = await evaluations_col().find_one({"_id": evaluation_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Evaluation not found")

    result = None
    if doc.get("status") == EvalStatus.COMPLETED.value and doc.get("scores"):
        from src.storage.models import ScoreResponse, QualityTier, TargetType
        scores = doc["scores"]
        result = ScoreResponse(
            target_id=doc["target_id"],
            target_type=TargetType(doc["target_type"]),
            score=scores.get("overall_score", 0),
            tier=QualityTier(scores.get("tier", "failed")),
            confidence=scores.get("confidence", 0),
            domains=doc.get("domains", []),
        )

    return EvaluationStatus(
        evaluation_id=evaluation_id,
        status=EvalStatus(doc["status"]),
        progress_pct=doc.get("progress_pct", 0),
        result=result,
        error=doc.get("error"),
    )


async def _run_evaluation(evaluation_id: str, request: EvaluateRequest):
    """Run evaluation in background."""
    try:
        await evaluations_col().update_one(
            {"_id": evaluation_id},
            {"$set": {"status": EvalStatus.RUNNING.value, "progress_pct": 10}},
        )

        judge = _get_judge()
        evaluator = Evaluator(judge)

        # Level 1: Manifest validation
        # TODO: Fetch manifest via MCP Client
        manifest = {"name": "test", "tools": [], "version": "0.1.0"}

        manifest_result = evaluator.validate_manifest(manifest)
        await evaluations_col().update_one(
            {"_id": evaluation_id},
            {"$set": {"progress_pct": 30}},
        )

        if request.level == EvalLevel.MANIFEST:
            scores = {
                "overall_score": manifest_result.score,
                "tier": determine_tier(manifest_result.score),
                "confidence": 0.5,
                "manifest": manifest_result.to_dict(),
            }
        else:
            # Level 2+: Functional testing
            # TODO: Connect to MCP server, call tools, collect responses
            scores = {
                "overall_score": manifest_result.score,
                "tier": determine_tier(manifest_result.score),
                "confidence": 0.5,
                "manifest": manifest_result.to_dict(),
                "tool_scores": {},
                "questions_asked": 0,
            }

        await evaluations_col().update_one(
            {"_id": evaluation_id},
            {
                "$set": {
                    "status": EvalStatus.COMPLETED.value,
                    "scores": scores,
                    "completed_at": datetime.utcnow(),
                    "progress_pct": 100,
                }
            },
        )

        # Update or create score record
        await scores_col().update_one(
            {"target_id": request.target_url},
            {
                "$set": {
                    "target_id": request.target_url,
                    "target_type": request.target_type.value,
                    "current_score": scores["overall_score"],
                    "tier": scores["tier"],
                    "confidence": scores["confidence"],
                    "last_evaluated_at": datetime.utcnow(),
                },
                "$inc": {"evaluation_count": 1},
            },
            upsert=True,
        )

        logger.info(f"Evaluation {evaluation_id} completed: score={scores['overall_score']}")

    except Exception as e:
        logger.error(f"Evaluation {evaluation_id} failed: {e}")
        await evaluations_col().update_one(
            {"_id": evaluation_id},
            {"$set": {"status": EvalStatus.FAILED.value, "error": str(e)}},
        )
