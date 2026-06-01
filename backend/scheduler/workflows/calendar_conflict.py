"""CalendarConflictWorkflow — proactive calendar-conflict detection (SPEC §2.6).

Periodically checks the configured Google Calendar for overlapping events
and creates a draft task for user approval when conflicts are found.
Designed for scheduled execution (every 60 min by default via Temporal Schedules).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from temporalio import activity, workflow

logger = logging.getLogger(__name__)

DEFAULT_CHECK_INTERVAL_MINUTES = 60
DEFAULT_DB_PATH = os.getenv("DATA_DIR", "/app/data") + "/mindforge.db"


@dataclass
class CalendarConflictParams:
    """Parameters for one CalendarConflictWorkflow execution.

    ``check_hours_ahead`` controls the look-ahead window for conflict
    detection. ``db_path`` is overridable for tests.
    """

    credentials: dict[str, Any] = field(default_factory=dict)
    check_hours_ahead: int = 24
    db_path: str = DEFAULT_DB_PATH


@activity.defn
async def find_calendar_conflicts(params: CalendarConflictParams) -> dict[str, Any]:
    """Activity: detect overlapping calendar events.

    Uses GoogleCalendarTool to find conflicts within the look-ahead window.
    Returns the list of conflicts found.
    """
    from backend.tools.integrations.google_calendar import GoogleCalendarTool

    tool = GoogleCalendarTool()
    result = await tool.execute(
        action="find_conflicts",
        **params.credentials,
        hours_ahead=params.check_hours_ahead,
    )
    if not result.success:
        raise RuntimeError(f"GoogleCalendarTool find_conflicts failed: {result.error}")

    conflicts = result.data.get("conflicts", [])
    logger.info(
        "calendar_conflict_check found %d conflicts (hours_ahead=%d)",
        len(conflicts),
        params.check_hours_ahead,
    )
    return {
        "conflicts": conflicts,
        "count": len(conflicts),
        "hours_ahead": params.check_hours_ahead,
    }


@workflow.defn
class CalendarConflictWorkflow:
    """Workflow: sweep calendar for conflicts each execution.

    Each execution checks for overlaps within the look-ahead window and
    returns the detected conflicts. A Temporal Schedule re-runs this
    every ``check_interval_minutes``.
    """

    @workflow.run
    async def run(self, params: CalendarConflictParams) -> dict[str, Any]:
        from .email_monitor import _proactive_enabled

        if not _proactive_enabled(params.db_path):
            logger.info("CalendarConflictWorkflow: proactive monitoring disabled — skipping")
            return {"conflicts": [], "count": 0, "hours_ahead": params.check_hours_ahead}
        return await workflow.execute_activity(
            find_calendar_conflicts,
            params,
            start_to_close_timeout=timedelta(minutes=3),
        )