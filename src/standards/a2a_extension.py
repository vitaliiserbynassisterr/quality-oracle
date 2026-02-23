"""A2A Agent Card quality extension schema.

Defines the quality_oracle extension format that other agents
can include in their A2A Agent Cards.
"""


def build_quality_extension(score_data: dict) -> dict:
    """Build the A2A Agent Card quality extension from a score record."""
    return {
        "quality_oracle": {
            "version": "1.0",
            "score": score_data.get("current_score", 0),
            "tier": score_data.get("tier", "unknown"),
            "confidence": score_data.get("confidence", 0),
            "last_evaluated": score_data.get("last_evaluated_at", "").isoformat()
            if score_data.get("last_evaluated_at") else None,
            "attestation_url": score_data.get("attestation_url"),
            "evaluation_count": score_data.get("evaluation_count", 0),
        }
    }
