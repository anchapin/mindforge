"""Temporal workflow + activity registry.

ALL_WORKFLOWS / ALL_ACTIVITIES are imported by TemporalClient.start() so the
worker registers everything in this package automatically. Add a new workflow:
1. Implement it in backend/scheduler/workflows/<name>.py.
2. Append the workflow class to ALL_WORKFLOWS and its activities to ALL_ACTIVITIES.
"""

from __future__ import annotations

from .email_monitor import (
    EmailMonitorParams,
    EmailMonitorWorkflow,
    fetch_recent_emails,
)

ALL_WORKFLOWS: tuple = (EmailMonitorWorkflow,)
ALL_ACTIVITIES: tuple = (fetch_recent_emails,)

__all__ = [
    "ALL_WORKFLOWS",
    "ALL_ACTIVITIES",
    "EmailMonitorWorkflow",
    "EmailMonitorParams",
    "fetch_recent_emails",
]
