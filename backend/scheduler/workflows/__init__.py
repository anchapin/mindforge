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
from .oauth_refresh import (
    OAuthRefreshParams,
    OAuthRefreshWorkflow,
    ensure_oauth_refresh_schedule,
    refresh_composio_bearers,
)

ALL_WORKFLOWS: tuple = (EmailMonitorWorkflow, OAuthRefreshWorkflow)
ALL_ACTIVITIES: tuple = (fetch_recent_emails, refresh_composio_bearers)

__all__ = [
    "ALL_WORKFLOWS",
    "ALL_ACTIVITIES",
    "EmailMonitorWorkflow",
    "EmailMonitorParams",
    "fetch_recent_emails",
    "OAuthRefreshWorkflow",
    "OAuthRefreshParams",
    "refresh_composio_bearers",
    "ensure_oauth_refresh_schedule",
]
