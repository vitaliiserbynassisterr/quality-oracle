"""Evaluation mode configurations for quick/standard/full eval runs."""

from dataclasses import dataclass, field
from typing import Optional, Set


@dataclass
class EvalModeConfig:
    max_tools: Optional[int]        # None = all tools
    test_types: Set[str]            # Which test types to run
    use_consensus: bool             # Multi-judge or single judge
    run_safety_probes: bool         # Adversarial probes
    run_consistency_check: bool     # Idempotency check
    max_judges: int                 # 1 for single, 2-3 for consensus


EVAL_MODES: dict[str, EvalModeConfig] = {
    "quick": EvalModeConfig(
        max_tools=3,
        test_types={"happy_path"},
        use_consensus=False,
        run_safety_probes=False,
        run_consistency_check=False,
        max_judges=1,
    ),
    "standard": EvalModeConfig(
        max_tools=None,
        test_types={"happy_path", "error_handling", "edge_case"},
        use_consensus=False,
        run_safety_probes=True,
        run_consistency_check=False,
        max_judges=1,
    ),
    "full": EvalModeConfig(
        max_tools=None,
        test_types={"happy_path", "happy_path_variation", "error_handling", "edge_case", "boundary", "type_coercion"},
        use_consensus=True,
        run_safety_probes=True,
        run_consistency_check=True,
        max_judges=3,
    ),
}
