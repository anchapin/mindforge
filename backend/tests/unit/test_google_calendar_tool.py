"""Unit tests for GoogleCalendarTool (#57 part C).

Composio-mediated per ADR-0001 -- the live SDK call is intentionally a
structured ``not_implemented`` outcome until the SDK is pinned, but the
observable contract (action surface, error sentinels, validate_auth
shape) is final.

Pre-spike state: no module existed.

Post-PR-C contract:
  - Disabled-by-default: execute() returns COMPOSIO_DISABLED_ERROR when
    ENABLE_COMPOSIO is unset/false; no network call.
  - Missing-key: ENABLE_COMPOSIO=true, no COMPOSIO_API_KEY -> distinct
    sentinel error.
  - Action surface: list_events + find_conflicts dispatch shape pinned.
  - Tool is auto-registered by register_all_tools() so the
    calendar-conflict skill can resolve it by name.
"""

from __future__ import annotations

import pytest

from backend.tools.integrations.google_calendar import (
    CALENDAR_DISABLED_ERROR,
    CALENDAR_MISSING_CREDENTIAL_ERROR,
    CALENDAR_NOT_IMPLEMENTED_ERROR,
    CALENDAR_UNKNOWN_ACTION_ERROR,
    GoogleCalendarTool,
)
from backend.tools.registry import ToolRegistry, register_all_tools


@pytest.fixture(autouse=True)
def _clean_registry():
    ToolRegistry._tools.clear()
    yield
    ToolRegistry._tools.clear()


@pytest.fixture(autouse=True)
def _no_composio_env(monkeypatch):
    monkeypatch.delenv("ENABLE_COMPOSIO", raising=False)
    monkeypatch.delenv("COMPOSIO_API_KEY", raising=False)


# ---------------------------------------------------------------------------
# Disabled-by-default behaviour
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_events_disabled_when_flag_unset():
    tool = GoogleCalendarTool()
    result = await tool.execute("list_events")
    assert result.success is False
    assert result.error == CALENDAR_DISABLED_ERROR
    assert result.tool_name == "google_calendar"


@pytest.mark.asyncio
async def test_find_conflicts_disabled_when_flag_unset():
    tool = GoogleCalendarTool()
    result = await tool.execute(
        "find_conflicts",
        start_iso="2026-05-15T14:00:00-04:00",
        end_iso="2026-05-15T15:00:00-04:00",
    )
    assert result.success is False
    assert result.error == CALENDAR_DISABLED_ERROR


@pytest.mark.asyncio
async def test_returns_missing_credential_when_enabled_without_key(monkeypatch):
    monkeypatch.setenv("ENABLE_COMPOSIO", "true")
    tool = GoogleCalendarTool()
    result = await tool.execute("list_events")
    assert result.success is False
    assert result.error == CALENDAR_MISSING_CREDENTIAL_ERROR


@pytest.mark.asyncio
async def test_unknown_action_rejected(monkeypatch):
    """Unknown actions must fail loudly even when fully configured."""
    monkeypatch.setenv("ENABLE_COMPOSIO", "true")
    monkeypatch.setenv("COMPOSIO_API_KEY", "ck_dummy")
    tool = GoogleCalendarTool()
    result = await tool.execute("delete_calendar")
    assert result.success is False
    assert result.error == CALENDAR_UNKNOWN_ACTION_ERROR


@pytest.mark.asyncio
async def test_known_action_returns_not_implemented_until_sdk_pinned(monkeypatch):
    monkeypatch.setenv("ENABLE_COMPOSIO", "true")
    monkeypatch.setenv("COMPOSIO_API_KEY", "ck_dummy")
    tool = GoogleCalendarTool()
    for action in ("list_events", "find_conflicts"):
        result = await tool.execute(
            action,
            start_iso="2026-05-15T14:00:00-04:00",
            end_iso="2026-05-15T15:00:00-04:00",
        )
        assert result.success is False
        assert result.error == CALENDAR_NOT_IMPLEMENTED_ERROR


# ---------------------------------------------------------------------------
# validate_auth contract
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_validate_auth_returns_false_with_no_token():
    tool = GoogleCalendarTool()
    assert await tool.validate_auth(None) is False
    assert await tool.validate_auth("") is False


@pytest.mark.asyncio
async def test_validate_auth_returns_false_when_disabled(monkeypatch):
    monkeypatch.delenv("ENABLE_COMPOSIO", raising=False)
    tool = GoogleCalendarTool()
    assert await tool.validate_auth("ca_dummy") is False


# ---------------------------------------------------------------------------
# Phase isolation -- now we DO want auto-registration so the
# calendar-conflict skill can resolve "google_calendar" by name. But the
# call must still be a no-op (disabled error) without env config.
# ---------------------------------------------------------------------------


def test_register_all_tools_includes_google_calendar():
    register_all_tools()
    assert "google_calendar" in ToolRegistry.list_names()


def test_tool_metadata():
    tool = GoogleCalendarTool()
    assert tool.name == "google_calendar"
    assert "calendar" in tool.description.lower()
    assert tool.required_integrations == ["google_calendar"]
