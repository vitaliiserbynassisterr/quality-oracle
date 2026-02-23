"""
Quality Oracle evaluation engine.

Orchestrates the full evaluation flow:
Level 1: Manifest validation
Level 2: Functional testing (challenge-response via MCP Client)
Level 3: Domain expert testing (calibrated question bank)
"""
import hashlib
import logging
import time
from datetime import datetime
from typing import Dict, List, Optional

from src.core.llm_judge import LLMJudge, JudgeResult
from src.core.question_pools import (
    QuestionSelector,
    ChallengeQuestion,
    determine_tier,
)
from src.storage.models import EvalLevel

logger = logging.getLogger(__name__)


class ManifestValidationResult:
    """Result of Level 1 manifest validation."""
    def __init__(self):
        self.score: int = 0
        self.checks: Dict[str, bool] = {}
        self.warnings: List[str] = []

    def to_dict(self) -> dict:
        return {
            "score": self.score,
            "checks": self.checks,
            "warnings": self.warnings,
        }


class EvaluationResult:
    """Result of a complete evaluation."""
    def __init__(self):
        self.overall_score: int = 0
        self.tier: str = "failed"
        self.confidence: float = 0.0
        self.tool_scores: Dict[str, dict] = {}
        self.domain_scores: Dict[str, dict] = {}
        self.questions_asked: int = 0
        self.questions_answered: int = 0
        self.judge_responses: List[dict] = []
        self.manifest_result: Optional[ManifestValidationResult] = None
        self.duration_ms: int = 0
        self.result_hash: str = ""

    def to_dict(self) -> dict:
        return {
            "overall_score": self.overall_score,
            "tier": self.tier,
            "confidence": self.confidence,
            "tool_scores": self.tool_scores,
            "domain_scores": self.domain_scores,
            "questions_asked": self.questions_asked,
            "questions_answered": self.questions_answered,
            "manifest": self.manifest_result.to_dict() if self.manifest_result else None,
            "duration_ms": self.duration_ms,
            "result_hash": self.result_hash,
        }


