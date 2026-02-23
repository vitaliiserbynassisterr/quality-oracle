"""
Domain-specific question pools for Quality Oracle evaluations.

Ported from agent-poi hackathon (poi/question_pools.py + poi/evaluator.py).
Adapted: domain-agnostic structure for MCP server evaluation.
"""
import hashlib
import logging
import random
from dataclasses import dataclass
from typing import Dict, List, Optional, Set

logger = logging.getLogger(__name__)


@dataclass
class ChallengeQuestion:
    """A domain-specific challenge question with reference answer."""
    question: str
    domain: str
    difficulty: str  # easy, medium, hard
    reference_answer: str
    category: str = "functional"  # functional, correctness, edge_case

    @property
    def id(self) -> str:
        return hashlib.sha256(self.question.encode()).hexdigest()[:12]

    @property
    def weight(self) -> int:
        return {"easy": 1, "medium": 2, "hard": 3}.get(self.difficulty, 1)


# Question pools organized by domain
QUESTION_POOLS: Dict[str, List[ChallengeQuestion]] = {
    "defi": [
        ChallengeQuestion(
            question="Explain how an AMM determines token prices using the constant product formula.",
            domain="defi", difficulty="medium",
            reference_answer="AMMs use x*y=k where x and y are token reserves. Price is the ratio of reserves. As one token is bought, its reserve decreases and price increases.",
        ),
        ChallengeQuestion(
            question="What is impermanent loss and when does it occur in liquidity pools?",
            domain="defi", difficulty="medium",
            reference_answer="Impermanent loss occurs when the price ratio of pooled tokens changes from deposit. The larger the divergence, the more IL. Becomes permanent only when withdrawn.",
        ),
        ChallengeQuestion(
            question="Describe how flash loans work and why they don't require collateral.",
            domain="defi", difficulty="hard",
            reference_answer="Flash loans are uncollateralized loans borrowed and repaid within a single transaction. If not repaid, the entire transaction reverts atomically.",
        ),
        ChallengeQuestion(
            question="What is TVL and why is it an important DeFi metric?",
            domain="defi", difficulty="easy",
            reference_answer="TVL measures total crypto assets deposited in DeFi protocols. Indicates adoption, trust, and available liquidity.",
        ),
        ChallengeQuestion(
            question="How does concentrated liquidity improve capital efficiency?",
            domain="defi", difficulty="hard",
            reference_answer="Concentrated liquidity allocates capital within custom price ranges instead of full range. Provides 10-20x capital efficiency but requires active management.",
        ),
    ],
    "solana": [
        ChallengeQuestion(
            question="What are PDAs in Solana and how are they created?",
            domain="solana", difficulty="medium",
            reference_answer="PDAs are deterministic addresses derived from program ID and seeds that fall off Ed25519 curve. Created using findProgramAddress. Enable programs to sign without private keys.",
        ),
        ChallengeQuestion(
            question="Explain how CPI works in Solana and its constraints.",
            domain="solana", difficulty="medium",
            reference_answer="CPI allows one program to call another's instructions. Passes required accounts, callee inherits signer privileges. Depth limited to 4 levels.",
        ),
        ChallengeQuestion(
            question="How does Solana's rent system work?",
            domain="solana", difficulty="easy",
            reference_answer="Solana charges rent for storage. Accounts must hold minimum balance (~2 years rent) to be rent-exempt. Below threshold, accounts are garbage collected.",
        ),
        ChallengeQuestion(
            question="Explain Solana's Proof of History consensus mechanism.",
            domain="solana", difficulty="hard",
            reference_answer="PoH uses sequential SHA-256 hash chain creating a verifiable delay function. Establishes temporal ordering before consensus, enabling high throughput.",
        ),
    ],
    "security": [
        ChallengeQuestion(
            question="What is a reentrancy attack and how can it be prevented?",
            domain="security", difficulty="medium",
            reference_answer="Reentrancy occurs when external call re-enters calling function before state updates. Prevention: checks-effects-interactions pattern, reentrancy guards.",
        ),
        ChallengeQuestion(
            question="How does a sandwich attack exploit pending transactions?",
            domain="security", difficulty="hard",
            reference_answer="Front-runs victim's swap with buy order, victim executes at inflated price, attacker sells after. MEV bots monitor mempool.",
        ),
        ChallengeQuestion(
            question="What is a Sybil attack and how do decentralized systems defend?",
            domain="security", difficulty="medium",
            reference_answer="Creates multiple fake identities for disproportionate influence. Defenses: proof-of-stake, proof-of-work, reputation systems, identity verification.",
        ),
    ],
    "code-generation": [
        ChallengeQuestion(
            question="Generate a Python function that checks if a string is a valid palindrome, ignoring spaces and punctuation.",
            domain="code-generation", difficulty="easy",
            reference_answer="Function should normalize string (lowercase, remove non-alphanumeric), then compare with reversed version. Handle empty strings and single characters.",
        ),
        ChallengeQuestion(
            question="Implement a rate limiter using the token bucket algorithm in Python.",
            domain="code-generation", difficulty="hard",
            reference_answer="Token bucket: initialize with capacity and refill rate. consume() checks tokens available, refills based on elapsed time. Thread-safe with locks.",
        ),
    ],
    "general": [
        ChallengeQuestion(
            question="What is the A2A protocol and why is it important for AI agents?",
            domain="general", difficulty="easy",
            reference_answer="A2A enables AI agents to discover, communicate, and verify each other through standardized HTTP endpoints. Creates interoperable agent network.",
        ),
        ChallengeQuestion(
            question="Explain the difference between pre-payment and post-payment quality verification for AI agents.",
            domain="general", difficulty="medium",
            reference_answer="Pre-payment: verify competency BEFORE paying (challenge-response, benchmarks). Post-payment: observe after use (ratings, reputation). Pre-payment prevents paying for low-quality service.",
        ),
    ],
}

ALL_QUESTIONS: List[ChallengeQuestion] = []
for domain_questions in QUESTION_POOLS.values():
    ALL_QUESTIONS.extend(domain_questions)

# Certification thresholds
CERTIFICATION_THRESHOLDS = {"expert": 85.0, "proficient": 70.0, "basic": 50.0}


def determine_tier(score: float) -> str:
    if score >= CERTIFICATION_THRESHOLDS["expert"]:
        return "expert"
    elif score >= CERTIFICATION_THRESHOLDS["proficient"]:
        return "proficient"
    elif score >= CERTIFICATION_THRESHOLDS["basic"]:
        return "basic"
    return "failed"


class QuestionSelector:
    """Selects questions for evaluation, tracking history to avoid repeats."""

    def __init__(self):
        self._target_history: Dict[str, Set[str]] = {}

    def select_questions(
        self,
        target_id: str,
        domains: List[str] | None = None,
        count: int = 10,
    ) -> List[ChallengeQuestion]:
        """Select questions for a target, weighted by domain."""
        asked = self._target_history.get(target_id, set())

        # Filter by domains if specified
        if domains:
            pool = [q for q in ALL_QUESTIONS if q.domain in domains]
        else:
            pool = list(ALL_QUESTIONS)

        candidates = [q for q in pool if q.id not in asked]

        if len(candidates) < count:
            self._target_history[target_id] = set()
            candidates = list(pool)

        selected = random.sample(candidates, min(count, len(candidates)))

        if target_id not in self._target_history:
            self._target_history[target_id] = set()
        for q in selected:
            self._target_history[target_id].add(q.id)

        return selected
