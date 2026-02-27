"""Tests for x402 payment layer, pricing model, and payment verification."""
import pytest
from src.payments.pricing import (
    get_price_quote,
    get_pricing_table,
    PriceQuote,
    PaymentReceipt,
    LEVEL_PRICES_USD,
    TIER_DISCOUNTS,
    ACCEPTED_TOKENS,
)
from src.payments.x402 import (
    build_402_response,
    parse_payment_header,
    verify_payment,
    require_payment,
    _usd_to_token_amount,
)


# ── Pricing Model ────────────────────────────────────────────────────────────

class TestPricingModel:

    def test_level_1_always_free(self):
        for tier in ["free", "developer", "team", "marketplace"]:
            quote = get_price_quote(1, tier)
            assert quote.is_free
            assert quote.final_price_usd == 0

    def test_level_2_base_price(self):
        quote = get_price_quote(2, "free")
        assert quote.base_price_usd == 0.01
        assert quote.final_price_usd == 0.01  # No discount for free tier

    def test_level_3_base_price(self):
        quote = get_price_quote(3, "free")
        assert quote.base_price_usd == 0.05
        assert quote.final_price_usd == 0.05

    def test_developer_discount(self):
        quote = get_price_quote(2, "developer")
        assert quote.discount_rate == 0.20
        assert quote.final_price_usd == 0.008  # 0.01 * 0.80

    def test_team_discount(self):
        quote = get_price_quote(3, "team")
        assert quote.discount_rate == 0.40
        assert quote.final_price_usd == 0.03  # 0.05 * 0.60

    def test_marketplace_discount(self):
        quote = get_price_quote(2, "marketplace")
        assert quote.discount_rate == 0.60
        assert quote.final_price_usd == 0.004  # 0.01 * 0.40

    def test_accepted_tokens(self):
        quote = get_price_quote(2, "free")
        assert "USDC" in quote.accepted_tokens
        assert "SOL" in quote.accepted_tokens

    def test_quote_to_dict(self):
        quote = get_price_quote(2, "free")
        d = quote.to_dict()
        assert d["level"] == 2
        assert "base_price_usd" in d
        assert "final_price_usd" in d
        assert "receiver_address" in d
        assert "accepted_tokens" in d

    def test_unknown_tier_no_discount(self):
        quote = get_price_quote(2, "unknown_tier")
        assert quote.discount_rate == 0.0
        assert quote.final_price_usd == 0.01

    def test_pricing_table(self):
        table = get_pricing_table("developer")
        assert len(table) == 3
        assert table[0]["level"] == 1
        assert table[0]["is_free"]
        assert table[1]["level"] == 2
        assert not table[1]["is_free"]
        assert table[2]["level"] == 3
        assert not table[2]["is_free"]

    def test_pricing_table_discounts_applied(self):
        free_table = get_pricing_table("free")
        team_table = get_pricing_table("team")
        # Level 2: team should be cheaper
        assert team_table[1]["final_price_usd"] < free_table[1]["final_price_usd"]


# ── Payment Receipt ──────────────────────────────────────────────────────────

class TestPaymentReceipt:

    def test_receipt_to_dict(self):
        receipt = PaymentReceipt(
            evaluation_id="eval-123",
            payer="wallet-abc",
            amount_usd=0.01,
            token="USDC",
            tx_signature="abc123def456",
            verified=True,
        )
        d = receipt.to_dict()
        assert d["evaluation_id"] == "eval-123"
        assert d["amount_usd"] == 0.01
        assert d["verified"]
        assert d["network"] == "solana"


# ── x402 Response Builder ────────────────────────────────────────────────────

class TestX402Response:

    def test_402_response_format(self):
        quote = get_price_quote(2, "free")
        resp = build_402_response(quote)
        assert resp["error"] == "payment_required"
        assert resp["status"] == 402
        assert resp["x402_version"] == "1"
        assert "payment_requirements" in resp
        assert len(resp["payment_requirements"]) >= 1

    def test_402_payment_requirements_have_fields(self):
        quote = get_price_quote(2, "free")
        resp = build_402_response(quote)
        req = resp["payment_requirements"][0]
        assert "network" in req
        assert "token" in req
        assert "amount" in req
        assert "amount_usd" in req
        assert "receiver" in req
        assert "mint" in req

    def test_402_includes_pricing(self):
        quote = get_price_quote(3, "developer")
        resp = build_402_response(quote)
        assert resp["pricing"]["level"] == 3
        assert resp["pricing"]["discount_rate"] == 0.20

    def test_custom_description(self):
        quote = get_price_quote(2, "free")
        resp = build_402_response(quote, description="Custom message")
        assert resp["description"] == "Custom message"

    def test_usdc_amount_conversion(self):
        # $0.01 in USDC = 10000 base units (6 decimals)
        amount = _usd_to_token_amount(0.01, "USDC")
        assert amount == "10000"

    def test_sol_amount_conversion(self):
        # SOL conversion should produce a valid integer string
        amount = _usd_to_token_amount(0.01, "SOL")
        assert int(amount) >= 0


