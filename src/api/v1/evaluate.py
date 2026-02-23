"""Evaluation endpoints — submit and check evaluation status."""
import hashlib
import hmac
import logging
from datetime import datetime
from uuid import uuid4

import httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException

from src.storage.models import (
    EvaluateRequest,
    EvaluateResponse,
    EvaluationStatus,
    EvalStatus,
    EvalLevel,
    WebhookPayload,
)
from src.storage.mongodb import evaluations_col, scores_col, score_history_col
from src.core.evaluator import Evaluator
from src.core.llm_judge import LLMJudge
from src.core.attestation import create_attestation
from src.core.scoring import aggregate_scores
from src.core.question_pools import determine_tier
from src.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()

EVALUATION_VERSION = settings.evaluation_version


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
        "connection_strategy": "sse",
        "evaluation_version": EVALUATION_VERSION,
        "webhook_url": request.webhook_url,
        "callback_secret": request.callback_secret,
        "created_at": datetime.utcnow(),
    }
    await evaluations_col().insert_one(doc)

    background_tasks.add_task(
        _run_evaluation, evaluation_id, request
    )

    estimated = {EvalLevel.MANIFEST: 5, EvalLevel.FUNCTIONAL: 60, EvalLevel.DOMAIN_EXPERT: 180}
    message = "Webhook recommended over polling for Level 2+ evaluations" if request.level.value >= 2 else ""

    return EvaluateResponse(
        evaluation_id=evaluation_id,
        status=EvalStatus.PENDING,
        estimated_time_seconds=estimated.get(request.level, 60),
        poll_url=f"/v1/evaluate/{evaluation_id}",
        message=message,
    )


