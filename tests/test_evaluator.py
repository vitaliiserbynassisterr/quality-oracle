"""Tests for the evaluation engine."""
import pytest
from src.core.evaluator import Evaluator, ManifestValidationResult
from src.core.llm_judge import LLMJudge
from src.core.question_pools import determine_tier


def test_determine_tier():
    assert determine_tier(90) == "expert"
    assert determine_tier(85) == "expert"
    assert determine_tier(75) == "proficient"
    assert determine_tier(70) == "proficient"
    assert determine_tier(60) == "basic"
    assert determine_tier(50) == "basic"
    assert determine_tier(49) == "failed"
    assert determine_tier(0) == "failed"


def test_manifest_validation_complete():
    evaluator = Evaluator(LLMJudge())
    manifest = {
        "name": "test-server",
        "version": "1.0.0",
        "description": "A test MCP server",
        "tools": [
            {
                "name": "search",
                "description": "Search for items",
                "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}},
            }
        ],
    }
    result = evaluator.validate_manifest(manifest)
    assert result.score == 100
    assert all(result.checks.values())
    assert len(result.warnings) == 0


def test_manifest_validation_empty():
    evaluator = Evaluator(LLMJudge())
    manifest = {}
    result = evaluator.validate_manifest(manifest)
    assert result.score < 50
    assert len(result.warnings) > 0


def test_manifest_validation_missing_descriptions():
    evaluator = Evaluator(LLMJudge())
    manifest = {
        "name": "test",
        "version": "1.0",
        "description": "Test",
        "tools": [
            {"name": "tool1"},  # No description
            {"name": "tool2", "description": "Has description"},
        ],
    }
    result = evaluator.validate_manifest(manifest)
    assert not result.checks["tools_have_descriptions"]
    assert any("missing descriptions" in w for w in result.warnings)


def test_fuzzy_judge():
    judge = LLMJudge()  # No API key = fuzzy only
    result = judge._judge_fuzzy(
        "What is TVL?",
        "Total Value Locked measures crypto assets in DeFi protocols",
        "TVL stands for Total Value Locked, measuring assets deposited in DeFi",
    )
    assert result.score > 50
    assert result.method == "fuzzy"


def test_fuzzy_judge_empty():
    judge = LLMJudge()
    result = judge._judge_fuzzy("What is TVL?", "Total Value Locked", "")
    assert result.score == 0