# ── Payment Header Parser ────────────────────────────────────────────────────

class TestPaymentHeaderParser:

    def test_full_format(self):
        result = parse_payment_header("abc123:USDC:solana")
        assert result["tx_signature"] == "abc123"
        assert result["token"] == "USDC"
        assert result["network"] == "solana"

    def test_signature_only(self):
        result = parse_payment_header("abc123def456789")
        assert result["tx_signature"] == "abc123def456789"
        assert result["token"] == "USDC"  # Default
        assert result["network"] == "solana"  # Default

    def test_signature_and_token(self):
        result = parse_payment_header("abc123:SOL")
        assert result["tx_signature"] == "abc123"
        assert result["token"] == "SOL"
        assert result["network"] == "solana"


# ── Payment Verification ─────────────────────────────────────────────────────

class TestPaymentVerification:

    @pytest.mark.asyncio
    async def test_valid_signature_verified(self):
        receipt = await verify_payment(
            tx_signature="a" * 88,  # Solana tx sig length
            expected_amount_usd=0.01,
        )
        assert receipt.verified

    @pytest.mark.asyncio
    async def test_short_signature_rejected(self):
        receipt = await verify_payment(
            tx_signature="short",
            expected_amount_usd=0.01,
        )
        assert not receipt.verified

    @pytest.mark.asyncio
    async def test_empty_signature_rejected(self):
        receipt = await verify_payment(
            tx_signature="",
            expected_amount_usd=0.01,
        )
        assert not receipt.verified

    @pytest.mark.asyncio
    async def test_receipt_has_token_info(self):
        receipt = await verify_payment(
            tx_signature="a" * 88,
            expected_amount_usd=0.05,
            token="SOL",
            network="solana",
        )
        assert receipt.token == "SOL"
        assert receipt.network == "solana"
        assert receipt.amount_usd == 0.05


# ── require_payment Dependency ───────────────────────────────────────────────

class TestRequirePayment:

    @pytest.mark.asyncio
    async def test_free_level_no_payment_needed(self):
        result = await require_payment(level=1, tier="free", x_payment=None)
        assert result is None

    @pytest.mark.asyncio
    async def test_paid_level_no_header_returns_402(self):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await require_payment(level=2, tier="free", x_payment=None)
        assert exc_info.value.status_code == 402
        detail = exc_info.value.detail
        assert detail["error"] == "payment_required"
        assert "payment_requirements" in detail

    @pytest.mark.asyncio
    async def test_paid_level_with_valid_payment(self):
        receipt = await require_payment(
            level=2,
            tier="free",
            x_payment="a" * 88 + ":USDC:solana",
        )
        assert receipt is not None
        assert receipt.verified

    @pytest.mark.asyncio
    async def test_paid_level_with_invalid_payment(self):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await require_payment(level=2, tier="free", x_payment="bad")
        assert exc_info.value.status_code == 402
        assert exc_info.value.detail["error"] == "payment_verification_failed"


# ── API Integration ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_payments_router_registered():
    """Payments router should be registered in the app."""
    from src.main import app
    paths = [route.path for route in app.routes]
    assert "/v1/pricing" in paths
    assert any("/v1/pricing/" in p for p in paths)


@pytest.mark.asyncio
async def test_evaluate_endpoint_accepts_x_payment_header():
    """Evaluate endpoint should accept optional X-Payment header."""
    import inspect
    from src.api.v1.evaluate import submit_evaluation
    sig = inspect.signature(submit_evaluation)
    param_names = list(sig.parameters.keys())
    assert "x_payment" in param_names


@pytest.mark.asyncio
async def test_accepted_tokens_have_required_fields():
    """Each accepted token should have mint, decimals, network."""
    for token_name, info in ACCEPTED_TOKENS.items():
        assert "mint" in info, f"{token_name} missing mint"
        assert "decimals" in info, f"{token_name} missing decimals"
        assert "network" in info, f"{token_name} missing network"
