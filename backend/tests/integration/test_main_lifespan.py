"""Verify the FastAPI lifespan registers built-in tools at startup (#42-#44 P1).

Pre-fix: register_all_tools() was defined and unit-tested, but nothing in
the production code path called it. Test fixtures registered tools manually,
masking the bug. As a result, POST /api/integrations/{id}/test returned
"No tool 'X' registered" for every real integration in production.

This test pins the wiring: a TestClient with the real app must, after
startup, have the canonical tool names resolvable via ToolRegistry.
"""

from __future__ import annotations

# ----- pre-import patches -------------------------------------------------
import os
import pathlib

_ORIGINAL_MAKEDIRS = os.makedirs


def _safe_makedirs(path, *args, **kwargs):
    if isinstance(path, pathlib.Path):
        path = str(path)
    if str(path).startswith("/app"):
        return
    return _ORIGINAL_MAKEDIRS(path, *args, **kwargs)


os.makedirs = _safe_makedirs  # type: ignore[assignment]

from cryptography.fernet import Fernet  # noqa: E402

os.environ.setdefault("FERNET_KEY", Fernet.generate_key().decode())
os.environ.setdefault("OPENROUTER_API_KEY", "sk-test-not-real")
# --------------------------------------------------------------------------

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture
def app_client():
    """Boot the real FastAPI app inside a TestClient context. The TestClient
    runs the lifespan (startup/shutdown) so register_all_tools() fires."""
    # Clear the registry first so we know any tools present afterwards came
    # from the lifespan, not from a previous test that registered manually.
    from backend.tools.registry import ToolRegistry

    ToolRegistry._tools.clear()

    # Import the app fresh
    from backend.main import app

    with TestClient(app) as client:
        yield client

    ToolRegistry._tools.clear()


class TestLifespanToolRegistration:
    """Lifespan must populate ToolRegistry with all built-in tools."""

    def test_stripe_tool_registered_after_startup(self, app_client):
        from backend.tools.registry import ToolRegistry

        # Should not raise
        tool = ToolRegistry.get("stripe_api")
        assert tool is not None
        assert tool.name == "stripe_api"

    def test_github_tool_registered_after_startup(self, app_client):
        from backend.tools.registry import ToolRegistry

        tool = ToolRegistry.get("github_api")
        assert tool.name == "github_api"

    def test_email_send_tool_registered_after_startup(self, app_client):
        """Specifically pins the wiring for the #42 EmailSendTool — the
        review found it was registered in the registry module but the
        registry's auto-register function was never called at startup."""
        from backend.tools.registry import ToolRegistry

        tool = ToolRegistry.get("email_send")
        assert tool.name == "email_send"

    def test_email_fetch_tool_registered_after_startup(self, app_client):
        from backend.tools.registry import ToolRegistry

        tool = ToolRegistry.get("email_fetch")
        assert tool.name == "email_fetch"

    def test_linear_tool_registered_after_startup(self, app_client):
        from backend.tools.registry import ToolRegistry

        tool = ToolRegistry.get("linear_api")
        assert tool.name == "linear_api"

    def test_all_canonical_tool_names_are_resolvable(self, app_client):
        """Every name listed in routes/integrations.py _PROBE_TOOL_FOR_APP
        must resolve. Catches a typo'd entry (the integration probe will
        otherwise quietly return 'No tool X registered')."""
        from backend.api.routes.integrations import _PROBE_TOOL_FOR_APP
        from backend.tools.registry import ToolRegistry

        for app_name, tool_name in _PROBE_TOOL_FOR_APP.items():
            tool = ToolRegistry.get(tool_name)
            assert tool.name == tool_name, (
                f"_PROBE_TOOL_FOR_APP[{app_name!r}] = {tool_name!r} "
                f"but ToolRegistry returned a tool named {tool.name!r}"
            )


class TestLifespanResilience:
    """register_all_tools() failure must not crash startup."""

    def test_startup_succeeds_even_if_a_tool_fails_to_construct(
        self, monkeypatch
    ):
        """Lifespan wraps register_all_tools in try/except; a single tool
        construction failure shouldn't prevent the API from serving."""
        from backend.tools import registry

        ToolRegistry = registry.ToolRegistry
        ToolRegistry._tools.clear()

        # Force register_all_tools to raise
        def boom():
            raise RuntimeError("simulated tool registration failure")

        monkeypatch.setattr(registry, "register_all_tools", boom)
        # Patch the symbol that backend.main re-imported
        import backend.main

        monkeypatch.setattr(backend.main, "register_all_tools", boom)

        # App must still boot and serve /health
        from backend.main import app

        with TestClient(app) as client:
            resp = client.get("/health")
            assert resp.status_code == 200

        ToolRegistry._tools.clear()


class TestSourceGuards:
    """Pin the regression: backend/main.py MUST call register_all_tools()."""

    def test_main_imports_register_all_tools(self):
        import backend.main as main_mod

        source = pathlib.Path(main_mod.__file__).read_text()
        assert "register_all_tools" in source, (
            "backend/main.py must import + call register_all_tools() at "
            "startup. Without it the integrations test endpoint always "
            "returns 'No tool X registered' — see Wave 2 P1 post-mortem."
        )
        assert "register_all_tools()" in source, (
            "register_all_tools must be CALLED, not just imported"
        )
