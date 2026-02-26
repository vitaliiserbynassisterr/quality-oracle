"""Tests for score aggregation and tier calculation."""
from src.core.scoring import aggregate_scores, calculate_trend


class TestAggregateScores:
    def test_aggregate_functional_only(self):
        """tool_scores only → weights={functional:1.0}."""
        result = aggregate_scores(
            tool_scores={"calc": {"score": 80}, "search": {"score": 60}},
        )
        assert result["weights"] == {"manifest": 0.0, "functional": 1.0, "domain": 0.0}
        assert result["overall_score"] == 70
        assert result["manifest_score"] is None
        assert result["domain_score"] is None

    def test_aggregate_manifest_and_functional(self):
        """manifest+tool → weights={manifest:0.15, functional:0.85}."""
        result = aggregate_scores(
            tool_scores={"t1": {"score": 80}},
            manifest_score=100,
        )
        assert result["weights"] == {"manifest": 0.15, "functional": 0.85, "domain": 0.0}
        expected = int(round(100 * 0.15 + 80 * 0.85))
        assert result["overall_score"] == expected

    def test_aggregate_functional_and_domain(self):
        """tool+domain → weights={functional:0.65, domain:0.35}."""
        result = aggregate_scores(
            tool_scores={"t1": {"score": 80}},
            domain_scores={"defi": {"score": 60}},
        )
        assert result["weights"] == {"manifest": 0.0, "functional": 0.65, "domain": 0.35}
        expected = int(round(80 * 0.65 + 60 * 0.35))
        assert result["overall_score"] == expected

    def test_aggregate_all_three(self):
        """all present → weights={manifest:0.10, functional:0.60, domain:0.30}."""
        result = aggregate_scores(
            tool_scores={"t1": {"score": 80}},
            domain_scores={"defi": {"score": 60}},
            manifest_score=90,
        )
        assert result["weights"] == {"manifest": 0.10, "functional": 0.60, "domain": 0.30}
        expected = int(round(90 * 0.10 + 80 * 0.60 + 60 * 0.30))
        assert result["overall_score"] == expected

    def test_aggregate_empty_tools(self):
        """{} → functional_score=0."""
        result = aggregate_scores(tool_scores={})
        assert result["functional_score"] == 0
        assert result["overall_score"] == 0

    def test_aggregate_returns_tier(self):
        """Verify tier is set correctly based on overall_score."""
        result = aggregate_scores(tool_scores={"t1": {"score": 90}})
        assert result["tier"] == "expert"

        result = aggregate_scores(tool_scores={"t1": {"score": 75}})
        assert result["tier"] == "proficient"

        result = aggregate_scores(tool_scores={"t1": {"score": 55}})
        assert result["tier"] == "basic"

        result = aggregate_scores(tool_scores={"t1": {"score": 30}})
        assert result["tier"] == "failed"


class TestCalculateTrend:
    def test_trend_improving(self):
        assert calculate_trend([50, 60, 70]) == "improving"

    def test_trend_declining(self):
        assert calculate_trend([70, 60, 50]) == "declining"

    def test_trend_stable(self):
        assert calculate_trend([60, 70, 60]) == "stable"

    def test_trend_short_history(self):
        assert calculate_trend([50]) == "stable"

    def test_trend_two_improving(self):
        assert calculate_trend([50, 60]) == "improving"
