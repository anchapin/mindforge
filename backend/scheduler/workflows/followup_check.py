"""FollowupCheckWorkflow — proactive unreplied-thread detection (SPEC §2.6).

Periodically queries the email inbox for threads that have gone unreplied
for longer than the configured ``days_threshold`` (default 3 days) and
creates a follow-up draft task for user approval. Each execution sweeps
once and returns the list of threads that generated a draft.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from temporalio import activity, workflow

logger = logging.getLogger(__name__)

DEFAULT_DAYS_THRESHOLD = 3
DEFAULT_DB_PATH = os.getenv("DATA_DIR", "/app/data") + "/mindforge.db"


@dataclass
class FollowupCheckParams:
    """Parameters for one FollowupCheckWorkflow execution.

    ``days_threshold`` controls how stale a thread must be before
    triggering a draft. ``db_path`` is overridable for tests.
    """

    credentials: dict[str, Any] = field(default_factory=dict)
    days_threshold: int = DEFAULT_DAYS_THRESHOLD
    db_path: str = DEFAULT_DB_PATH


@activity.defn
async def check_unreplied_threads(params: FollowupCheckParams) -> dict[str, Any]:
    """Activity: find inbox threads with no replies since ``days_threshold``.

    Uses EmailFetchTool to pull recent messages, identifies threads with
    no reply, and returns structured thread data for the workflow.
    """
    from backend.tools.email_fetch import EmailFetchTool

    tool = EmailFetchTool()
    result = await tool.execute(
        action="unreplied",
        **params.credentials,
        days_threshold=params.days_threshold,
    )
    if not result.success:
        raise RuntimeError(f"EmailFetchTool unreplied check failed: {result.error}")

    threads = result.data.get("threads", [])
    logger.info(
        "followup_check found %d unreplied threads (threshold=%d days)",
        len(threads),
        params.days_threshold,
    )
    return {
        "threads": threads,
        "count": len(threads),
        "days_threshold": params.days_threshold,
    }


@workflow.defn
class FollowupCheckWorkflow:
    """Workflow: detect unreplied threads and create draft tasks.

    Each execution sweeps the inbox once and returns the threads that
    crossed the threshold. A Temporal Schedule (installed at startup)
    re-runs this every 24 hours by default.
    """

    @workflow.run
    async def run(self, params: FollowupCheckParams) -> dict[str, Any]:
        from .email_monitor import _proactive_enabled

        if not _proactive_enabled(params.db_path):
            logger.info("FollowupCheckWorkflow: proactive monitoring disabled — skipping")
            return {"threads": [], "count": 0, "days_threshold": params.days_threshold}
        return await workflow.execute_activity(
            check_unreplied_threads,
            params,
            start_to_close_timeout=timedelta(minutes=5),
        )