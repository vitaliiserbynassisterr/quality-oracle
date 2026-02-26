"""Tests for process quality evaluation (6th scoring dimension)."""
import pytest
from src.core.process_quality import (
    ProcessQualityResult,
    analyze_process_quality,
    _score_error_response,
    _score_validation_response,
    _score_response_structure,
)


# ── Error handling scoring ───────────────────────────────────────────────────

class TestErrorHandlingScoring:

    def test_empty_response_scores_low(self):
        score = _score_error_response("", is_error=True)
        assert score <= 15

    def test_structured_json_error_scores_high(self):
        content = '{"error": "validation_error", "detail": "Field required: expression"}'
        score = _score_error_response(content, is_error=True)
        assert score >= 70

    def test_descriptive_text_error_scores_ok(self):
        content = "Error: missing required parameter 'query'. Please provide a valid search query."
        score = _score_error_response(content, is_error=True)
        assert score >= 60

    def test_traceback_leak_scores_low(self):
        content = "Traceback (most recent call last):\n  File 'server.py', line 42\nTypeError: NoneType"
        score = _score_error_response(content, is_error=True)
        assert score <= 30

    def test_generic_error_without_flag_scores_medium(self):
        content = "Something went wrong"
        score = _score_error_response(content, is_error=False)
        assert 20 <= score <= 50

    def test_error_flag_without_message(self):
        content = "Error occurred"
        score = _score_error_response(content, is_error=True)
        assert score >= 30


# ── Input validation scoring ─────────────────────────────────────────────────

class TestInputValidationScoring:

    def test_type_coercion_rejected_properly(self):
        content = '{"error": "invalid type", "expected": "number", "got": "string"}'
        score = _score_validation_response(content, is_error=True, test_type="type_coercion")
        assert score >= 70

    def test_type_coercion_accepted_silently(self):
        content = '{"result": 42}'
        score = _score_validation_response(content, is_error=False, test_type="type_coercion")
        assert score <= 50

    def test_edge_case_empty_rejected(self):
        content = "Error: empty input is not allowed"
        score = _score_validation_response(content, is_error=True, test_type="edge_case")
        assert score >= 60

    def test_edge_case_graceful_default(self):
        content = '{"result": "default_value", "note": "empty input provided"}'
        score = _score_validation_response(content, is_error=False, test_type="edge_case")
        assert score >= 40

    def test_boundary_oversized_rejected(self):
        content = "Input exceeds maximum length limit of 10000 characters"
        score = _score_validation_response(content, is_error=True, test_type="boundary")
        assert score >= 70

    def test_boundary_crash(self):
        content = "Traceback: segfault in processing"
        score = _score_validation_response(content, is_error=True, test_type="boundary")
        assert score <= 10

    def test_empty_validation_response(self):
        score = _score_validation_response("", is_error=False, test_type="type_coercion")
        assert score <= 15


# ── Response structure scoring ───────────────────────────────────────────────

class TestResponseStructureScoring:

    def test_valid_json_object_scores_high(self):
        content = '{"city": "London", "temperature_c": 15, "condition": "cloudy"}'
        score = _score_response_structure(content)
        assert score >= 65

    def test_valid_json_array(self):
        content = '[{"id": 1, "name": "test"}]'
        score = _score_response_structure(content)
        assert score >= 50

    def test_plain_text_short(self):
        content = "42"
        score = _score_response_structure(content)
        assert 20 <= score <= 50

    def test_plain_text_long(self):
        content = "This is a detailed response with plenty of information about the requested topic."
        score = _score_response_structure(content)
        assert score >= 30

    def test_empty_response(self):
        score = _score_response_structure("")
        assert score <= 15

    def test_json_with_consistent_snake_case(self):
        content = '{"user_name": "john", "email_address": "john@test.com", "is_active": true}'
        score = _score_response_structure(content)
        assert score >= 70

    def test_single_field_json(self):
        content = '{"result": 42}'
        score = _score_response_structure(content)
        assert score >= 45


# ── Full analysis integration ────────────────────────────────────────────────

