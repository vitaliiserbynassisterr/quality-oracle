"""Tests for streaming evaluation pipeline and early termination."""
import pytest
from src.core.cancellation import CancellationToken
from src.core.evaluator import (
    Evaluator,
    EARLY_EXIT_MIN_SCORES,
    EARLY_EXIT_HIGH_THRESHOLD,
    EARLY_EXIT_LOW_THRESHOLD,
    EARLY_EXIT_MIN_LOW,
)
from src.core.llm_judge import LLMJudge


# ── CancellationToken ────────────────────────────────────────────────────────

def test_cancellation_token_initial_state():
    token = CancellationToken()
    assert not token.is_cancelled
    assert token.reason == ""


def test_cancellation_token_cancel():
    token = CancellationToken()
    token.cancel("test reason")
    assert token.is_cancelled
    assert token.reason == "test reason"


def test_cancellation_token_cancel_no_reason():
    token = CancellationToken()
    token.cancel()
    assert token.is_cancelled
    assert token.reason == ""


def test_cancellation_token_cancel_is_idempotent():
    token = CancellationToken()
    token.cancel("first")
    token.cancel("second")
    assert token.is_cancelled
    # First reason sticks since _cancelled was already True
    assert token.reason == "second"


# ── Progressive Confidence ───────────────────────────────────────────────────

def test_progressive_confidence_empty():
    assert Evaluator._compute_progressive_confidence([]) == 0.0


def test_progressive_confidence_few_scores():
    # With 2 scores, confidence = min(0.95, 2/30) = 0.067
    conf = Evaluator._compute_progressive_confidence([80, 80])
    assert 0.05 <= conf <= 0.10


def test_progressive_confidence_many_consistent_scores():
    # 30 identical scores → high confidence, no variance penalty
    scores = [75] * 30
    conf = Evaluator._compute_progressive_confidence(scores)
    assert conf == 0.95


def test_progressive_confidence_high_variance():
    # Scores with high variance should have lower confidence
    scores = [10, 90, 10, 90, 10, 90, 10, 90, 10, 90]
    conf = Evaluator._compute_progressive_confidence(scores)
    # stdev ~42.2, penalty ~0.17, sample_conf = 10/30 = 0.33, result ~0.16
    assert conf < 0.3


# ── Early Exit ───────────────────────────────────────────────────────────────

def test_early_exit_not_enough_scores():
    result = Evaluator._check_early_exit([90, 95])
    assert result is None  # Need at least EARLY_EXIT_MIN_SCORES


def test_early_exit_positive():
    scores = [90, 92, 88, 95]  # All >= 85
    assert len(scores) >= EARLY_EXIT_MIN_SCORES
    result = Evaluator._check_early_exit(scores)
    assert result is not None
    assert "positive_exit" in result


def test_early_exit_negative():
    scores = [10, 15, 5]  # All <= 30
    assert len(scores) >= EARLY_EXIT_MIN_LOW
    result = Evaluator._check_early_exit(scores)
    assert result is not None
    assert "negative_exit" in result


def test_early_exit_mixed_scores_no_exit():
    scores = [90, 30, 90, 30, 90]
    result = Evaluator._check_early_exit(scores)
    assert result is None  # Mixed scores → no early exit


def test_early_exit_borderline_no_positive():
    scores = [85, 86, 84, 87]  # One score below threshold
    result = Evaluator._check_early_exit(scores)
    assert result is None  # 84 < 85, not all above threshold


def test_early_exit_all_high_enough():
    scores = [85, 86, 87, 88]  # All >= 85
    result = Evaluator._check_early_exit(scores)
    assert result is not None
    assert "positive_exit" in result


