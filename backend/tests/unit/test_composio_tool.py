"""Unit tests for ComposioTool — Phase 4 spike (#56).

Covers the flag-gated POC tool delivered as part of the Composio integration
spike. Live API calls are intentionally NOT exercised; that is reserved for
follow-up issues #57 (OAuth migration) and #58 (7-day soak).

Pre-spike state: no module existed.

Post-spike:
  - Importing the module never crashes (import is safe even when the
    `composio` SDK is absent — Phase 1-3 must keep working).
  - When ENABLE_COMPOSIO is unset/false, execute() returns a clean,
    actionable disabled error -- never raises, never hits the network.
  - When ENABLE_COMPOSIO is true but COMPOSIO_API_KEY is missing,
    execute() reports the missing-credential failure mode.
  - validate_auth() returns False (not raise) when credentials are absent.
  - The tool is NOT auto-registered by register_all_tools(); Phase 1-3
    behaviour must remain byte-identical when the flag is off.
"""

from __future__ import annotations

import pytest

from backend.tools.integrations.composio import (
    COMPOSIO_DISABLED_ERROR,
    COMPOSIO_MISSING_CREDENTIAL_ERROR,
    ComposioTool,
)
from backend.tools.registry import ToolRegistry, register_all_tools


@pytest.fixture(autouse=True)
def _clean_registry():
    """ToolRegistry is a class-level singleton — reset between tests."""
    ToolRegistry._tools.clear()
    yield
    ToolRegistry._tools.clear()


@pytest.fixture(autouse=True)
def _no_composio_env(monkeypatch):
    """Default: simulate a fresh install with no Composio config."""
    monkeypatch.delenv("ENABLE_COMPOSIO", raising=False)
    monkeypatch.delenv("COMPOSIO_API_KEY", raising=False)


# ---------------------------------------------------------------------------
# Disabled-by-default behaviour
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_returns_disabled_when_flag_unset():
    tool = ComposioTool()
    result = await tool.execute("gmail.send", to="user@example.com", subject="hi", body="x")
    assert result.success is False
    assert result.error == COMPOSIO_DISABLED_ERROR
    assert result.tool_name == "composio"


@pytest.mark.asyncio
async def test_execute_returns_disabled_when_flag_false(monkeypatch):
    monkeypatch.setenv("ENABLE_COMPOSIO", "false")
    tool = ComposioTool()
    result = await tool.execute("gmail.send")
    assert result.success is False
    assert result.error == COMPOSIO_DISABLED_ERROR


@pytest.mark.asyncio
async def test_execute_reports_missing_credential_when_enabled_without_key(monkeypatch):
    monkeypatch.setenv("ENABLE_COMPOSIO", "true")
    tool = ComposioTool()
    result = await tool.execute("gmail.send")
    assert result.success is False
    assert result.error == COMPOSIO_MISSING_CREDENTIAL_ERROR


# ---------------------------------------------------------------------------
# validate_auth contract
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_validate_auth_returns_false_with_no_token():
    tool = ComposioTool()
    assert await tool.validate_auth(None) is False
    assert await tool.validate_auth("") is False


@pytest.mark.asyncio
async def test_validate_auth_returns_false_when_disabled(monkeypatch):
    """Even with a token, do not waste a network call when the flag is off."""
    monkeypatch.delenv("ENABLE_COMPOSIO", raising=False)
    tool = ComposioTool()
    assert await tool.validate_auth("ck_live_dummy") is False


# ---------------------------------------------------------------------------
# Phase-isolation guarantee — POC must NOT auto-register
# ---------------------------------------------------------------------------


def test_register_all_tools_does_not_register_composio():
    """register_all_tools() must remain Phase 1-3 only (#56 is Phase 4)."""
    register_all_tools()
    assert "composio" not in ToolRegistry.list_names()


# ---------------------------------------------------------------------------
# Tool metadata sanity
# ---------------------------------------------------------------------------


def test_tool_metadata_matches_basetool_contract():
    tool = ComposioTool()
    assert tool.name == "composio"
    assert "composio" in tool.description.lower()
    # Composio is the umbrella for many integrations; the dispatcher uses
    # the action prefix to route — required_integrations stays empty so it
    # doesn't trip Phase 1 integration whitelists.
    assert tool.required_integrations == []
