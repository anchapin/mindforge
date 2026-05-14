"""Test budget API endpoint — Task 12.

Tests GET /api/usage response shape and budget_warning WS message wiring.
From plan-gap-analysis.json: "Add GET /api/usage budget endpoint + WS budget alerts"

RED: GET /api/usage does not exist yet.
GREEN: Implement GET /api/usage returning BUDGET_GUARD.usage_today.
Run: pytest backend/tests/integration/test_budget.py -v
"""

import os
import pathlib
from unittest.mock import patch

import pytest

# Patch os.makedirs BEFORE any backend imports
_original_makedirs = os.makedirs


def _patched_makedirs(path, *args, **kwargs):
    if isinstance(path, pathlib.Path):
        path = str(path)
    if str(path).startswith("/app"):
        return
    return _original_makedirs(path, *args, **kwargs)


os.makedirs = _patched_makedirs  # type: ignore[assignment]


class TestBudgetAPIUsageEndpoint:
    """Verify GET /api/usage returns correct budget usage structure.

    RED: /api/usage endpoint does not exist.
    GREEN: Implement usage.py route returning BUDGET_GUARD.usage_today dict.
    """

    def test_get_api_usage_returns_expected_shape(self):
        """GET /api/usage returns dict with calls_today, tokens_today, calls_remaining, tokens_remaining."""
        from fastapi.testclient import TestClient

        from backend.main import app

        # Mock the budget guard to return known values
        mock_usage = {
            "calls_today": 42,
            "tokens_today": 500_000,
            "calls_remaining": 458,
            "tokens_remaining": 1_500_000,
        }

        with patch("backend.api.routes.usage.BUDGET_GUARD") as mock_guard:
            mock_guard.usage_today = mock_usage
            client = TestClient(app)
            response = client.get("/api/usage")

        # RED: This will fail with 404 because /api/usage is not yet implemented
        assert response.status_code == 200, (
            f"Expected 200, got {response.status_code}. "
            "GET /api/usage endpoint does not exist yet."
        )

        data = response.json()
        assert "calls_today" in data, f"Missing 'calls_today' in response: {data}"
        assert "tokens_today" in data, f"Missing 'tokens_today' in response: {data}"
        assert "calls_remaining" in data, f"Missing 'calls_remaining' in response: {data}"
        assert "tokens_remaining" in data, f"Missing 'tokens_remaining' in response: {data}"

        # Verify values match mock
        assert data["calls_today"] == 42
        assert data["tokens_today"] == 500_000
        assert data["calls_remaining"] == 458
        assert data["tokens_remaining"] == 1_500_000

    def test_get_api_usage_returns_integers(self):
        """GET /api/usage returns integer values for all fields."""
        from fastapi.testclient import TestClient

        from backend.main import app

        mock_usage = {
            "calls_today": 10,
            "tokens_today": 100_000,
            "calls_remaining": 490,
            "tokens_remaining": 1_900_000,
        }

        with patch("backend.api.routes.usage.BUDGET_GUARD") as mock_guard:
            mock_guard.usage_today = mock_usage
            client = TestClient(app)
            response = client.get("/api/usage")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data["calls_today"], int)
        assert isinstance(data["tokens_today"], int)
        assert isinstance(data["calls_remaining"], int)
        assert isinstance(data["tokens_remaining"], int)


class TestBudgetWarningWS:
    """Verify budget_warning WS message is broadcast when threshold approached.

    RED: budget_warning WS message not wired in BUDGET_GUARD._check_warnings.
    GREEN: Wire broadcast when calls_remaining < 50 or tokens_remaining < 300000.
    """

    @pytest.mark.asyncio
    async def test_budget_warning_sent_when_calls_remaining_low(self):
        """When calls_remaining < 50, budget_warning WS message is broadcast."""
        from backend.llm.cost_tracker import BudgetLimits, OpenRouterBudgetGuard

        # Track broadcast messages
        broadcasts = []

        def capture_budget_warning(calls_remaining, tokens_remaining):
            broadcasts.append({
                "type": "budget_warning",
                "calls_remaining": calls_remaining,
                "tokens_remaining": tokens_remaining,
            })

        # Create budget guard with low call limit to trigger warning
        limits = BudgetLimits(
            max_calls_per_day=100,
            max_tokens_per_day=2_000_000,
            calls_per_day_warning=50,
            tokens_per_day_warning=1_500_000,
        )
        guard = OpenRouterBudgetGuard(limits=limits, on_budget_warning=capture_budget_warning)

        # Record calls to approach the limit
        for _ in range(60):  # 60 calls, 40 remaining -> below 50 threshold
            guard.record(tokens_used=1000)

        # Check if budget_warning was captured via callback
        budget_warnings = [m for m in broadcasts if m.get("type") == "budget_warning"]
        assert len(budget_warnings) >= 1, (
            f"Expected at least 1 budget_warning message when calls_remaining < 50, got {len(budget_warnings)}. "
            "budget_warning WS message is not wired in BUDGET_GUARD._check_warnings."
        )

    @pytest.mark.asyncio
    async def test_budget_warning_not_sent_when_under_threshold(self):
        """When calls_remaining >= 50 and tokens_remaining >= 300000, no budget_warning sent."""
        from backend.api.websocket import WSConnectionManager
        from backend.llm.cost_tracker import BudgetLimits, OpenRouterBudgetGuard

        broadcasts = []

        class MockWSManager(WSConnectionManager):
            async def broadcast(self, message):
                broadcasts.append(message)

        # Create budget guard with normal limits
        limits = BudgetLimits(
            max_calls_per_day=1000,
            max_tokens_per_day=2_000_000,
        )
        guard = OpenRouterBudgetGuard(limits=limits)

        # Record a few calls but stay well under limits
        for _ in range(5):
            guard.record(tokens_used=1000)

        from backend.api import websocket
        original_ws_manager = websocket.ws_manager
        mock_ws = MockWSManager()
        websocket.ws_manager = mock_ws

        try:
            guard.record(tokens_used=1000)

            # Should not have any budget_warning since we're under threshold
            budget_warnings = [m for m in broadcasts if m.get("type") == "budget_warning"]
            assert len(budget_warnings) == 0, (
                f"Expected 0 budget_warning messages when under threshold, got {len(budget_warnings)}"
            )
        finally:
            websocket.ws_manager = original_ws_manager
