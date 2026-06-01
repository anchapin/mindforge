"""Tests for the Temporal proactive engine — Issue #24.

Two-tier strategy so CI does not need a real Temporal broker:

1. Stub-mode tests (always run): TemporalClient defaults to ENABLE_TEMPORAL=false,
   so .start()/.shutdown()/.start_workflow() must be safe no-ops.
2. Workflow definition tests (always run): EmailMonitorWorkflow + activity must
   import, be properly decorated, and the activity must call EmailFetchTool with
   the expected arguments. End-to-end execution against a live broker is left to
   the docker-compose "temporal" profile (`docker compose --profile temporal up -d`).

Run: pytest backend/tests/integration/test_temporal.py -v
"""

from __future__ import annotations

import os
import pathlib
from unittest.mock import AsyncMock, patch

import pytest

# Patch os.makedirs BEFORE any backend imports — same pattern as other integration tests
_original_makedirs = os.makedirs


def _patched_makedirs(path, *args, **kwargs):
    if isinstance(path, pathlib.Path):
        path = str(path)
    if str(path).startswith("/app"):
        return
    return _original_makedirs(path, *args, **kwargs)


os.makedirs = _patched_makedirs  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# 1. Stub-mode TemporalClient — guards Phase 1/2 backward compatibility
# ---------------------------------------------------------------------------