class TestAnalyzeProcessQuality:

    def test_all_good_responses(self):
        """Server with good error handling, validation, and structure."""
        tool_responses = {
            "search": [
                {
                    "question": "Use 'search'",
                    "expected": "Return results",
                    "answer": '{"results": [{"id": 1, "title": "test"}], "total": 1}',
                    "is_error": False,
                    "test_type": "happy_path",
                    "latency_ms": 100,
                },
                {
                    "question": "Call 'search' without 'query'",
                    "expected": "Should return error",
                    "answer": '{"error": "validation_error", "detail": "Missing required parameter: query"}',
                    "is_error": True,
                    "test_type": "error_handling",
                    "latency_ms": 50,
                },
                {
                    "question": "Call 'search' with empty query",
                    "expected": "Handle empty input",
                    "answer": '{"error": "invalid_input", "detail": "Query must not be empty"}',
                    "is_error": True,
                    "test_type": "edge_case",
                    "latency_ms": 45,
                },
                {
                    "question": "Call 'search' with string for 'limit'",
                    "expected": "Reject invalid type",
                    "answer": '{"error": "type_error", "detail": "Expected integer for limit, got string"}',
                    "is_error": True,
                    "test_type": "type_coercion",
                    "latency_ms": 40,
                },
            ]
        }
        result = analyze_process_quality(tool_responses)
        assert result.score >= 60
        assert result.error_handling >= 60
        assert result.input_validation >= 60
        assert result.response_structure >= 50

    def test_all_bad_responses(self):
        """Server that crashes on errors and returns unstructured output."""
        tool_responses = {
            "calc": [
                {
                    "question": "Use 'calc'",
                    "expected": "Return result",
                    "answer": "42",
                    "is_error": False,
                    "test_type": "happy_path",
                    "latency_ms": 100,
                },
                {
                    "question": "Call 'calc' without params",
                    "expected": "Should error",
                    "answer": "Traceback (most recent call last):\n  TypeError: NoneType has no attribute 'get'",
                    "is_error": True,
                    "test_type": "error_handling",
                    "latency_ms": 50,
                },
                {
                    "question": "Call 'calc' with string",
                    "expected": "Reject type",
                    "answer": "",
                    "is_error": True,
                    "test_type": "type_coercion",
                    "latency_ms": 40,
                },
            ]
        }
        result = analyze_process_quality(tool_responses)
        assert result.score < 40
        assert result.error_handling < 30

    def test_empty_responses(self):
        """No tool responses — should return neutral scores."""
        result = analyze_process_quality({})
        assert result.score == 50
        assert result.error_handling == 50
        assert result.input_validation == 50

    def test_only_happy_path(self):
        """Only happy path responses — validation/error are neutral."""
        tool_responses = {
            "tool": [
                {
                    "question": "Use 'tool'",
                    "expected": "Return data",
                    "answer": '{"data": "value", "status": "ok"}',
                    "is_error": False,
                    "test_type": "happy_path",
                    "latency_ms": 100,
                },
            ]
        }
        result = analyze_process_quality(tool_responses)
        # error_handling and input_validation = 50 (neutral, no data)
        assert result.error_handling == 50
        assert result.input_validation == 50
        # response_structure should be scored from happy path
        assert result.response_structure >= 50

    def test_result_to_dict(self):
        result = ProcessQualityResult(
            score=72,
            error_handling=80,
            input_validation=65,
            response_structure=70,
            details={"samples": "5"},
        )
        d = result.to_dict()
        assert d["score"] == 72
        assert d["error_handling"] == 80
        assert d["input_validation"] == 65
        assert d["response_structure"] == 70
        assert d["details"]["samples"] == "5"

    def test_multiple_tools_aggregated(self):
        """Scores from multiple tools are averaged together."""
        tool_responses = {
            "tool_a": [
                {
                    "question": "test",
                    "expected": "error",
                    "answer": '{"error": "missing required field: name"}',
                    "is_error": True,
                    "test_type": "error_handling",
                    "latency_ms": 50,
                },
            ],
            "tool_b": [
                {
                    "question": "test",
                    "expected": "error",
                    "answer": "",
                    "is_error": True,
                    "test_type": "error_handling",
                    "latency_ms": 50,
                },
            ],
        }
        result = analyze_process_quality(tool_responses)
        # One good (>60) + one bad (10) = average should be moderate
        assert 20 <= result.error_handling <= 55

    def test_boundary_response_handled(self):
        tool_responses = {
            "tool": [
                {
                    "question": "Long input test",
                    "expected": "Handle gracefully",
                    "answer": "Error: input too long, maximum 10000 characters allowed",
                    "is_error": True,
                    "test_type": "boundary",
                    "latency_ms": 30,
                },
            ]
        }
        result = analyze_process_quality(tool_responses)
        assert result.input_validation >= 70


