"""Score aggregation and tier calculation."""
from typing import Dict, List, Optional
from src.core.question_pools import determine_tier


def aggregate_scores(
    tool_scores: Dict[str, dict],
    domain_scores: Dict[str, dict] | None = None,
    manifest_score: int | None = None,
) -> dict:
    """
    Aggregate individual scores into overall quality score.

    Weighting:
    - Manifest (Level 1): 10% of overall (if present)
    - Functional (Level 2): 60% of overall
    - Domain (Level 3): 30% of overall (if present)
    """
    weights = {"manifest": 0.0, "functional": 1.0, "domain": 0.0}

    # Determine if this is L1-only (no functional tests ran)
    l1_only = manifest_score is not None and not tool_scores

    if l1_only:
        # L1 only: manifest is the entire score (capped with confidence penalty)
        weights = {"manifest": 1.0, "functional": 0.0, "domain": 0.0}
    elif manifest_score is not None and domain_scores:
        weights = {"manifest": 0.10, "functional": 0.60, "domain": 0.30}
    elif manifest_score is not None:
        weights = {"manifest": 0.15, "functional": 0.85, "domain": 0.0}
    elif domain_scores:
        weights = {"manifest": 0.0, "functional": 0.65, "domain": 0.35}

    # Functional score from tool scores
    if tool_scores:
        func_scores = [t["score"] for t in tool_scores.values()]
        functional_score = sum(func_scores) / len(func_scores)
    else:
        functional_score = 0

    # Domain score
    if domain_scores:
        dom_scores = [d["score"] for d in domain_scores.values()]
        domain_score = sum(dom_scores) / len(dom_scores)
    else:
        domain_score = 0

    overall = (
        (manifest_score or 0) * weights["manifest"]
        + functional_score * weights["functional"]
        + domain_score * weights["domain"]
    )
    overall = int(round(overall))

    return {
        "overall_score": overall,
        "tier": determine_tier(overall),
        "functional_score": int(functional_score),
        "domain_score": int(domain_score) if domain_scores else None,
        "manifest_score": manifest_score,
        "weights": weights,
    }


def calculate_trend(scores_history: List[int]) -> str:
    """Determine score trend from history."""
    if len(scores_history) < 2:
        return "stable"
    recent = scores_history[-3:]
    if all(recent[i] <= recent[i + 1] for i in range(len(recent) - 1)):
        return "improving"
    if all(recent[i] >= recent[i + 1] for i in range(len(recent) - 1)):
        return "declining"
    return "stable"
