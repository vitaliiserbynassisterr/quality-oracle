"""Tests for rate limiter async functions."""
import pytest
from unittest.mock import AsyncMock, patch

from fastapi import Response

from src.auth.rate_limiter import (
    check_eval_rate_limit,
    check_score_lookup_limit,
    add_rate_limit_headers,
)


@pytest.mark.asyncio
class TestCheckEvalRateLimit:
    @patch("src.auth.rate_limiter.check_rate_limit", new_callable=AsyncMock)
    async def test_check_eval_rate_limit_allowed(self, mock_check):
        mock_check.return_value = (True, 9, 10)
        result = await check_eval_rate_limit("key-1", "free")
        assert result == (True, 9, 10)
        mock_check.assert_called_once_with("key-1", 10, window="month")

    @patch("src.auth.rate_limiter.check_rate_limit", new_callable=AsyncMock)
    async def test_check_eval_rate_limit_exceeded(self, mock_check):
        mock_check.return_value = (False, 0, 10)
        result = await check_eval_rate_limit("key-2", "free")
        assert result == (False, 0, 10)

    @patch("src.auth.rate_limiter.check_rate_limit", new_callable=AsyncMock)
    async def test_check_eval_rate_limit_unknown_tier(self, mock_check):
        """Unknown tier defaults to limit=10."""
        mock_check.return_value = (True, 9, 10)
        await check_eval_rate_limit("key-3", "unknown")
        mock_check.assert_called_once_with("key-3", 10, window="month")


@pytest.mark.asyncio
class TestCheckScoreLookupLimit:
    @patch("src.auth.rate_limiter.check_rate_limit", new_callable=AsyncMock)
    async def test_check_score_lookup_limit_allowed(self, mock_check):
        mock_check.return_value = (True, 29, 30)
        result = await check_score_lookup_limit("key-1", "developer")
        assert result == (True, 29, 30)
        mock_check.assert_called_once_with("score:key-1", 30, window="minute")

    @patch("src.auth.rate_limiter.check_rate_limit", new_callable=AsyncMock)
    async def test_check_score_lookup_limit_exceeded(self, mock_check):
        mock_check.return_value = (False, 0, 30)
        result = await check_score_lookup_limit("key-2", "developer")
        assert result == (False, 0, 30)


class TestAddRateLimitHeaders:
    def test_add_rate_limit_headers(self):
        response = Response()
        add_rate_limit_headers(response, "developer", limit=100, remaining=50)
        assert response.headers["X-RateLimit-Limit"] == "100"
        assert response.headers["X-RateLimit-Remaining"] == "50"
        assert response.headers["X-Quality-Oracle-Tier"] == "developer"

    def test_add_rate_limit_headers_clamps_negative(self):
        """remaining=-1 → header shows 0."""
        response = Response()
        add_rate_limit_headers(response, "free", limit=10, remaining=-1)
        assert response.headers["X-RateLimit-Remaining"] == "0"
