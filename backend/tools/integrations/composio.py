"""Composio Cloud integration tool — Phase 4 spike POC (#56).

This is a SPIKE deliverable. Its purpose is to:

  1. Lock in the tool shape decision documented in
     `docs/adr/0001-composio-integration.md` (single ``ComposioTool`` with
     action dispatch on the ``<app>.<verb>`` form, e.g. ``"gmail.send"``).
  2. Provide a flag-gated entry point so downstream issues #57 (OAuth
     migration) and #58 (7-day soak) can extend an existing module rather
     than introduce a new tool surface.
  3. Guarantee Phase 1-3 functionality is unchanged when ``ENABLE_COMPOSIO``
     is unset/false (per AGENTS.md Rule 6 / SPEC §5.4).

This POC intentionally does NOT make any live Composio network calls. It
returns structured ``ToolResult`` errors so the supervisor / skill executor
can degrade gracefully and surface the problem to the user.

Authentication strategy (full design lives in the ADR):
  - The Composio SDK / REST API key is sourced from ``COMPOSIO_API_KEY``.
  - Per-end-user OAuth tokens (Gmail, GitHub, etc.) are encrypted at rest
    via ``FERNET_KEY`` and stored on the existing ``Integration`` row in
    PGLite — same envelope used by the Phase 1 direct integrations
    (SPEC §3b.5, validated by ``test_fernet_round_trip``).

Auto-registration:
  - This tool is intentionally NOT added to ``register_all_tools()``. It
    must be opted in by ``backend.tools.integrations.composio_register``
    (added in #57 once OAuth is wired). Keeping it off the canonical
    registry preserves byte-identical Phase 1-3 behaviour.
"""

from __future__ import annotations

import logging
import os
import time

from ..base import BaseTool, ToolResult

logger = logging.getLogger(__name__)


# Public sentinel error strings — exposed so callers (skills, supervisor,
# tests) can branch on the failure mode without string-matching prose.
COMPOSIO_DISABLED_ERROR = (
    "composio_disabled: ENABLE_COMPOSIO is not set. "
    "Composio is a Phase 4 integration; enable it explicitly via env."
)
COMPOSIO_MISSING_CREDENTIAL_ERROR = (
    "composio_missing_credential: COMPOSIO_API_KEY is not configured. "
    "Set it in .env or via the Integrations dashboard."
)
COMPOSIO_NOT_IMPLEMENTED_ERROR = (
    "composio_not_implemented: this is a Phase 4 spike POC. "
    "Live calls land with #57 (OAuth migration)."
)


def _flag_enabled() -> bool:
    """Honour ENABLE_COMPOSIO with the same truthy-string convention as ENABLE_TEMPORAL."""
    raw = os.getenv("ENABLE_COMPOSIO", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _api_key() -> str | None:
    key = os.getenv("COMPOSIO_API_KEY", "").strip()
    return key or None


class ComposioTool(BaseTool):  # type: ignore[override]
    """Single dispatch tool for the 864+ Composio Cloud integrations.

    Action format: ``"<app>.<verb>"`` -- e.g. ``"gmail.send"``,
    ``"github.create_pr"``, ``"slack.post_message"``. The dispatcher table
    will land in #57; this POC reports the spike status through
    ``ToolResult.error``.
    """

    name = "composio"
    description = (
        "Composio Cloud action dispatcher (Phase 4). Routes <app>.<verb> "
        "actions to the configured Composio account. Disabled by default."
    )
    # Composio is the umbrella for many integrations -- the per-app
    # whitelist check happens inside execute() once the dispatcher is wired.
    required_integrations: list[str] = []

    async def _execute(self, action: str, **kwargs) -> ToolResult:  # type: ignore[override]
        start = time.monotonic()

        if not _flag_enabled():
            logger.info("Composio call rejected: feature flag off (action=%s)", action)
            return ToolResult(
                success=False,
                error=COMPOSIO_DISABLED_ERROR,
                tool_name=self.name,
                latency_ms=(time.monotonic() - start) * 1000.0,
            )

        if _api_key() is None:
            logger.warning("Composio enabled but COMPOSIO_API_KEY missing")
            return ToolResult(
                success=False,
                error=COMPOSIO_MISSING_CREDENTIAL_ERROR,
                tool_name=self.name,
                latency_ms=(time.monotonic() - start) * 1000.0,
            )

        # Spike scope ends here. The dispatcher table + httpx client land in #57.
        logger.info("Composio dispatch placeholder hit (action=%s)", action)
        return ToolResult(
            success=False,
            error=COMPOSIO_NOT_IMPLEMENTED_ERROR,
            tool_name=self.name,
            latency_ms=(time.monotonic() - start) * 1000.0,
        )

    async def validate_auth(self, token: str | None = None) -> bool:  # type: ignore[override]
        """Cheap, side-effect-free check.

        Returns False (never raises) when:
          - the feature flag is off, OR
          - no token was supplied, OR
          - no COMPOSIO_API_KEY is configured.

        A successful 2xx round-trip against ``GET /api/v1/me`` will land in
        #57 alongside the SDK pin; this POC must not make network calls.
        """
        if not _flag_enabled():
            return False
        if not token:
            return False
        if _api_key() is None:
            return False
        # Spike: assume well-formed token == valid. #57 replaces with real call.
        return False
