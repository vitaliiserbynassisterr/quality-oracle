"""W3C Verifiable Credential attestation endpoints."""
from fastapi import APIRouter, HTTPException
from src.storage.mongodb import attestations_col

router = APIRouter()


@router.get("/attestation/{attestation_id}")
async def get_attestation(attestation_id: str):
    """Get a W3C Verifiable Credential quality attestation."""
    doc = await attestations_col().find_one({"_id": attestation_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Attestation not found")

    return doc.get("vc_document", doc)


@router.get("/attestation/{attestation_id}/verify")
async def verify_attestation(attestation_id: str):
    """Verify the validity of a quality attestation."""
    doc = await attestations_col().find_one({"_id": attestation_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Attestation not found")

    vc = doc.get("vc_document", {})
    return {
        "valid": not doc.get("revoked", False),
        "issuer": vc.get("issuer", ""),
        "issued_at": vc.get("issuanceDate", ""),
        "expires_at": vc.get("expirationDate", ""),
        "target_id": vc.get("credentialSubject", {}).get("id", ""),
        "quality_score": vc.get("credentialSubject", {}).get("qualityScore", 0),
        "tier": vc.get("credentialSubject", {}).get("tier", ""),
    }
