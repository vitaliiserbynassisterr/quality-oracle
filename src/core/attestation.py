"""
W3C Verifiable Credential issuance for quality attestations.

Issues UAQA (Universal Agent Quality Attestation) format credentials.
"""
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)


def create_attestation(
    target_id: str,
    target_type: str,
    target_name: str,
    evaluation_result: dict,
    issuer_did: str = "did:web:quality-oracle.assisterr.ai",
    validity_days: int = 30,
) -> dict:
    """
    Create a W3C Verifiable Credential quality attestation (UAQA format).

    Args:
        target_id: ID of the evaluated target
        target_type: Type (mcp_server, agent, skill)
        target_name: Human-readable name
        evaluation_result: Evaluation result dict
        issuer_did: DID of the issuer
        validity_days: How long the attestation is valid

    Returns:
        W3C VC document in UAQA format
    """
    now = datetime.utcnow()
    attestation_id = str(uuid4())

    vc = {
        "@context": [
            "https://www.w3.org/2018/credentials/v1",
            "https://quality-oracle.assisterr.ai/schemas/v1",
        ],
        "id": f"urn:uuid:{attestation_id}",
        "type": ["VerifiableCredential", "AgentQualityAttestation"],
        "issuer": issuer_did,
        "issuanceDate": now.isoformat() + "Z",
        "expirationDate": (now + timedelta(days=validity_days)).isoformat() + "Z",
        "credentialSubject": {
            "id": target_id,
            "type": target_type,
            "name": target_name,
            "qualityScore": evaluation_result.get("overall_score", 0),
            "tier": evaluation_result.get("tier", "failed"),
            "confidence": evaluation_result.get("confidence", 0),
            "evaluationMethod": "challenge-response-v1",
            "questionsAsked": evaluation_result.get("questions_asked", 0),
            "toolScores": evaluation_result.get("tool_scores", {}),
            "domainScores": evaluation_result.get("domain_scores", {}),
            "durationMs": evaluation_result.get("duration_ms", 0),
            "resultHash": evaluation_result.get("result_hash", ""),
            "evaluatedAt": now.isoformat() + "Z",
        },
    }

    logger.info(f"Created attestation {attestation_id} for {target_id}: score={vc['credentialSubject']['qualityScore']}")
    return vc
