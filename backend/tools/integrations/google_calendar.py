"""Google Calendar tool -- Composio-mediated (#57 part C, ADR-0001).

Action surface kept narrow on purpose: only the verbs the
calendar-conflict skill needs (``list_events``, ``find_conflicts``).
Adding more later is a 1-line dispatch entry.

Composio-mediated per ADR-0001:
  - The OAuth grant lives on Composio's side; MindForge stores the
    Composio ``connected_account_id`` Fernet-encrypted on the existing
    ``integration`` row (PR A).
  - This tool's ``execute()`` would dispatch through the Composio SDK
    once the SDK is pinned. Until then it returns a structured
    ``CALENDAR_NOT_IMPLEMENTED_ERROR`` so the skill executor can
    branch on it without log-scraping.

Triple-gated phase isolation matches the rest of the Composio surface:
  - ``ENABLE_COMPOSIO=false`` -> CALENDAR_DISABLED_ERROR
  - ``ENABLE_COMPOSIO=true`` + no key -> CALENDAR_MISSING_CREDENTIAL_ERROR
  - All gates pass -> CALENDAR_NOT_IMPLEMENTED_ERROR (until SDK pinned)
"""

from __future__ import annotations

import logging
import os
import time

from ..base import BaseTool, ToolResult

logger = logging.getLogger(__name__)


# Public sentinels -- mirror the existing #56 ComposioTool conventions
# so the dashboard can branch on a single set of error strings.
CALENDAR_DISABLED_ERROR = (
    "calendar_disabled: ENABLE_COMPOSIO is not set. "
    "Google Calendar is a Phase 4 integration; enable it explicitly via env."
)
CALENDAR_MISSING_CREDENTIAL_ERROR = (
    "calendar_missing_credential: COMPOSIO_API_KEY is not configured."
)
CALENDAR_NOT_IMPLEMENTED_ERROR = (
    "calendar_not_implemented: Composio SDK is not yet pinned. "
    "Live dispatch lands once the SDK selection is finalised."
)
CALENDAR_UNKNOWN_ACTION_ERROR = (
    "calendar_unknown_action: action is not in the Phase 4 dispatch table."
)

# Narrow action surface -- expand as the skill catalogue grows.
_SUPPORTED_ACTIONS: frozenset[str] = frozenset({"list_events", "find_conflicts"})


def _flag_enabled() -> bool:
    raw = os.getenv("ENABLE_COMPOSIO", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _api_key() -> str | None:
    key = os.getenv("COMPOSIO_API_KEY", "").strip()
    return key or None


class GoogleCalendarTool(BaseTool):  # type: ignore[override]
    """Read-only Google Calendar dispatcher (Composio-mediated)."""

    name = "google_calendar"
    description = (
        "Google Calendar read-only access (Phase 4, Composio-mediated). "
        "Actions: list_events, find_conflicts."
    )
    required_integrations: list[str] = ["google_calendar"]

    async def execute(self, action: str, **kwargs) -> ToolResult:  # type: ignore[override]
        start = time.monotonic()

        if not _flag_enabled():
            logger.info("Calendar call rejected: feature flag off (action=%s)", action)
            return ToolResult(
                success=False,
                error=CALENDAR_DISABLED_ERROR,
                tool_name=self.name,
                latency_ms=(time.monotonic() - start) * 1000.0,
            )

        if _api_key() is None:
            logger.warning("Calendar enabled but COMPOSIO_API_KEY missing")
            return ToolResult(
                success=False,
                error=CALENDAR_MISSING_CREDENTIAL_ERROR,
                tool_name=self.name,
                latency_ms=(time.monotonic() - start) * 1000.0,
            )

        if action not in _SUPPORTED_ACTIONS:
            logger.warning("Calendar action not in dispatch table: %s", action)
            return ToolResult(
                success=False,
                error=CALENDAR_UNKNOWN_ACTION_ERROR,
                tool_name=self.name,
                latency_ms=(time.monotonic() - start) * 1000.0,
            )

        # SDK drop-in lands here. Until then the structured outcome lets the
        # skill executor + UI surface a real reason rather than a 500.
        del kwargs  # action params (start_iso/end_iso) ignored until SDK pinned
        logger.info("Calendar dispatch placeholder hit (action=%s)", action)
        return ToolResult(
            success=False,
            error=CALENDAR_NOT_IMPLEMENTED_ERROR,
            tool_name=self.name,
            latency_ms=(time.monotonic() - start) * 1000.0,
        )

    async def validate_auth(self, token: str | None = None) -> bool:  # type: ignore[override]
        """Cheap read-only check. Never raises.

        Returns False when the flag is off, no token is supplied, or no
        COMPOSIO_API_KEY is configured. The real ``GET /me`` round-trip
        lands with the SDK pin.
        """
        if not _flag_enabled():
            return False
        if not token:
            return False
        if _api_key() is None:
            return False
        return False