@router.get("/evaluate/{evaluation_id}", response_model=EvaluationStatus)
async def get_evaluation_status(evaluation_id: str):
    """Check the status of an evaluation and get full report when completed."""
    doc = await evaluations_col().find_one({"_id": evaluation_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Evaluation not found")

    result = None
    report = None
    score = None
    tier = None
    attestation_jwt = None
    badge_url = None

    if doc.get("status") == EvalStatus.COMPLETED.value and doc.get("scores"):
        from src.storage.models import ScoreResponse, QualityTier, TargetType
        scores = doc["scores"]
        score = scores.get("overall_score", 0)
        tier = scores.get("tier", "failed")

        result = ScoreResponse(
            target_id=doc["target_id"],
            target_type=TargetType(doc["target_type"]),
            score=score,
            tier=QualityTier(tier),
            confidence=scores.get("confidence", 0),
            domains=doc.get("domains", []),
            evaluation_version=doc.get("evaluation_version"),
        )

        report = doc.get("report")
        badge_url = f"{settings.base_url}/v1/badge/{doc['target_id']}.svg"

        if doc.get("attestation_id"):
            from src.storage.mongodb import attestations_col
            att = await attestations_col().find_one({"_id": doc["attestation_id"]})
            if att:
                attestation_jwt = att.get("attestation_jwt")

    return EvaluationStatus(
        evaluation_id=evaluation_id,
        status=EvalStatus(doc["status"]),
        progress_pct=doc.get("progress_pct", 0),
        score=score,
        tier=tier,
        evaluation_version=doc.get("evaluation_version"),
        report=report,
        attestation_jwt=attestation_jwt,
        badge_url=badge_url,
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
        # TODO: Fetch manifest via MCP Client (Strategy A: SSE/HTTP)
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
            report = {
                "level1": {
                    "manifest_score": manifest_result.score,
                    "checks": manifest_result.checks,
                    "issues": manifest_result.warnings,
                },
                "level2": None,
                "level3": None,
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
            report = {
                "level1": {
                    "manifest_score": manifest_result.score,
                    "checks": manifest_result.checks,
                    "issues": manifest_result.warnings,
                },
                "level2": {
                    "tools_tested": 0,
                    "tools_passed": 0,
                    "tools_failed": 0,
                    "avg_latency_ms": 0,
                    "tool_details": [],
                },
                "level3": None,
            }

        now = datetime.utcnow()

        # Create attestation
        attestation = create_attestation(
            target_id=request.target_url,
            target_type=request.target_type.value,
            target_name=manifest.get("name", request.target_url),
            evaluation_result=scores,
            evaluation_version=EVALUATION_VERSION,
        )
        attestation_id = attestation["_id"]
        from src.storage.mongodb import attestations_col
        await attestations_col().insert_one(attestation)

        await evaluations_col().update_one(
            {"_id": evaluation_id},
            {
                "$set": {
                    "status": EvalStatus.COMPLETED.value,
                    "scores": scores,
                    "report": report,
                    "completed_at": now,
                    "progress_pct": 100,
                    "attestation_id": attestation_id,
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
                    "evaluation_version": EVALUATION_VERSION,
                    "last_evaluated_at": now,
                },
                "$inc": {"evaluation_count": 1},
                "$setOnInsert": {"first_evaluated_at": now},
            },
            upsert=True,
        )

        # Record score history
        previous = await score_history_col().find_one(
            {"target_id": request.target_url},
            sort=[("recorded_at", -1)],
        )
        delta = scores["overall_score"] - previous["score"] if previous else None

        await score_history_col().insert_one({
            "target_id": request.target_url,
            "target_type": request.target_type.value,
            "evaluation_id": evaluation_id,
            "score": scores["overall_score"],
            "tier": scores["tier"],
            "confidence": scores["confidence"],
            "evaluation_version": EVALUATION_VERSION,
            "domain_scores": scores.get("domain_scores", {}),
            "recorded_at": now,
            "delta_from_previous": delta,
        })

        logger.info(f"Evaluation {evaluation_id} completed: score={scores['overall_score']}")

        # Deliver webhook if configured
        webhook_url = request.webhook_url
        if webhook_url:
            await _deliver_webhook(
                evaluation_id=evaluation_id,
                target_id=request.target_url,
                scores=scores,
                webhook_url=webhook_url,
                callback_secret=request.callback_secret,
                attestation_id=attestation_id,
            )

    except Exception as e:
        logger.error(f"Evaluation {evaluation_id} failed: {e}")
        await evaluations_col().update_one(
            {"_id": evaluation_id},
            {"$set": {"status": EvalStatus.FAILED.value, "error": str(e)}},
        )


async def _deliver_webhook(
    evaluation_id: str,
    target_id: str,
    scores: dict,
    webhook_url: str,
    callback_secret: str | None,
    attestation_id: str | None,
):
    """Deliver HMAC-signed webhook on evaluation completion."""
    payload = WebhookPayload(
        event="evaluation.completed",
        evaluation_id=evaluation_id,
        target_id=target_id,
        score=scores.get("overall_score", 0),
        tier=scores.get("tier", "failed"),
        report_url=f"{settings.base_url}/v1/evaluate/{evaluation_id}",
        badge_url=f"{settings.base_url}/v1/badge/{target_id}.svg",
        attestation_url=f"{settings.base_url}/v1/attestation/{attestation_id}" if attestation_id else None,
    )

    body = payload.model_dump_json()

    # HMAC signature if callback_secret provided
    signature = None
    if callback_secret:
        signature = hmac.new(
            callback_secret.encode(),
            body.encode(),
            hashlib.sha256,
        ).hexdigest()
        payload.signature = signature

    headers = {"Content-Type": "application/json"}
    if signature:
        headers["X-Quality-Oracle-Signature"] = f"sha256={signature}"

    try:
        async with httpx.AsyncClient(timeout=settings.webhook_timeout_seconds) as client:
            resp = await client.post(webhook_url, content=body, headers=headers)
            logger.info(f"Webhook delivered to {webhook_url}: status={resp.status_code}")
    except Exception as e:
        logger.warning(f"Webhook delivery failed for {evaluation_id}: {e}")