# ── Streaming Eval Integration ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_streaming_eval_basic():
    """Test streaming evaluation with mock data."""
    judge = LLMJudge()  # Fuzzy fallback
    evaluator = Evaluator(llm_judge=judge, paraphrase=False)

    async def mock_stream():
        cases = [
            ("tool_a", {"question": "What is 2+2?", "expected": "4", "test_type": "basic"},
             {"content": "4", "is_error": False, "latency_ms": 50}),
            ("tool_a", {"question": "What is 3+3?", "expected": "6", "test_type": "basic"},
             {"content": "6", "is_error": False, "latency_ms": 60}),
            ("tool_b", {"question": "Echo hello", "expected": "hello", "test_type": "echo"},
             {"content": "hello", "is_error": False, "latency_ms": 30}),
        ]
        for item in cases:
            yield item

    result = await evaluator.evaluate_functional_streaming(
        target_id="test-server",
        response_stream=mock_stream(),
    )

    assert result.questions_asked == 3
    assert result.overall_score > 0
    assert "tool_a" in result.tool_scores
    assert "tool_b" in result.tool_scores
    assert result.tool_scores["tool_a"]["tests_total"] == 2
    assert result.tool_scores["tool_b"]["tests_total"] == 1


@pytest.mark.asyncio
async def test_streaming_eval_with_cancellation():
    """Test that cancellation stops streaming evaluation."""
    judge = LLMJudge()
    evaluator = Evaluator(llm_judge=judge, paraphrase=False)
    cancel = CancellationToken()

    calls = []

    async def mock_stream():
        for i in range(10):
            if cancel.is_cancelled:
                return
            calls.append(i)
            yield (
                "tool_a",
                {"question": f"Q{i}", "expected": "answer", "test_type": "basic"},
                {"content": "answer", "is_error": False, "latency_ms": 50},
            )
            # Cancel after 2 items
            if i == 1:
                cancel.cancel("test cancellation")

    result = await evaluator.evaluate_functional_streaming(
        target_id="test-server",
        response_stream=mock_stream(),
        cancel=cancel,
    )

    # Should have processed at most 2-3 items (cancel happens after yield of i=1)
    assert result.questions_asked <= 3
    assert cancel.is_cancelled


@pytest.mark.asyncio
async def test_streaming_eval_early_exit_high():
    """Test early exit with consistently high scores."""
    judge = LLMJudge()
    evaluator = Evaluator(llm_judge=judge, paraphrase=False)
    cancel = CancellationToken()

    async def mock_stream():
        # Yield many identical perfect-match cases
        for i in range(20):
            if cancel.is_cancelled:
                return
            yield (
                f"tool_{i % 3}",
                {"question": "exact match test", "expected": "exact match", "test_type": "basic"},
                {"content": "exact match", "is_error": False, "latency_ms": 50},
            )

    result = await evaluator.evaluate_functional_streaming(
        target_id="test-server",
        response_stream=mock_stream(),
        cancel=cancel,
    )

    # Should have exited early due to consistently high scores
    assert result.questions_asked < 20
    assert result.overall_score >= EARLY_EXIT_HIGH_THRESHOLD


@pytest.mark.asyncio
async def test_streaming_eval_progress_callback():
    """Test that progress callback is called."""
    judge = LLMJudge()
    evaluator = Evaluator(llm_judge=judge, paraphrase=False)
    progress_calls = []

    async def mock_stream():
        yield ("tool_a", {"question": "Q1", "expected": "A", "test_type": "basic"},
               {"content": "A", "is_error": False, "latency_ms": 50})
        yield ("tool_a", {"question": "Q2", "expected": "B", "test_type": "basic"},
               {"content": "B", "is_error": False, "latency_ms": 50})

    def on_progress(tool_name, idx, score, running_avg):
        progress_calls.append((tool_name, idx, score, running_avg))

    await evaluator.evaluate_functional_streaming(
        target_id="test-server",
        response_stream=mock_stream(),
        on_progress=on_progress,
    )

    assert len(progress_calls) == 2
    assert progress_calls[0][0] == "tool_a"
    assert progress_calls[1][1] == 2  # second call has idx=2
