"""Tests for A2A v0.3 extension builders and agent card format."""
import pytest
from datetime import datetime, timezone

from src.standards.a2a_extension import (
    EXTENSION_URI,
    build_provider_extension_declaration,
    build_consumer_extension_declaration,
)


# ── Extension URI ────────────────────────────────────────────────────────────

def test_extension_uri_format():
    assert EXTENSION_URI.startswith("https://")
    assert "/ext/evaluation/v1" in EXTENSION_URI


# ── Provider Extension ───────────────────────────────────────────────────────

def test_provider_extension_has_required_fields():
    ext = build_provider_extension_declaration()
    assert ext["uri"] == EXTENSION_URI
    assert "description" in ext
    assert ext["required"] is False
    assert "params" in ext


def test_provider_extension_role():
    ext = build_provider_extension_declaration()
    assert ext["params"]["role"] == "provider"


def test_provider_extension_capabilities():
    ext = build_provider_extension_declaration()
    params = ext["params"]
    assert params["evaluation_levels"] == [1, 2, 3]
    assert "mcp_server" in params["supported_targets"]
    assert "agent" in params["supported_targets"]
    assert "UAQA" in params["attestation_format"]


# ── Consumer Extension ───────────────────────────────────────────────────────

def test_consumer_extension_basic():
    score_data = {
        "current_score": 85,
        "tier": "expert",
        "confidence": 0.92,
        "target_id": "https://example.com/mcp",
    }
    ext = build_consumer_extension_declaration(score_data)
    assert ext["uri"] == EXTENSION_URI
    assert ext["params"]["role"] == "verified_subject"
    assert ext["params"]["score"] == 85
    assert ext["params"]["tier"] == "expert"
    assert ext["params"]["confidence"] == 0.92


def test_consumer_extension_with_datetime():
    now = datetime(2025, 10, 29, 12, 0, 0, tzinfo=timezone.utc)
    score_data = {
        "current_score": 75,
        "tier": "proficient",
        "confidence": 0.8,
        "last_evaluated_at": now,
        "target_id": "test-agent",
    }
    ext = build_consumer_extension_declaration(score_data)
    assert ext["params"]["last_evaluated"] == "2025-10-29T12:00:00+00:00"


def test_consumer_extension_missing_fields():
    """Handles missing fields gracefully with defaults."""
    ext = build_consumer_extension_declaration({})
    assert ext["params"]["score"] == 0
    assert ext["params"]["tier"] == "unknown"
    assert ext["params"]["confidence"] == 0
    assert ext["params"]["last_evaluated"] is None
    assert ext["params"]["verify_url"] == "/v1/score/"


def test_consumer_extension_with_urls():
    score_data = {
        "current_score": 90,
        "tier": "expert",
        "confidence": 0.95,
        "target_id": "my-server",
        "attestation_url": "https://example.com/attest/123",
        "badge_url": "https://example.com/badge/123.svg",
    }
    ext = build_consumer_extension_declaration(score_data)
    assert ext["params"]["attestation_url"] == "https://example.com/attest/123"
    assert ext["params"]["badge_url"] == "https://example.com/badge/123.svg"
    assert ext["params"]["verify_url"] == "/v1/score/my-server"


# ── Agent Card Format (A2A v0.3) ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_agent_card_v03_format():
    """Agent card should follow A2A v0.3 spec."""
    from src.api.agent_card import agent_card
    card = await agent_card()

    # Required top-level fields
    assert card["name"] == "Quality Oracle"
    assert "url" in card
    assert "version" in card
    assert "provider" in card

    # A2A v0.3: capabilities.extensions is an array
    capabilities = card["capabilities"]
    assert isinstance(capabilities["extensions"], list)
    assert len(capabilities["extensions"]) >= 1

    # Each extension has uri field
    ext = capabilities["extensions"][0]
    assert "uri" in ext
    assert ext["uri"] == EXTENSION_URI

    # A2A v0.3: defaultInputModes and defaultOutputModes
    assert "defaultInputModes" in card
    assert "defaultOutputModes" in card
    assert "application/json" in card["defaultInputModes"]


@pytest.mark.asyncio
async def test_agent_card_has_skills():
    from src.api.agent_card import agent_card
    card = await agent_card()
    assert "skills" in card
    skill_ids = [s["id"] for s in card["skills"]]
    assert "evaluate-quality" in skill_ids
    assert "lookup-score" in skill_ids
    assert "verify-attestation" in skill_ids


@pytest.mark.asyncio
async def test_extension_spec_endpoint():
    """Extension spec endpoint returns valid schema."""
    from src.api.agent_card import extension_spec
    spec = await extension_spec()

    assert "@context" in spec
    assert spec["name"] == "Quality Oracle Evaluation Extension"
    assert "provider" in spec["roles"]
    assert "verified_subject" in spec["roles"]
    assert "params_schema" in spec
    assert "provider" in spec["params_schema"]
    assert "verified_subject" in spec["params_schema"]


# ── Enrichment A2A v0.3 Format ──────────────────────────────────────────────

def test_enrichment_builds_extensions_array():
    """Consumer extension should be appendable to capabilities.extensions[]."""
    score_data = {
        "current_score": 80,
        "tier": "proficient",
        "confidence": 0.85,
        "target_id": "https://example.com",
    }

    # Simulate enrichment logic
    card = {"name": "test-agent", "capabilities": {"streaming": False}}
    enriched = dict(card)
    capabilities = enriched.get("capabilities", {})
    extensions = capabilities.get("extensions", [])
    extensions.append(build_consumer_extension_declaration(score_data))
    capabilities["extensions"] = extensions
    enriched["capabilities"] = capabilities

    # Verify A2A v0.3 format
    assert isinstance(enriched["capabilities"]["extensions"], list)
    assert len(enriched["capabilities"]["extensions"]) == 1
    ext = enriched["capabilities"]["extensions"][0]
    assert ext["uri"] == EXTENSION_URI
    assert ext["params"]["score"] == 80


def test_enrichment_preserves_existing_extensions():
    """Should append to existing extensions, not replace."""
    existing_ext = {"uri": "https://other.ext/v1", "description": "Other", "required": False, "params": {}}
    card = {"name": "test", "capabilities": {"extensions": [existing_ext]}}

    enriched = dict(card)
    capabilities = enriched.get("capabilities", {})
    extensions = capabilities.get("extensions", [])
    extensions.append(build_consumer_extension_declaration({"current_score": 70, "tier": "proficient", "confidence": 0.7, "target_id": "t"}))
    capabilities["extensions"] = extensions
    enriched["capabilities"] = capabilities

    assert len(enriched["capabilities"]["extensions"]) == 2
    assert enriched["capabilities"]["extensions"][0]["uri"] == "https://other.ext/v1"
    assert enriched["capabilities"]["extensions"][1]["uri"] == EXTENSION_URI