class Evaluator:
    """
    Core evaluation engine for Quality Oracle.

    Supports 3 levels of evaluation with increasing depth.
    """

    def __init__(self, llm_judge: LLMJudge):
        self.llm_judge = llm_judge
        self.question_selector = QuestionSelector()

    def validate_manifest(self, manifest: dict) -> ManifestValidationResult:
        """Level 1: Validate MCP server manifest for completeness and quality."""
        result = ManifestValidationResult()
        checks = {}
        warnings = []

        # Check tools are defined
        tools = manifest.get("tools", [])
        checks["has_tools"] = len(tools) > 0
        if not checks["has_tools"]:
            warnings.append("No tools defined in manifest")

        # Check each tool has description
        tools_with_desc = sum(1 for t in tools if t.get("description"))
        checks["tools_have_descriptions"] = tools_with_desc == len(tools) if tools else False
        if tools and tools_with_desc < len(tools):
            warnings.append(f"{len(tools) - tools_with_desc}/{len(tools)} tools missing descriptions")

        # Check input schemas
        tools_with_schema = sum(1 for t in tools if t.get("inputSchema") or t.get("parameters"))
        checks["tools_have_schemas"] = tools_with_schema == len(tools) if tools else False
        if tools and tools_with_schema < len(tools):
            warnings.append(f"{len(tools) - tools_with_schema}/{len(tools)} tools missing input schemas")

        # Check server info
        checks["has_name"] = bool(manifest.get("name"))
        checks["has_version"] = bool(manifest.get("version"))
        checks["has_description"] = bool(manifest.get("description"))

        if not checks["has_name"]:
            warnings.append("Missing server name")
        if not checks["has_description"]:
            warnings.append("Missing server description")

        # Score calculation
        total_checks = len(checks)
        passed_checks = sum(1 for v in checks.values() if v)
        result.score = int((passed_checks / total_checks) * 100) if total_checks > 0 else 0
        result.checks = checks
        result.warnings = warnings

        return result

    async def evaluate_functional(
        self,
        target_id: str,
        tool_responses: Dict[str, List[dict]],
        manifest: Optional[dict] = None,
    ) -> EvaluationResult:
        """
        Level 2: Functional testing.

        Takes pre-collected tool responses and judges them.

        Args:
            target_id: ID of the target being evaluated
            tool_responses: Dict of tool_name -> list of {question, expected, answer}
            manifest: Optional manifest for Level 1 inclusion
        """
        start = time.time()
        result = EvaluationResult()

        # Run Level 1 if manifest provided
        if manifest:
            result.manifest_result = self.validate_manifest(manifest)

        # Judge each tool's responses
        all_scores = []
        for tool_name, responses in tool_responses.items():
            tool_scores = []
            tests_passed = 0

            for resp in responses:
                judge_result = await self.llm_judge.ajudge(
                    resp["question"],
                    resp["expected"],
                    resp["answer"],
                )
                tool_scores.append(judge_result.score)
                if judge_result.score >= 50:
                    tests_passed += 1

                result.judge_responses.append({
                    "tool": tool_name,
                    "question": resp["question"],
                    "score": judge_result.score,
                    "explanation": judge_result.explanation,
                    "method": judge_result.method,
                })

            avg_score = sum(tool_scores) / len(tool_scores) if tool_scores else 0
            result.tool_scores[tool_name] = {
                "score": int(avg_score),
                "tests_passed": tests_passed,
                "tests_total": len(responses),
            }
            all_scores.extend(tool_scores)

        # Aggregate
        result.questions_asked = len(all_scores)
        result.questions_answered = sum(1 for s in all_scores if s > 0)
        result.overall_score = int(sum(all_scores) / len(all_scores)) if all_scores else 0
        result.tier = determine_tier(result.overall_score)
        result.confidence = min(0.95, len(all_scores) / 30)  # More questions = more confidence
        result.duration_ms = int((time.time() - start) * 1000)

        # Result hash for on-chain
        hash_data = f"{target_id}:{result.overall_score}:{result.questions_asked}:{int(time.time())}"
        result.result_hash = hashlib.sha256(hash_data.encode()).hexdigest()

        logger.info(
            f"Evaluation complete: {target_id} | "
            f"Score: {result.overall_score} | Tier: {result.tier} | "
            f"Questions: {result.questions_asked}"
        )

        return result

    async def evaluate_domain(
        self,
        target_id: str,
        domains: List[str],
        answer_fn,
        question_count: int = 10,
    ) -> EvaluationResult:
        """
        Level 3: Domain expert testing with calibrated questions.

        Args:
            target_id: ID of the target
            domains: Domains to test
            answer_fn: Async callable that takes a question and returns answer string
            question_count: Number of questions to ask
        """
        start = time.time()
        result = EvaluationResult()

        questions = self.question_selector.select_questions(
            target_id, domains=domains, count=question_count
        )

        all_scores = []
        domain_buckets: Dict[str, List[int]] = {}

        for q in questions:
            try:
                answer = await answer_fn(q.question)
            except Exception as e:
                logger.warning(f"Failed to get answer for {q.id}: {e}")
                answer = ""

            judge_result = await self.llm_judge.ajudge(
                q.question, q.reference_answer, answer
            )

            weighted_score = int(judge_result.score * q.weight)
            all_scores.append(judge_result.score)

            if q.domain not in domain_buckets:
                domain_buckets[q.domain] = []
            domain_buckets[q.domain].append(judge_result.score)

            result.judge_responses.append({
                "question_id": q.id,
                "domain": q.domain,
                "difficulty": q.difficulty,
                "score": judge_result.score,
                "weighted_score": weighted_score,
                "explanation": judge_result.explanation,
                "method": judge_result.method,
            })

        # Domain scores
        for domain, scores in domain_buckets.items():
            result.domain_scores[domain] = {
                "score": int(sum(scores) / len(scores)),
                "questions": len(scores),
            }

        result.questions_asked = len(questions)
        result.questions_answered = sum(1 for s in all_scores if s > 0)
        result.overall_score = int(sum(all_scores) / len(all_scores)) if all_scores else 0
        result.tier = determine_tier(result.overall_score)
        result.confidence = min(0.95, len(all_scores) / 30)
        result.duration_ms = int((time.time() - start) * 1000)

        hash_data = f"{target_id}:{result.overall_score}:{result.questions_asked}:{int(time.time())}"
        result.result_hash = hashlib.sha256(hash_data.encode()).hexdigest()

        return result