class TestTemporalClientStubMode:
    """ENABLE_TEMPORAL=false (default) → every public method is a safe no-op."""

    @pytest.mark.asyncio
    async def test_default_constructor_runs_in_stub_mode(self, monkeypatch):
        monkeypatch.delenv("ENABLE_TEMPORAL", raising=False)
        from backend.scheduler.temporal_app import TemporalClient

        client = TemporalClient()
        assert client.enabled is False
        assert client._client is None
        assert client._worker is None

    @pytest.mark.asyncio
    async def test_start_is_noop_in_stub_mode(self, monkeypatch):
        monkeypatch.setenv("ENABLE_TEMPORAL", "false")
        from backend.scheduler.temporal_app import TemporalClient

        client = TemporalClient()
        await client.start()  # must not raise even though no broker exists
        assert client._client is None
        assert client._worker is None

    @pytest.mark.asyncio
    async def test_start_workflow_is_noop_in_stub_mode(self, monkeypatch):
        monkeypatch.setenv("ENABLE_TEMPORAL", "false")
        from backend.scheduler.temporal_app import TemporalClient

        client = TemporalClient()
        await client.start()
        result = await client.start_workflow(
            object,  # any sentinel — never invoked
            id="wf-stub-1",
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_shutdown_is_safe_in_stub_mode(self, monkeypatch):
        monkeypatch.setenv("ENABLE_TEMPORAL", "false")
        from backend.scheduler.temporal_app import TemporalClient

        client = TemporalClient()
        await client.start()
        await client.shutdown()  # must not raise


# ---------------------------------------------------------------------------
# 2. Enabled-but-broker-unreachable path — degrades to stub mode
# ---------------------------------------------------------------------------


class TestTemporalClientEnabledWithoutBroker:
    """ENABLE_TEMPORAL=true but Client.connect raises → swallow and stay safe."""

    @pytest.mark.asyncio
    async def test_failed_connect_does_not_raise(self, monkeypatch):
        monkeypatch.setenv("ENABLE_TEMPORAL", "true")

        async def boom(*args, **kwargs):
            raise ConnectionError("simulated: no broker")

        with patch("temporalio.client.Client.connect", side_effect=boom):
            from backend.scheduler.temporal_app import TemporalClient

            client = TemporalClient(host="127.0.0.1:1")
            # Must not raise — backend startup must remain robust per AGENTS.md rule #6
            await client.start()
            assert client._client is None
            assert client._worker is None

            # And shutdown is still callable
            await client.shutdown()


# ---------------------------------------------------------------------------
# 3. Workflow / activity definitions — import + structural checks
# ---------------------------------------------------------------------------


class TestEmailMonitorWorkflowDefinition:
    def test_workflow_module_exposes_registry(self):
        from backend.scheduler.workflows import (
            ALL_ACTIVITIES,
            ALL_WORKFLOWS,
            EmailMonitorWorkflow,
            fetch_recent_emails,
        )

        assert EmailMonitorWorkflow in ALL_WORKFLOWS
        assert fetch_recent_emails in ALL_ACTIVITIES

    def test_workflow_class_is_decorated(self):
        from temporalio.workflow import _Definition

        from backend.scheduler.workflows.email_monitor import EmailMonitorWorkflow

        defn = _Definition.must_from_class(EmailMonitorWorkflow)
        assert defn.name == "EmailMonitorWorkflow"

    def test_activity_is_decorated(self):
        from temporalio.activity import _Definition

        from backend.scheduler.workflows.email_monitor import fetch_recent_emails

        defn = _Definition.must_from_callable(fetch_recent_emails)
        assert defn.name == "fetch_recent_emails"


# ---------------------------------------------------------------------------
# 4. Activity behavior — verifies it calls EmailFetchTool correctly
# ---------------------------------------------------------------------------


class TestFetchRecentEmailsActivity:
    @pytest.mark.asyncio
    async def test_activity_returns_emails_from_tool(self):
        from backend.scheduler.workflows.email_monitor import (
            EmailMonitorParams,
            fetch_recent_emails,
        )
        from backend.tools.base import ToolResult

        fake = ToolResult(
            success=True,
            data={"emails": [{"from": "x@y.com", "subject": "hi", "date": "", "body": ""}]},
            latency_ms=1.0,
        )

        with patch(
            "backend.tools.email_fetch.EmailFetchTool.execute",
            new=AsyncMock(return_value=fake),
        ) as mock_execute:
            result = await fetch_recent_emails(
                EmailMonitorParams(
                    credentials={
                        "host": "imap.gmail.com",
                        "username": "user@example.com",
                        "password": "app-password",
                    },
                    limit=5,
                )
            )

        assert result == fake.data["emails"]
        mock_execute.assert_awaited_once()
        kwargs = mock_execute.await_args.kwargs
        assert kwargs["action"] == "recent"
        assert kwargs["host"] == "imap.gmail.com"
        assert kwargs["limit"] == 5

    @pytest.mark.asyncio
    async def test_activity_raises_on_tool_failure(self):
        from backend.scheduler.workflows.email_monitor import (
            EmailMonitorParams,
            fetch_recent_emails,
        )
        from backend.tools.base import ToolResult

        with patch(
            "backend.tools.email_fetch.EmailFetchTool.execute",
            new=AsyncMock(return_value=ToolResult(success=False, error="auth", latency_ms=0)),
        ), pytest.raises(RuntimeError, match="EmailFetchTool failed: auth"):
            await fetch_recent_emails(EmailMonitorParams(credentials={}))


# ---------------------------------------------------------------------------
# 5. FollowupCheckWorkflow + activity
# ---------------------------------------------------------------------------


class TestFollowupCheckWorkflowDefinition:
    def test_workflow_in_registry(self):
        from backend.scheduler.workflows import (
            ALL_ACTIVITIES,
            ALL_WORKFLOWS,
            FollowupCheckWorkflow,
            check_unreplied_threads,
        )

        assert FollowupCheckWorkflow in ALL_WORKFLOWS
        assert check_unreplied_threads in ALL_ACTIVITIES

    def test_workflow_class_is_decorated(self):
        from temporalio.workflow import _Definition

        from backend.scheduler.workflows.followup_check import FollowupCheckWorkflow

        defn = _Definition.must_from_class(FollowupCheckWorkflow)
        assert defn.name == "FollowupCheckWorkflow"

    def test_activity_is_decorated(self):
        from temporalio.activity import _Definition

        from backend.scheduler.workflows.followup_check import check_unreplied_threads

        defn = _Definition.must_from_callable(check_unreplied_threads)
        assert defn.name == "check_unreplied_threads"


class TestCheckUnrepliedThreadsActivity:
    @pytest.mark.asyncio
    async def test_activity_returns_threads_from_tool(self):
        from backend.scheduler.workflows.followup_check import (
            FollowupCheckParams,
            check_unreplied_threads,
        )
        from backend.tools.base import ToolResult

        fake = ToolResult(
            success=True,
            data={
                "threads": [
                    {"from": "x@y.com", "subject": "Re: hi", "date": ""},
                    {"from": "z@w.com", "subject": "follow up", "date": ""},
                ]
            },
            latency_ms=1.0,
        )

        with patch(
            "backend.tools.email_fetch.EmailFetchTool.execute",
            new=AsyncMock(return_value=fake),
        ):
            result = await check_unreplied_threads(
                FollowupCheckParams(
                    credentials={"host": "imap.gmail.com", "username": "u", "password": "p"},
                    days_threshold=3,
                )
            )

        assert result["count"] == 2
        assert len(result["threads"]) == 2

    @pytest.mark.asyncio
    async def test_activity_raises_on_tool_failure(self):
        from backend.scheduler.workflows.followup_check import (
            FollowupCheckParams,
            check_unreplied_threads,
        )
        from backend.tools.base import ToolResult

        with patch(
            "backend.tools.email_fetch.EmailFetchTool.execute",
            new=AsyncMock(return_value=ToolResult(success=False, error="imap error", latency_ms=0)),
        ), pytest.raises(RuntimeError, match="EmailFetchTool unreplied check failed: imap error"):
            await check_unreplied_threads(FollowupCheckParams(credentials={}))


# ---------------------------------------------------------------------------
# 6. CalendarConflictWorkflow + activity
# ---------------------------------------------------------------------------


class TestCalendarConflictWorkflowDefinition:
    def test_workflow_in_registry(self):
        from backend.scheduler.workflows import (
            ALL_ACTIVITIES,
            ALL_WORKFLOWS,
            CalendarConflictWorkflow,
            find_calendar_conflicts,
        )

        assert CalendarConflictWorkflow in ALL_WORKFLOWS
        assert find_calendar_conflicts in ALL_ACTIVITIES

    def test_workflow_class_is_decorated(self):
        from temporalio.workflow import _Definition

        from backend.scheduler.workflows.calendar_conflict import CalendarConflictWorkflow

        defn = _Definition.must_from_class(CalendarConflictWorkflow)
        assert defn.name == "CalendarConflictWorkflow"

    def test_activity_is_decorated(self):
        from temporalio.activity import _Definition

        from backend.scheduler.workflows.calendar_conflict import find_calendar_conflicts

        defn = _Definition.must_from_callable(find_calendar_conflicts)
        assert defn.name == "find_calendar_conflicts"


class TestFindCalendarConflictsActivity:
    @pytest.mark.asyncio
    async def test_activity_returns_conflicts_from_tool(self):
        from backend.scheduler.workflows.calendar_conflict import (
            CalendarConflictParams,
            find_calendar_conflicts,
        )
        from backend.tools.base import ToolResult

        fake = ToolResult(
            success=True,
            data={
                "conflicts": [
                    {"title": "Meeting A", "start": "2026-06-01T10:00", "end": "11:00"},
                    {"title": "Meeting B", "start": "2026-06-01T10:30", "end": "11:30"},
                ]
            },
            latency_ms=1.0,
        )

        with patch(
            "backend.tools.integrations.google_calendar.GoogleCalendarTool.execute",
            new=AsyncMock(return_value=fake),
        ):
            result = await find_calendar_conflicts(
                CalendarConflictParams(
                    credentials={},
                    check_hours_ahead=24,
                )
            )

        assert result["count"] == 2
        assert len(result["conflicts"]) == 2

    @pytest.mark.asyncio
    async def test_activity_raises_on_tool_failure(self):
        from backend.scheduler.workflows.calendar_conflict import (
            CalendarConflictParams,
            find_calendar_conflicts,
        )
        from backend.tools.base import ToolResult

        with patch(
            "backend.tools.integrations.google_calendar.GoogleCalendarTool.execute",
            new=AsyncMock(return_value=ToolResult(success=False, error="calendar error", latency_ms=0)),
        ), pytest.raises(RuntimeError, match="GoogleCalendarTool find_conflicts failed: calendar error"):
            await find_calendar_conflicts(CalendarConflictParams(credentials={}))


# ---------------------------------------------------------------------------
# 7. proactive_monitoring_enabled gating
# ---------------------------------------------------------------------------


class TestProactiveMonitoringGating:
    @pytest.mark.asyncio
    async def test_email_monitor_skips_when_disabled(self, monkeypatch):
        from backend.scheduler.workflows.email_monitor import (
            EmailMonitorParams,
            EmailMonitorWorkflow,
        )

        monkeypatch.setenv("ENABLE_TEMPORAL", "false")
        monkeypatch.setattr(
            "backend.scheduler.workflows.email_monitor._proactive_enabled",
            lambda db_path: False,
        )
        params = EmailMonitorParams()
        wf = EmailMonitorWorkflow()
        result = await wf.run(params)
        assert result == []

    @pytest.mark.asyncio
    async def test_followup_check_skips_when_disabled(self, monkeypatch):
        from backend.scheduler.workflows.followup_check import (
            FollowupCheckParams,
            FollowupCheckWorkflow,
        )

        monkeypatch.setenv("ENABLE_TEMPORAL", "false")
        # _proactive_enabled is imported from email_monitor into followup_check
        monkeypatch.setattr(
            "backend.scheduler.workflows.email_monitor._proactive_enabled",
            lambda db_path: False,
        )
        params = FollowupCheckParams()
        wf = FollowupCheckWorkflow()
        result = await wf.run(params)
        assert result["count"] == 0
        assert result["threads"] == []

    @pytest.mark.asyncio
    async def test_calendar_conflict_skips_when_disabled(self, monkeypatch):
        from backend.scheduler.workflows.calendar_conflict import (
            CalendarConflictParams,
            CalendarConflictWorkflow,
        )

        monkeypatch.setenv("ENABLE_TEMPORAL", "false")
        monkeypatch.setattr(
            "backend.scheduler.workflows.email_monitor._proactive_enabled",
            lambda db_path: False,
        )
        params = CalendarConflictParams()
        wf = CalendarConflictWorkflow()
        result = await wf.run(params)
        assert result["count"] == 0
        assert result["conflicts"] == []

    @pytest.mark.asyncio
    async def test_all_workflows_skip_when_disabled(self, monkeypatch):
        """Verify all three workflows short-circuit when proactive monitoring is off.

        This tests the gating logic without calling execute_activity, so it
        works without a Temporal broker in the test environment.
        """
        from backend.scheduler.workflows.email_monitor import (
            EmailMonitorParams,
            EmailMonitorWorkflow,
        )
        from backend.scheduler.workflows.followup_check import (
            FollowupCheckParams,
            FollowupCheckWorkflow,
        )
        from backend.scheduler.workflows.calendar_conflict import (
            CalendarConflictParams,
            CalendarConflictWorkflow,
        )

        monkeypatch.setenv("ENABLE_TEMPORAL", "false")
        monkeypatch.setattr(
            "backend.scheduler.workflows.email_monitor._proactive_enabled",
            lambda db_path: False,
        )

        # EmailMonitor
        wf1 = EmailMonitorWorkflow()
        result1 = await wf1.run(EmailMonitorParams())
        assert result1 == []

        # FollowupCheck
        wf2 = FollowupCheckWorkflow()
        result2 = await wf2.run(FollowupCheckParams())
        assert result2["count"] == 0
        assert result2["threads"] == []

        # CalendarConflict
        wf3 = CalendarConflictWorkflow()
        result3 = await wf3.run(CalendarConflictParams())
        assert result3["count"] == 0
        assert result3["conflicts"] == []
