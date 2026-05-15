"""OAuthRefreshWorkflow + activity -- background bearer refresh (#57 part B).

Per ADR-0001 (#56) Composio handles the OAuth grant; MindForge stores the
``connected_account_id`` Fernet-encrypted on the ``integration`` row and
must periodically fetch a fresh bearer from Composio so downstream tools
keep working without user intervention.

Triple-gated phase isolation:

  - ``ENABLE_TEMPORAL=false`` -> no schedule, no worker run (gated upstream
    by ``TemporalClient``).
  - ``ENABLE_COMPOSIO=false``  -> activity returns a structured ``skipped``
    result and never enumerates the integration table.
  - ``ENABLE_COMPOSIO=true`` but no ``COMPOSIO_API_KEY`` -> activity
    returns ``skipped`` with the missing-key reason.

When all gates pass the activity enumerates ``integration`` rows where
``extra.oauth_broker == "composio"``, advances ``last_sync_at`` so
operators can see heartbeating, and (PR C) fetches a fresh bearer via
the Composio SDK. Until the SDK is pinned the per-row outcome is the
explicit ``REFRESH_NOT_IMPLEMENTED_REASON`` so failures are observable
rather than silent.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from temporalio import activity, workflow

logger = logging.getLogger(__name__)


# Defaults -- the schedule below installs the workflow at this cadence.
DEFAULT_REFRESH_INTERVAL_MINUTES = 5
DEFAULT_DB_PATH = os.getenv("DATA_DIR", "/app/data") + "/mindforge.db"

# Public reason strings -- callers (ops dashboards, tests) branch on these
# rather than prose-matching log lines.
REFRESH_DISABLED_REASON = "composio_disabled"
REFRESH_MISSING_KEY_REASON = "composio_missing_key"
REFRESH_NOT_IMPLEMENTED_REASON = "composio_sdk_not_pinned"

SCHEDULE_ID = "oauth-refresh"
WORKFLOW_ID_PREFIX = "oauth-refresh"


def _flag_enabled() -> bool:
    raw = os.getenv("ENABLE_COMPOSIO", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _api_key() -> str | None:
    key = os.getenv("COMPOSIO_API_KEY", "").strip()
    return key or None


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class OAuthRefreshParams:
    """Parameters for one OAuthRefreshWorkflow execution.

    ``db_path`` is overridable so tests can point at an isolated SQLite
    file; production callers should use the default which resolves the
    same path the FastAPI dependency layer uses.
    """

    db_path: str = DEFAULT_DB_PATH
    interval_minutes: int = DEFAULT_REFRESH_INTERVAL_MINUTES


def _is_composio_row(extra_blob: str | None) -> bool:
    """True iff the ``extra`` column carries ``oauth_broker = "composio"``."""
    if not extra_blob:
        return False
    try:
        parsed = json.loads(extra_blob)
    except (TypeError, ValueError):
        return False
    return isinstance(parsed, dict) and parsed.get("oauth_broker") == "composio"


@activity.defn
async def refresh_composio_bearers(params: OAuthRefreshParams) -> dict[str, Any]:
    """Activity: enumerate Composio-mediated integrations and refresh bearers.

    Returns a structured outcome dict so the workflow (and ops tooling)
    can branch on it without log-scraping.
    """
    if not _flag_enabled():
        return {
            "status": "skipped",
            "reason": REFRESH_DISABLED_REASON,
            "refreshed": 0,
            "attempted": 0,
        }
    if _api_key() is None:
        return {
            "status": "skipped",
            "reason": REFRESH_MISSING_KEY_REASON,
            "refreshed": 0,
            "attempted": 0,
        }

    conn = sqlite3.connect(params.db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT id, app_name, extra, auth_token_enc FROM integration "
            "WHERE status = 'active'"
        ).fetchall()

        outcomes: list[dict[str, Any]] = []
        skipped_non_composio = 0
        attempted = 0
        refreshed = 0
        pending_implementation = 0
        now = _now_iso()

        for row in rows:
            if not _is_composio_row(row["extra"]):
                skipped_non_composio += 1
                continue

            attempted += 1
            # PR C swaps this stub for a real Composio SDK call. The
            # observable contract (return shape) stays identical so the
            # workflow + tests don't churn.
            outcome_reason = REFRESH_NOT_IMPLEMENTED_REASON
            pending_implementation += 1

            outcomes.append(
                {
                    "id": row["id"],
                    "app": row["app_name"],
                    "reason": outcome_reason,
                }
            )

            # Advance last_sync_at so operators can see the worker is
            # heartbeating against the row even before the SDK lands.
            conn.execute(
                "UPDATE integration SET last_sync_at = ?, updated_at = ? "
                "WHERE id = ?",
                (now, now, row["id"]),
            )

        conn.commit()

        logger.info(
            "oauth_refresh attempted=%d refreshed=%d pending=%d skipped_non_composio=%d",
            attempted,
            refreshed,
            pending_implementation,
            skipped_non_composio,
        )

        return {
            "status": "ok",
            "attempted": attempted,
            "refreshed": refreshed,
            "pending_implementation": pending_implementation,
            "skipped_non_composio": skipped_non_composio,
            "outcomes": outcomes,
        }
    finally:
        conn.close()


@workflow.defn
class OAuthRefreshWorkflow:
    """Workflow: sweep all Composio integrations once per execution.

    Use a Temporal Schedule (installed via ``ensure_oauth_refresh_schedule``)
    to re-run this workflow every ``params.interval_minutes``. Keeping
    each execution short-lived sidesteps long-running-workflow versioning
    pitfalls and matches the EmailMonitorWorkflow pattern.
    """

    @workflow.run
    async def run(self, params: OAuthRefreshParams) -> dict[str, Any]:
        return await workflow.execute_activity(
            refresh_composio_bearers,
            params,
            start_to_close_timeout=timedelta(minutes=2),
        )


async def ensure_oauth_refresh_schedule(client: Any) -> bool:
    """Install the recurring schedule for OAuthRefreshWorkflow.

    Returns ``True`` when the schedule was successfully installed (or was
    already present) and ``False`` when no install was attempted (e.g.
    TemporalClient is in stub mode, or the schedule API isn't reachable).

    Errors are logged and swallowed -- AGENTS.md rule #6: phase scope
    isolation must keep backend startup robust even when the broker is
    unhealthy.
    """
    underlying = getattr(client, "_client", None)
    if underlying is None:
        # Stub mode -- nothing to do, but make the no-op observable.
        logger.info(
            "oauth_refresh schedule skipped: TemporalClient is in stub mode"
        )
        return False

    try:
        from temporalio.client import (  # noqa: WPS433  (intentional lazy import)
            Schedule,
            ScheduleActionStartWorkflow,
            ScheduleAlreadyRunningError,
            ScheduleIntervalSpec,
            ScheduleSpec,
        )

        from ..temporal_app import DEFAULT_TASK_QUEUE

        params = OAuthRefreshParams()
        spec = ScheduleSpec(
            intervals=[
                ScheduleIntervalSpec(
                    every=timedelta(minutes=params.interval_minutes)
                )
            ]
        )
        action = ScheduleActionStartWorkflow(
            OAuthRefreshWorkflow.run,
            params,
            id=f"{WORKFLOW_ID_PREFIX}-{int(datetime.now(UTC).timestamp())}",
            task_queue=DEFAULT_TASK_QUEUE,
        )
        try:
            await underlying.create_schedule(
                SCHEDULE_ID,
                Schedule(action=action, spec=spec),
            )
        except ScheduleAlreadyRunningError:
            # Idempotent: a previous boot installed it.
            logger.info("oauth_refresh schedule already installed")
        return True
    except Exception as exc:  # pragma: no cover - exercised only with a broker
        logger.warning(
            "oauth_refresh schedule install failed -- continuing without it (%s)",
            exc,
        )
        return False
