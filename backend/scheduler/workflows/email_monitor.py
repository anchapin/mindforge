"""EmailMonitorWorkflow — proactive IMAP inbox sweep (SPEC §2.6).

Periodically polls the configured IMAP inbox via EmailFetchTool and returns
the recent message envelopes so downstream skills can classify urgency or
draft follow-ups. Designed for scheduled execution (every 30 min by default
via Temporal Schedules) but can also be triggered ad hoc.

Gated by ``proactive_monitoring_enabled`` user preference (checked at each run).
"""

from __future__ import annotations

import logging
import os
import sqlite3
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from temporalio import activity, workflow

logger = logging.getLogger(__name__)

DEFAULT_INTERVAL_MINUTES = 30
DEFAULT_DB_PATH = os.getenv("DATA_DIR", "/app/data") + "/mindforge.db"


def _proactive_enabled(db_path: str) -> bool:
    """Read ``proactive_monitoring_enabled`` from the user_preference row."""
    try:
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT proactive_monitoring_enabled FROM user_preference LIMIT 1"
        ).fetchone()
        conn.close()
        if row is None:
            return True
        return bool(row["proactive_monitoring_enabled"])
    except Exception:
        return True


@dataclass
class EmailMonitorParams:
    """Parameters for one EmailMonitorWorkflow execution.

    The credentials block is intentionally a plain dict so the workflow stays
    serializable; the activity reads it via the IntegrationsManager-equivalent
    secret store in production deployments.
    """

    credentials: dict[str, Any] = field(default_factory=dict)
    limit: int = 20
    interval_minutes: int = DEFAULT_INTERVAL_MINUTES
    db_path: str = DEFAULT_DB_PATH


@activity.defn
async def fetch_recent_emails(params: EmailMonitorParams) -> list[dict[str, Any]]:
    """Activity: pull the most recent N messages from the IMAP inbox.

    Wraps EmailFetchTool so all retries / timeouts go through Temporal's
    activity machinery instead of being re-implemented here.
    """
    # Imported lazily so the workflow module can be imported without pulling
    # the rest of the tools layer (handy for unit tests that patch the activity).
    from backend.tools.email_fetch import EmailFetchTool

    tool = EmailFetchTool()
    result = await tool.execute(action="recent", **params.credentials, limit=params.limit)
    if not result.success:
        # Activity failure -> Temporal will retry per the retry policy
        raise RuntimeError(f"EmailFetchTool failed: {result.error}")
    return list(result.data.get("emails", []))


@workflow.defn
class EmailMonitorWorkflow:
    """Workflow: sweep the inbox once per execution.

    Use a Temporal Schedule (created at startup, see TemporalClient) to re-run
    this workflow every params.interval_minutes. Keeping each execution
    short-lived makes it easy to inspect runs in the Temporal UI and avoids
    the long-running-workflow versioning pitfalls.
    """

    @workflow.run
    async def run(self, params: EmailMonitorParams) -> list[dict[str, Any]]:
        if not _proactive_enabled(params.db_path):
            logger.info("EmailMonitorWorkflow: proactive monitoring disabled — skipping")
            return []
        return await workflow.execute_activity(
            fetch_recent_emails,
            params,
            start_to_close_timeout=timedelta(minutes=2),
        )
