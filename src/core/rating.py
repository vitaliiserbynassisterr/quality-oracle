"""OpenSkill rating engine for AgentTrust Battle Arena.

Uses PlackettLuce model for Bayesian skill estimation.
Maintains 7 independent rating instances: 6 per scoring axis + 1 composite.
"""
import logging
from typing import Dict, Optional

from openskill.models import PlackettLuce

logger = logging.getLogger(__name__)

# 6 scoring axes (matching evaluator.py)
SCORING_AXES = [
    "accuracy", "safety", "process_quality",
    "reliability", "latency", "schema_quality",
]


class RatingEngine:
    """Manages OpenSkill ratings for battle participants."""

    AXES = SCORING_AXES
    DEFAULT_MU = 25.0
    DEFAULT_SIGMA = 25.0 / 3  # ~8.333

    def __init__(self):
        self.model = PlackettLuce()

    def new_rating(self):
        """Create a fresh rating with default mu/sigma."""
        return self.model.rating(mu=self.DEFAULT_MU, sigma=self.DEFAULT_SIGMA)

    def predict_win(self, rating_a, rating_b) -> float:
        """Predict probability that A wins against B. Returns 0.0-1.0."""
        probs = self.model.predict_win([[rating_a], [rating_b]])
        return probs[0]

    def match_quality(self, rating_a, rating_b) -> float:
        """Compute match quality. 1.0 = perfect match, 0.0 = total mismatch."""
        win_prob = self.predict_win(rating_a, rating_b)
        return 1.0 - abs(win_prob - 0.5) * 2

    def update_ratings(self, rating_a, rating_b, winner: Optional[str]):
        """Update ratings after a battle.

        Args:
            rating_a: Agent A's current rating
            rating_b: Agent B's current rating
            winner: "a", "b", or None (draw)

        Returns:
            Tuple of (new_rating_a, new_rating_b)
        """
        if winner == "a":
            result = self.model.rate([[rating_a], [rating_b]])
        elif winner == "b":
            result = self.model.rate([[rating_b], [rating_a]])
            # Swap back since we reversed the order
            return result[1][0], result[0][0]
        else:
            # Draw — same rank
            result = self.model.rate([[rating_a], [rating_b]], ranks=[1, 1])

        return result[0][0], result[1][0]

    def _rating_from_dict(self, data: Dict) -> object:
        """Reconstruct a rating object from stored {mu, sigma}."""
        return self.model.rating(
            mu=data.get("mu", self.DEFAULT_MU),
            sigma=data.get("sigma", self.DEFAULT_SIGMA),
        )

    def process_battle_scores(
        self,
        scores_a: Dict[str, float],
        scores_b: Dict[str, float],
        overall_a: int,
        overall_b: int,
        existing_ratings_a: Dict,
        existing_ratings_b: Dict,
        winner: Optional[str],
    ) -> Dict:
        """Process a battle result and update all 7 rating axes.

        Args:
            scores_a: Agent A's 6-axis scores {axis: score}
            scores_b: Agent B's 6-axis scores
            overall_a: Agent A's composite score
            overall_b: Agent B's composite score
            existing_ratings_a: Stored ratings {axis: {mu, sigma}, composite: {mu, sigma}}
            existing_ratings_b: Same for agent B
            winner: "a", "b", or None

        Returns:
            Dict with agent_a and agent_b rating deltas per axis + composite.
        """
        result = {"agent_a": {}, "agent_b": {}}

        # Process 6 individual axes
        for axis in self.AXES:
            ra = self._get_or_create_rating(existing_ratings_a, axis)
            rb = self._get_or_create_rating(existing_ratings_b, axis)

            # Per-axis winner based on axis scores
            axis_score_a = scores_a.get(axis, 0)
            axis_score_b = scores_b.get(axis, 0)
            if axis_score_a > axis_score_b:
                axis_winner = "a"
            elif axis_score_b > axis_score_a:
                axis_winner = "b"
            else:
                axis_winner = None

            new_ra, new_rb = self.update_ratings(ra, rb, axis_winner)

            result["agent_a"][axis] = {
                "before": {"mu": ra.mu, "sigma": ra.sigma},
                "after": {"mu": new_ra.mu, "sigma": new_ra.sigma},
            }
            result["agent_b"][axis] = {
                "before": {"mu": rb.mu, "sigma": rb.sigma},
                "after": {"mu": new_rb.mu, "sigma": new_rb.sigma},
            }

        # Process composite rating (uses overall winner)
        ra_comp = self._get_or_create_rating(existing_ratings_a, "composite")
        rb_comp = self._get_or_create_rating(existing_ratings_b, "composite")
        new_ra_comp, new_rb_comp = self.update_ratings(ra_comp, rb_comp, winner)

        result["agent_a"]["composite"] = {
            "before": {"mu": ra_comp.mu, "sigma": ra_comp.sigma},
            "after": {"mu": new_ra_comp.mu, "sigma": new_ra_comp.sigma},
        }
        result["agent_b"]["composite"] = {
            "before": {"mu": rb_comp.mu, "sigma": rb_comp.sigma},
            "after": {"mu": new_rb_comp.mu, "sigma": new_rb_comp.sigma},
        }

        return result

    def _get_or_create_rating(self, existing: Dict, key: str):
        """Get existing rating or create new one."""
        if key in existing:
            return self._rating_from_dict(existing[key])
        return self.new_rating()
