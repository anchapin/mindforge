"""EmailMonitorWorkflow — proactive IMAP inbox sweep (SPEC §5.3).

Periodically polls the configured IMAP inbox via EmailFetchTool and returns
the recent message envelopes so downstream skills can classify urgency or
draft follow-ups. Designed for scheduled execution (every 30 min by default
via Temporal Schedules) but can also be triggered ad hoc.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from temporalio import activity, workflow

DEFAULT_INTERVAL_MINUTES = 30


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
        return await workflow.execute_activity(
            fetch_recent_emails,
            params,
            start_to_close_timeout=timedelta(minutes=2),
        )
