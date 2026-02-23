"""
W3C Verifiable Credential issuance — Phase 2 (Week 5+).

Phase 1 uses JWT signing via src/core/attestation.py.
This module will wrap JWT attestations in W3C VC envelope
when integrating with SATI/ERC-8004.

For now, re-exports the Phase 1 JWT functions.
"""
from src.core.attestation import create_attestation, verify_attestation

__all__ = ["create_attestation", "verify_attestation"]
