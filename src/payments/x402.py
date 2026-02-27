"""
x402 Protocol implementation for Quality Oracle.

The x402 protocol uses HTTP 402 Payment Required to gate API access.
Flow:
1. Client sends request without payment
2. Server returns 402 with payment details (price, receiver, tokens)
3. Client makes payment (e.g., Solana SPL transfer)
4. Client retries request with X-Payment header containing tx signature
5. Server verifies payment and processes request

This module provides:
- x402 response builder (402 Payment Required with payment instructions)
- Payment header parser (X-Payment)
- Payment verification dependency for FastAPI
- Payment receipt storage
- Pricing endpoint

x402 spec reference: https://x402.org
Solana has 77% of x402 payment volume.
"""
import logging
from datetime import datetime
from typing import Optional
from uuid import uuid4

from fastapi import Header, HTTPException, Request

from src.payments.pricing import (
    PriceQuote,
    PaymentReceipt,
    get_price_quote,
    ACCEPTED_TOKENS,
)

logger = logging.getLogger(__name__)


# ── x402 Response Builder ────────────────────────────────────────────────────

def build_402_response(
    quote: PriceQuote,
    description: str = "Payment required for evaluation",
) -> dict:
    """Build x402-compliant 402 Payment Required response body.

    Per x402 spec, the response includes:
    - paymentRequirements: array of accepted payment methods
    - description: human-readable explanation
    - resource: what the payment grants access to
    """
    payment_requirements = []
    for token_name in quote.accepted_tokens:
        token_info = ACCEPTED_TOKENS.get(token_name, {})
        payment_requirements.append({
            "type": "exact",
            "network": token_info.get("network", "solana"),
            "token": token_name,
            "mint": token_info.get("mint", ""),
            "decimals": token_info.get("decimals", 6),
            "amount": _usd_to_token_amount(quote.final_price_usd, token_name),
            "amount_usd": quote.final_price_usd,
            "receiver": quote.receiver_address,
        })

    return {
        "error": "payment_required",
        "status": 402,
        "description": description,
        "x402_version": "1",
        "payment_requirements": payment_requirements,
        "resource": f"evaluation/level-{quote.level}",
        "pricing": quote.to_dict(),
    }


def _usd_to_token_amount(usd: float, token: str) -> str:
    """Convert USD amount to token base units (string for precision).

    For USDC: 1 USD = 1_000_000 base units (6 decimals)
    For SOL: approximate at $150/SOL (will be dynamic in production)
    """
    token_info = ACCEPTED_TOKENS.get(token, {})
    decimals = token_info.get("decimals", 6)

    if token == "USDC":
        # 1:1 with USD
        return str(int(usd * (10 ** decimals)))
    elif token == "SOL":
        # Approximate conversion (production would use price oracle)
        sol_price = 150.0  # Placeholder — use Pyth/Switchboard in production
        sol_amount = usd / sol_price
        return str(int(sol_amount * (10 ** decimals)))
    else:
        return str(int(usd * (10 ** decimals)))


# ── Payment Header Parser ────────────────────────────────────────────────────

def parse_payment_header(header_value: str) -> dict:
    """Parse X-Payment header from client.

    Expected format (x402 spec):
        X-Payment: <tx_signature>:<token>:<network>

    Or simplified:
        X-Payment: <tx_signature>

    Returns dict with tx_signature, token, network.
    """
    parts = header_value.strip().split(":")
    result = {
        "tx_signature": parts[0],
        "token": parts[1] if len(parts) > 1 else "USDC",
        "network": parts[2] if len(parts) > 2 else "solana",
    }
    return result


# ── Payment Verification ─────────────────────────────────────────────────────

async def verify_payment(
    tx_signature: str,
    expected_amount_usd: float,
    token: str = "USDC",
    network: str = "solana",
) -> PaymentReceipt:
    """Verify a payment transaction.

    In production, this would:
    1. Query Solana RPC for the transaction
    2. Verify recipient matches our receiver address
    3. Verify amount >= expected
    4. Verify token mint matches
    5. Verify transaction is finalized

    For now, returns a receipt with verified=True for valid-looking signatures,
    or verified=False for obviously invalid ones.
    """
    # Basic validation
    if not tx_signature or len(tx_signature) < 10:
        return PaymentReceipt(
            evaluation_id="",
            payer="unknown",
            amount_usd=expected_amount_usd,
            token=token,
            tx_signature=tx_signature,
            network=network,
            verified=False,
        )

    # In production: query Solana RPC here
    # For development: accept any well-formed signature
    # A real Solana tx signature is 88 base58 chars
    is_valid_format = len(tx_signature) >= 32 and tx_signature.isalnum()

    logger.info(
        f"Payment verification: tx={tx_signature[:16]}... "
        f"amount=${expected_amount_usd} token={token} "
        f"verified={is_valid_format}"
    )

    return PaymentReceipt(
        evaluation_id="",
        payer="unknown",  # Would extract from tx in production
        amount_usd=expected_amount_usd,
        token=token,
        tx_signature=tx_signature,
        network=network,
        verified=is_valid_format,
    )


# ── FastAPI Dependency ────────────────────────────────────────────────────────

async def require_payment(
    level: int,
    tier: str,
    x_payment: Optional[str] = None,
) -> Optional[PaymentReceipt]:
    """FastAPI dependency that enforces x402 payment for paid evaluations.

    Returns:
        None if evaluation is free
        PaymentReceipt if payment was provided and verified

    Raises:
        HTTPException(402) if payment is required but not provided
        HTTPException(402) if payment verification fails
    """
    quote = get_price_quote(level, tier)

    if quote.is_free:
        return None

    if not x_payment:
        raise HTTPException(
            status_code=402,
            detail=build_402_response(
                quote,
                description=f"Payment required for Level {level} evaluation. "
                           f"Price: ${quote.final_price_usd} USD",
            ),
        )

    # Parse and verify payment
    payment_info = parse_payment_header(x_payment)
    receipt = await verify_payment(
        tx_signature=payment_info["tx_signature"],
        expected_amount_usd=quote.final_price_usd,
        token=payment_info["token"],
        network=payment_info["network"],
    )

    if not receipt.verified:
        raise HTTPException(
            status_code=402,
            detail={
                "error": "payment_verification_failed",
                "status": 402,
                "description": "Payment could not be verified. "
                              "Ensure the transaction is finalized.",
                "tx_signature": payment_info["tx_signature"],
                "x402_version": "1",
                "payment_requirements": build_402_response(quote)["payment_requirements"],
            },
        )

    return receipt