# ── Integration with evaluator (6-axis) ─────────────────────────────────────

@pytest.mark.asyncio
async def test_evaluate_full_has_6_dimensions():
    """evaluate_full() should include process_quality as 6th dimension."""
    from src.core.evaluator import Evaluator
    from src.core.llm_judge import LLMJudge

    evaluator = Evaluator(LLMJudge(), paraphrase=False)
    tool_responses = {
        "search": [
            {
                "question": "Use search with query='test'",
                "expected": "Should return results",
                "answer": '{"results": [], "total": 0}',
                "is_error": False,
                "test_type": "happy_path",
                "latency_ms": 100,
            },
            {
                "question": "Use search variation",
                "expected": "Should return results",
                "answer": '{"results": [{"id": 1}], "total": 1}',
                "is_error": False,
                "test_type": "happy_path_variation",
                "latency_ms": 120,
            },
            {
                "question": "Call search without query",
                "expected": "Should return error",
                "answer": '{"error": "missing_field", "detail": "query is required"}',
                "is_error": True,
                "test_type": "error_handling",
                "latency_ms": 50,
            },
            {
                "question": "Call search with empty query",
                "expected": "Handle edge case",
                "answer": '{"error": "invalid_input", "message": "Query cannot be empty"}',
                "is_error": True,
                "test_type": "edge_case",
                "latency_ms": 45,
            },
        ],
    }

    manifest = {
        "name": "test-server",
        "version": "1.0",
        "description": "Test",
        "tools": [{"name": "search", "description": "Search", "inputSchema": {}}],
    }

    result = await evaluator.evaluate_full(
        target_id="test-server",
        server_url="http://fake:1234",
        tool_responses=tool_responses,
        manifest=manifest,
        run_safety=False,
    )

    # Should have 6 dimensions
    assert result.dimensions is not None
    assert len(result.dimensions) == 6
    assert "process_quality" in result.dimensions

    # Weights should sum to 1.0
    total_weight = sum(d["weight"] for d in result.dimensions.values())
    assert abs(total_weight - 1.0) < 0.01

    # Process quality report should be populated
    assert result.process_quality_report is not None
    assert "error_handling" in result.process_quality_report
    assert "input_validation" in result.process_quality_report
    assert "response_structure" in result.process_quality_report


@pytest.mark.asyncio
async def test_evaluate_full_process_quality_affects_score():
    """Process quality dimension should affect the overall score."""
    from src.core.evaluator import Evaluator
    from src.core.llm_judge import LLMJudge

    evaluator = Evaluator(LLMJudge(), paraphrase=False)

    # Good process quality responses
    good_responses = {
        "tool": [
            {"question": "test", "expected": "result", "answer": '{"data": "ok"}',
             "is_error": False, "test_type": "happy_path", "latency_ms": 100},
            {"question": "error test", "expected": "error msg",
             "answer": '{"error": "validation", "detail": "Missing required field: name"}',
             "is_error": True, "test_type": "error_handling", "latency_ms": 50},
            {"question": "type test", "expected": "reject",
             "answer": '{"error": "type_error", "detail": "Expected integer, got string"}',
             "is_error": True, "test_type": "type_coercion", "latency_ms": 40},
        ],
    }

    # Bad process quality responses
    bad_responses = {
        "tool": [
            {"question": "test", "expected": "result", "answer": "42",
             "is_error": False, "test_type": "happy_path", "latency_ms": 100},
            {"question": "error test", "expected": "error msg",
             "answer": "Traceback: KeyError in server.py",
             "is_error": True, "test_type": "error_handling", "latency_ms": 50},
            {"question": "type test", "expected": "reject", "answer": "",
             "is_error": True, "test_type": "type_coercion", "latency_ms": 40},
        ],
    }

    result_good = await evaluator.evaluate_full(
        "test-good", "http://fake:1", good_responses, run_safety=False,
    )
    result_bad = await evaluator.evaluate_full(
        "test-bad", "http://fake:2", bad_responses, run_safety=False,
    )

    # Good process quality should have higher process_quality dimension score
    assert result_good.dimensions["process_quality"]["score"] > result_bad.dimensions["process_quality"]["score"]
