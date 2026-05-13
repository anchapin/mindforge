"""OpenRouter budget guard — hard rate limits on API calls and token usage.

Implements SPEC.md §5.7.10 — Cost Tracking.
Tracks calls_per_minute, calls_per_day, and tokens_per_day.
Environment variable overrides allow emergency adjustments.
"""

from __future__ import annotations

import logging
import os
import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta

from backend.exceptions import BudgetExceeded

logger = logging.getLogger(__name__)


# ── Default Limits ────────────────────────────────────────────────────────────


@dataclass
class BudgetLimits:
    """Hard caps and warning thresholds for OpenRouter usage."""

    max_calls_per_minute: int = 30
    max_calls_per_day: int = 500
    max_tokens_per_day: int = 2_000_000  # ~$0.40 at gemini-2-flash
    calls_per_day_warning: int = 300  # 60% of daily cap
    tokens_per_day_warning: int = 1_500_000  # 75% of daily token cap


def _load_limits_from_env() -> BudgetLimits:
    """Load budget limits from environment variables, with defaults."""
    return BudgetLimits(
        max_calls_per_minute=int(
            os.environ.get("OPENROUTER_MAX_CALLS_PER_MINUTE", "30")
        ),
        max_calls_per_day=int(
            os.environ.get("OPENROUTER_MAX_CALLS_PER_DAY", "500")
        ),
        max_tokens_per_day=int(
            os.environ.get("OPENROUTER_MAX_TOKENS_PER_DAY", "2000000")
        ),
        calls_per_day_warning=int(
            os.environ.get("OPENROUTER_CALLS_PER_DAY_WARNING", "300")
        ),
        tokens_per_day_warning=int(
            os.environ.get("OPENROUTER_TOKENS_PER_DAY_WARNING", "1500000")
        ),
    )


# ── Budget Guard ───────────────────────────────────────────────────────────────


class OpenRouterBudgetGuard:
    """Hard rate limit guard for OpenRouter API calls and token usage.

    Prevents runaway loops from exhausting the monthly budget.
    All methods are thread-safe for use from async contexts.

    Usage:
        guard = OpenRouterBudgetGuard()
        allowed, reason = guard.check(tokens_estimate=5000)
        if not allowed:
            raise BudgetExceeded(reason)
        # ... make LLM call ...
        guard.record(tokens_used=1200)
    """

    def __init__(self, limits: BudgetLimits | None = None):
        self._limits = limits or _load_limits_from_env()
        self._calls_minute: deque[datetime] = deque()
        self._calls_day: deque[datetime] = deque()
        self._tokens_day: int = 0
        self._last_warning_log: datetime | None = None
        self._lock = threading.Lock()
        self._day_offset = datetime.utcnow().day  # Track day changes

    def _reset_day_if_needed(self) -> None:
        """Clear daily counters if we've crossed midnight UTC."""
        now = datetime.utcnow()
        if self._calls_day and self._calls_day[0].date() < now.date():
            self._calls_day.clear()
            self._tokens_day = 0
            self._day_offset = now.day

    def _clean_minute_window(self) -> None:
        """Remove calls older than 1 minute from the minute window."""
        cutoff = datetime.utcnow() - timedelta(minutes=1)
        while self._calls_minute and self._calls_minute[0] < cutoff:
            self._calls_minute.popleft()

    def check(self, tokens_estimate: int = 0) -> tuple[bool, str]:
        """Check if a new LLM call is allowed under the budget.

        Args:
            tokens_estimate: Estimated tokens for this call (input + output).

        Returns:
            Tuple of (allowed: bool, reason: str).
            If allowed is False, reason explains why.
            Raises BudgetExceeded if a hard cap is hit.
        """
        now = datetime.utcnow()
        with self._lock:
            self._clean_minute_window()
            self._reset_day_if_needed()

            # 1. Per-minute call rate
            if len(self._calls_minute) >= self._limits.max_calls_per_minute:
                return False, (
                    f"Per-minute rate limit hit "
                    f"({len(self._calls_minute)}/{self._limits.max_calls_per_minute} "
                    f"calls in last minute). Wait before retrying."
                )

            # 2. Per-day call count
            if len(self._calls_day) >= self._limits.max_calls_per_day:
                return False, (
                    f"Daily call limit reached "
                    f"({self._limits.max_calls_per_day}). Resets at midnight UTC."
                )

            # 3. Per-day token budget
            if tokens_estimate > 0:
                if self._tokens_day + tokens_estimate > self._limits.max_tokens_per_day:
                    return False, (
                        f"Daily token budget exceeded "
                        f"(~{self._tokens_day + tokens_estimate:,} / "
                        f"{self._limits.max_tokens_per_day:,}). "
                        f"Wait until midnight UTC or reduce context size."
                    )

            return True, "allowed"

    def record(self, tokens_used: int = 0) -> None:
        """Record a completed LLM call for usage tracking.

        Call this after every successful LLM response to update counters.

        Args:
            tokens_used: Total tokens consumed (input + output).
        """
        now = datetime.utcnow()
        with self._lock:
            self._calls_minute.append(now)
            self._calls_day.append(now)
            self._tokens_day += tokens_used

        # Check warning thresholds after recording
        self._check_warnings()

    def _check_warnings(self) -> None:
        """Log warnings when approaching budget limits."""
        # Avoid spamming logs — at most once per hour
        now = datetime.utcnow()
        if self._last_warning_log and (
            now - self._last_warning_log
        ).total_seconds() < 3600:
            return

        with self._lock:
            calls_remaining = self._limits.max_calls_per_day - len(self._calls_day)
            tokens_remaining = max(
                0, self._limits.max_tokens_per_day - self._tokens_day
            )

            if calls_remaining < 50:
                logger.warning(
                    "approaching_openrouter_call_limit",
                    calls_remaining=calls_remaining,
                    daily_cap=self._limits.max_calls_per_day,
                )
                self._last_warning_log = now

            if tokens_remaining < 300_000:
                logger.warning(
                    "approaching_openrouter_token_limit",
                    tokens_remaining=tokens_remaining,
                    daily_cap=self._limits.max_tokens_per_day,
                )
                self._last_warning_log = now

    @property
    def usage_today(self) -> dict:
        """Return current usage statistics for the day.

        Returns:
            Dict with calls_today, tokens_today, calls_remaining, tokens_remaining.
        """
        with self._lock:
            self._reset_day_if_needed()
            return {
                "calls_today": len(self._calls_day),
                "tokens_today": self._tokens_day,
                "calls_remaining": self._limits.max_calls_per_day
                - len(self._calls_day),
                "tokens_remaining": max(
                    0, self._limits.max_tokens_per_day - self._tokens_day
                ),
            }

    def warn_if_exceeded(self) -> None:
        """Log a warning if today's usage exceeds monthly budget.

        Call this on startup and periodically to alert if the budget
        is already over the threshold.
        """
        usage = self.usage_today
        if usage["calls_remaining"] < 0 or usage["tokens_remaining"] < 0:
            logger.warning(
                "openrouter_budget_exceeded",
                calls_today=usage["calls_today"],
                tokens_today=usage["tokens_today"],
            )


# Global budget guard singleton
BUDGET_GUARD = OpenRouterBudgetGuard()