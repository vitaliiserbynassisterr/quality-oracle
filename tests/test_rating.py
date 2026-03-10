"""Tests for the OpenSkill rating engine."""
import pytest
from src.core.rating import RatingEngine


@pytest.fixture()
def engine():
    return RatingEngine()


class TestNewRating:
    def test_default_mu(self, engine):
        r = engine.new_rating()
        assert r.mu == 25.0

    def test_default_sigma(self, engine):
        r = engine.new_rating()
        assert abs(r.sigma - 8.333) < 0.01

    def test_new_ratings_are_independent(self, engine):
        r1 = engine.new_rating()
        r2 = engine.new_rating()
        assert r1 is not r2


class TestPredictWin:
    def test_equal_ratings_50_50(self, engine):
        r1 = engine.new_rating()
        r2 = engine.new_rating()
        prob = engine.predict_win(r1, r2)
        assert abs(prob - 0.5) < 0.01

    def test_stronger_player_favored(self, engine):
        strong = engine.new_rating()
        strong.mu = 35.0
        weak = engine.new_rating()
        weak.mu = 15.0
        prob = engine.predict_win(strong, weak)
        assert prob > 0.7

    def test_weaker_player_disfavored(self, engine):
        strong = engine.new_rating()
        strong.mu = 35.0
        weak = engine.new_rating()
        weak.mu = 15.0
        prob = engine.predict_win(weak, strong)
        assert prob < 0.3


class TestMatchQuality:
    def test_equal_ratings_high_quality(self, engine):
        r1 = engine.new_rating()
        r2 = engine.new_rating()
        quality = engine.match_quality(r1, r2)
        assert quality > 0.9

    def test_unbalanced_ratings_low_quality(self, engine):
        strong = engine.new_rating()
        strong.mu = 40.0
        strong.sigma = 2.0
        weak = engine.new_rating()
        weak.mu = 10.0
        weak.sigma = 2.0
        quality = engine.match_quality(strong, weak)
        assert quality < 0.5

    def test_quality_range_zero_to_one(self, engine):
        r1 = engine.new_rating()
        r2 = engine.new_rating()
        quality = engine.match_quality(r1, r2)
        assert 0.0 <= quality <= 1.0


class TestUpdateRatings:
    def test_winner_mu_increases(self, engine):
        r1 = engine.new_rating()
        r2 = engine.new_rating()
        old_mu = r1.mu
        new_r1, new_r2 = engine.update_ratings(r1, r2, winner="a")
        assert new_r1.mu > old_mu

    def test_loser_mu_decreases(self, engine):
        r1 = engine.new_rating()
        r2 = engine.new_rating()
        old_mu = r2.mu
        new_r1, new_r2 = engine.update_ratings(r1, r2, winner="a")
        assert new_r2.mu < old_mu

    def test_draw_keeps_similar(self, engine):
        r1 = engine.new_rating()
        r2 = engine.new_rating()
        new_r1, new_r2 = engine.update_ratings(r1, r2, winner=None)
        # Draw with equal ratings should barely change
        assert abs(new_r1.mu - new_r2.mu) < 1.0

    def test_sigma_decreases_after_game(self, engine):
        r1 = engine.new_rating()
        r2 = engine.new_rating()
        old_sigma = r1.sigma
        new_r1, _ = engine.update_ratings(r1, r2, winner="a")
        assert new_r1.sigma < old_sigma


class TestProcessBattleScores:
    def test_processes_all_7_axes(self, engine):
        scores_a = {
            "accuracy": 85, "safety": 90, "process_quality": 70,
            "reliability": 80, "latency": 75, "schema_quality": 88,
        }
        scores_b = {
            "accuracy": 70, "safety": 85, "process_quality": 65,
            "reliability": 75, "latency": 80, "schema_quality": 72,
        }
        ratings_a = {}  # empty = new ratings
        ratings_b = {}
        result = engine.process_battle_scores(
            scores_a, scores_b, 85, 72,  # overall scores
            ratings_a, ratings_b, winner="a",
        )
        assert "composite" in result["agent_a"]
        assert "composite" in result["agent_b"]
        for axis in engine.AXES:
            assert axis in result["agent_a"]
            assert axis in result["agent_b"]

    def test_winner_gets_higher_composite_mu(self, engine):
        scores_a = {"accuracy": 85, "safety": 90, "process_quality": 70,
                     "reliability": 80, "latency": 75, "schema_quality": 88}
        scores_b = {"accuracy": 70, "safety": 85, "process_quality": 65,
                     "reliability": 75, "latency": 80, "schema_quality": 72}
        result = engine.process_battle_scores(
            scores_a, scores_b, 85, 72, {}, {}, winner="a",
        )
        assert result["agent_a"]["composite"]["after"]["mu"] > result["agent_b"]["composite"]["after"]["mu"]

    def test_new_agents_get_default_ratings(self, engine):
        scores = {"accuracy": 50, "safety": 50, "process_quality": 50,
                  "reliability": 50, "latency": 50, "schema_quality": 50}
        result = engine.process_battle_scores(
            scores, scores, 50, 50, {}, {}, winner=None,
        )
        # Before ratings should be the default 25.0
        assert result["agent_a"]["composite"]["before"]["mu"] == 25.0

    def test_existing_ratings_preserved(self, engine):
        scores = {"accuracy": 50, "safety": 50, "process_quality": 50,
                  "reliability": 50, "latency": 50, "schema_quality": 50}
        existing = {"composite": {"mu": 30.0, "sigma": 5.0}}
        result = engine.process_battle_scores(
            scores, scores, 50, 50, existing, {}, winner=None,
        )
        assert result["agent_a"]["composite"]["before"]["mu"] == 30.0
