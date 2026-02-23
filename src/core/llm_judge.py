"""
LLM-as-Judge for Quality Oracle evaluation scoring.

Ported from agent-poi hackathon (poi/llm_judge.py).
Adapted for Quality Oracle: DeepSeek V3.2 primary, Groq fallback, fuzzy fallback.
"""
import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Dict, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

CACHE_TTL = 86400  # 24 hours
MAX_RETRIES = 3
RETRY_BASE_DELAY = 2.0


@dataclass
class JudgeResult:
    """Result from the LLM judge evaluation."""
    score: int  # 0-100
    explanation: str
    method: str  # "llm" or "fuzzy"
    cached: bool = False
    latency_ms: int = 0


@dataclass
class CacheEntry:
    result: JudgeResult
    timestamp: float


class LLMJudge:
    """
    LLM-as-Judge for evaluating MCP server / agent responses.

    Provider priority: DeepSeek V3.2 → Groq → Fuzzy fallback.
    Results are cached to avoid duplicate API calls.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "deepseek-chat",
        provider: str = "deepseek",
        base_url: str = "https://api.deepseek.com/v1",
        fallback_key: Optional[str] = None,
        fallback_model: str = "llama-3.3-70b-versatile",
        fallback_provider: str = "groq",
    ):
        self.api_key = api_key
        self.model = model
        self.provider = provider
        self.base_url = base_url
        self.fallback_key = fallback_key
        self.fallback_model = fallback_model
        self.fallback_provider = fallback_provider
        self._cache: Dict[str, CacheEntry] = {}
        self._llm_available = bool(api_key)

        if self._llm_available:
            logger.info(f"LLM Judge: provider={provider}, model={model}")
        else:
            logger.info("LLM Judge: using fuzzy fallback (no API key)")

    @property
    def is_llm_available(self) -> bool:
        return self._llm_available

    def _cache_key(self, question: str, expected: str, answer: str) -> str:
        raw = f"{question}|{expected}|{answer}".lower().strip()
        return hashlib.sha256(raw.encode()).hexdigest()

    def _get_cached(self, key: str) -> Optional[JudgeResult]:
        entry = self._cache.get(key)
        if entry is None:
            return None
        if time.time() - entry.timestamp > CACHE_TTL:
            del self._cache[key]
            return None
        return JudgeResult(
            score=entry.result.score,
            explanation=entry.result.explanation,
            method=entry.result.method,
            cached=True,
        )

    def _store_cache(self, key: str, result: JudgeResult) -> None:
        self._cache[key] = CacheEntry(result=result, timestamp=time.time())
        if len(self._cache) > 1000:
            oldest_key = min(self._cache, key=lambda k: self._cache[k].timestamp)
            del self._cache[oldest_key]

    def _build_prompt(self, question: str, expected: str, answer: str) -> str:
        return (
            "You are a judge evaluating an AI agent/tool response quality. "
            "Score the response from 0 to 100 based on CORRECTNESS, COMPLETENESS, and RELEVANCE. "
            "A correct but concise answer should score 70-85. "
            "Only deduct heavily for factual errors, missing critical information, or irrelevant responses.\n\n"
            f"Question/Input: {question}\n"
            f"Expected behavior: {expected}\n"
            f"Actual response: {answer}\n\n"
            "Respond with ONLY valid JSON:\n"
            '{"score": <0-100>, "explanation": "<brief 1-sentence explanation>"}\n'
        )

    def _parse_response(self, text: str) -> Optional[Tuple[int, str]]:
        text = text.strip()
        if "```" in text:
            for segment in text.split("```"):
                segment = segment.strip()
                if segment.startswith("json"):
                    segment = segment[4:].strip()
                if segment.startswith("{"):
                    text = segment
                    break
        try:
            data = json.loads(text)
            score = max(0, min(100, int(data.get("score", 0))))
            explanation = str(data.get("explanation", ""))
            return score, explanation
        except (json.JSONDecodeError, ValueError, TypeError):
            return None

    async def ajudge(self, question: str, expected: str, answer: str) -> JudgeResult:
        """Judge a response asynchronously. Primary → fallback → fuzzy."""
        key = self._cache_key(question, expected, answer)
        cached = self._get_cached(key)
        if cached is not None:
            return cached

        start = time.time()

        # Try primary provider
        if self._llm_available:
            result = await self._call_llm(
                question, expected, answer,
                self.api_key, self.model, self.provider, self.base_url,
            )
            if result is not None:
                result.latency_ms = int((time.time() - start) * 1000)
                self._store_cache(key, result)
                return result

        # Try fallback provider
        if self.fallback_key:
            result = await self._call_llm(
                question, expected, answer,
                self.fallback_key, self.fallback_model, self.fallback_provider,
                "https://api.groq.com/openai/v1",
            )
            if result is not None:
                result.latency_ms = int((time.time() - start) * 1000)
                self._store_cache(key, result)
                return result

        # Fuzzy fallback
        result = self._judge_fuzzy(question, expected, answer)
        result.latency_ms = int((time.time() - start) * 1000)
        self._store_cache(key, result)
        return result

    async def _call_llm(
        self, question: str, expected: str, answer: str,
        api_key: str, model: str, provider: str, base_url: str,
    ) -> Optional[JudgeResult]:
        prompt = self._build_prompt(question, expected, answer)
        url = f"{base_url}/chat/completions"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": "You are a precise scoring judge. Always respond with valid JSON only."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.1,
            "max_tokens": 150,
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                for attempt in range(MAX_RETRIES):
                    response = await client.post(url, headers=headers, json=body)
                    if response.status_code == 429:
                        delay = RETRY_BASE_DELAY * (2 ** attempt)
                        logger.warning(f"Judge rate limited (429), retry {attempt + 1}/{MAX_RETRIES}")
                        await asyncio.sleep(delay)
                        continue
                    break

                if response.status_code != 200:
                    logger.warning(f"{provider} API returned {response.status_code}")
                    return None

                data = response.json()
                text = data["choices"][0]["message"]["content"]
                parsed = self._parse_response(text)
                if parsed is None:
                    return None

                score, explanation = parsed
                return JudgeResult(score=score, explanation=explanation, method="llm")

        except Exception as e:
            logger.warning(f"LLM judge error ({provider}): {e}")
            return None

    def _judge_fuzzy(self, question: str, expected: str, answer: str) -> JudgeResult:
        """Enhanced fuzzy matching fallback using difflib."""
        if not answer or not answer.strip():
            return JudgeResult(score=0, explanation="Empty response", method="fuzzy")

        answer_lower = answer.lower().strip()
        expected_lower = expected.lower().strip()

        seq_ratio = SequenceMatcher(None, expected_lower, answer_lower).ratio()

        expected_terms = [t for t in expected_lower.split() if len(t) > 1]
        if expected_terms:
            answer_terms = answer_lower.split()
            term_scores = []
            for et in expected_terms:
                if et in answer_lower:
                    term_scores.append(1.0)
                elif answer_terms:
                    best = max(SequenceMatcher(None, et, at).ratio() for at in answer_terms)
                    term_scores.append(best)
                else:
                    term_scores.append(0.0)
            keyword_score = sum(term_scores) / len(term_scores)
        else:
            keyword_score = 0.0

        containment_score = 1.0 if expected_lower in answer_lower else (
            0.7 if answer_lower in expected_lower else 0.0
        )

        raw_score = keyword_score * 0.50 + seq_ratio * 0.30 + containment_score * 0.20
        score = max(0, min(100, int(round(raw_score * 100))))

        return JudgeResult(
            score=score,
            explanation=f"Fuzzy: keyword={keyword_score:.0%}, similarity={seq_ratio:.0%}",
            method="fuzzy",
        )
