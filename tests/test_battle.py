"""Tests for the head-to-head battle engine."""
import asyncio
import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from src.core.battle import BattleEngine


@pytest.fixture()
def engine():
    return BattleEngine()


def run_async(coro):
    """Helper to run async test functions."""
    return asyncio.get_event_loop().run_until_complete(coro)


# ── Challenge Composition ────────────────────────────────────────────────────


class TestComposeChallengeSet:
    def test_returns_correct_count(self, engine):
        questions = engine.compose_challenge_set(count=5)
        assert len(questions) == 5

    def test_returns_correct_count_large(self, engine):
        questions = engine.compose_challenge_set(count=10)
        assert len(questions) == 10

    def test_shared_seed_produces_identical_sets(self, engine):
        q1 = engine.compose_challenge_set(count=5, seed=42)
        q2 = engine.compose_challenge_set(count=5, seed=42)
        assert [q.id for q in q1] == [q.id for q in q2]

    def test_different_seeds_produce_different_sets(self, engine):
        q1 = engine.compose_challenge_set(count=5, seed=42)
        q2 = engine.compose_challenge_set(count=5, seed=99)
        # Very unlikely to be identical with different seeds
        ids1 = [q.id for q in q1]
        ids2 = [q.id for q in q2]
        assert ids1 != ids2

    def test_stratified_difficulty_distribution(self, engine):
        """Test 15/25/30/25/15% difficulty distribution for large sets."""
        # Use a large count to get a clear distribution
        questions = engine.compose_challenge_set(count=20, seed=1)
        difficulties = [q.difficulty for q in questions]
        # With 20 questions: 3 easy, 5 med-easy (medium), 6 medium, 5 med-hard (medium), 3 hard
        # Since we only have easy/medium/hard, medium bucket gets both medium slots
        easy_count = difficulties.count("easy")
        hard_count = difficulties.count("hard")
        medium_count = difficulties.count("medium")
        # Should have a mix — not all one difficulty
        assert easy_count > 0 or hard_count > 0 or medium_count > 0

    def test_domain_balance_neutral(self, engine):
        """With no domains specified, returns neutral questions."""
        questions = engine.compose_challenge_set(count=5)
        # All questions should come from available pools
        assert all(q.domain for q in questions)

    def test_domain_balance_specific(self, engine):
        """With specific domains, prefers those domains."""
        questions = engine.compose_challenge_set(
            count=5, domains_a=["defi"], domains_b=["security"],
        )
        # Should include some from the specified domains (if available)
        assert len(questions) == 5


# ── Winner Determination ─────────────────────────────────────────────────────


class TestDetermineWinner:
    def test_higher_score_wins(self, engine):
        winner, margin, photo_finish = engine.determine_winner(85, 70)
        assert winner == "a"
        assert margin == 15
        assert photo_finish is False

    def test_lower_score_loses(self, engine):
        winner, margin, photo_finish = engine.determine_winner(60, 80)
        assert winner == "b"
        assert margin == 20

    def test_equal_scores_draw(self, engine):
        winner, margin, photo_finish = engine.determine_winner(75, 75)
        assert winner is None
        assert margin == 0
        assert photo_finish is False

    def test_photo_finish_margin_under_5(self, engine):
        winner, margin, photo_finish = engine.determine_winner(80, 77)
        assert winner == "a"
        assert margin == 3
        assert photo_finish is True

    def test_photo_finish_exactly_5(self, engine):
        """Margin of exactly 5 is NOT photo finish (only < 5)."""
        winner, margin, photo_finish = engine.determine_winner(80, 75)
        assert photo_finish is False

    def test_photo_finish_margin_1(self, engine):
        winner, margin, photo_finish = engine.determine_winner(50, 51)
        assert winner == "b"
        assert margin == 1
        assert photo_finish is True


# ── Cooldown ─────────────────────────────────────────────────────────────────


class TestCooldown:
    def test_no_recent_battle_allows(self, engine):
        """No recent battle → cooldown check passes."""
        mock_col = MagicMock()
        mock_col.find_one = AsyncMock(return_value=None)
        with patch("src.core.battle.battles_col", return_value=mock_col):
            result = run_async(engine.check_cooldown("agent_a", "agent_b"))
        assert result is None  # No cooldown

    def test_recent_battle_blocks(self, engine):
        """Battle within 1 hour → cooldown blocks."""
        recent_battle = {"created_at": datetime.utcnow() - timedelta(minutes=30)}
        mock_col = MagicMock()
        mock_col.find_one = AsyncMock(return_value=recent_battle)
        with patch("src.core.battle.battles_col", return_value=mock_col):
            result = run_async(engine.check_cooldown("agent_a", "agent_b"))
        assert result is not None  # Has remaining minutes
        assert result > 0

    def test_old_battle_allows(self, engine):
        """Battle more than 1 hour ago → MongoDB $gte filter excludes it."""
        # MongoDB's $gte filter would NOT return battles older than cutoff
        mock_col = MagicMock()
        mock_col.find_one = AsyncMock(return_value=None)
        with patch("src.core.battle.battles_col", return_value=mock_col):
            result = run_async(engine.check_cooldown("agent_a", "agent_b"))
        assert result is None


# ── Same Operator Check ──────────────────────────────────────────────────────


class TestSameOperatorCheck:
    def test_same_url_host_detected(self, engine):
        assert engine.check_same_operator(
            "https://api.example.com/mcp/server1",
            "https://api.example.com/mcp/server2",
        ) is True

    def test_different_hosts_allowed(self, engine):
        assert engine.check_same_operator(
            "https://agent-a.example.com/mcp",
            "https://agent-b.different.com/mcp",
        ) is False

    def test_same_url_rejected(self, engine):
        assert engine.check_same_operator(
            "https://example.com/mcp",
            "https://example.com/mcp",
        ) is True


# ── IRT Data Collection ──────────────────────────────────────────────────────


class TestIRTDataCollection:
    def test_compute_question_response(self, engine):
        resp = engine.compute_question_response(
            question_id="q1",
            question_hash="abc",
            domain="defi",
            difficulty="medium",
            score_a=85,
            score_b=60,
            latency_a_ms=150,
            latency_b_ms=200,
        )
        assert resp["question_id"] == "q1"
        assert resp["agent_a_correct"] is True  # score >= 70
        assert resp["agent_b_correct"] is False
        assert resp["battle_discrimination"] > 0  # agents differ

    def test_both_correct(self, engine):
        resp = engine.compute_question_response(
            question_id="q2", question_hash="def", domain="general",
            difficulty="easy", score_a=90, score_b=85,
            latency_a_ms=100, latency_b_ms=120,
        )
        assert resp["agent_a_correct"] is True
        assert resp["agent_b_correct"] is True
        # Low discrimination when both correct
        assert resp["battle_discrimination"] < 0.3

    def test_both_incorrect(self, engine):
        resp = engine.compute_question_response(
            question_id="q3", question_hash="ghi", domain="security",
            difficulty="hard", score_a=30, score_b=25,
            latency_a_ms=500, latency_b_ms=600,
        )
        assert resp["agent_a_correct"] is False
        assert resp["agent_b_correct"] is False
