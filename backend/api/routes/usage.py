"""Budget usage API endpoint — Task 12.

Exposes BUDGET_GUARD.usage_today via GET /api/usage.
From plan-gap-analysis.json: "Add GET /api/usage budget endpoint + WS budget alerts"
"""

from __future__ import annotations

from fastapi import APIRouter

from ...llm.cost_tracker import BUDGET_GUARD

router = APIRouter(prefix="/api/usage", tags=["usage"])


@router.get("/")
def get_usage():
    """Return current day budget usage statistics.

    Returns:
        dict with calls_today, tokens_today, calls_remaining, tokens_remaining.

    Budget warnings are also broadcast via WebSocket when:
    - calls_remaining < 50
    - tokens_remaining < 300,000
    """
    return BUDGET_GUARD.usage_today
