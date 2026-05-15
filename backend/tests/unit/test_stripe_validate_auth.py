"""Unit tests for StripeTool.validate_auth and GitHubTool.validate_auth (#44).

Pre-fix bugs:
  - StripeTool used a literal "sk_test_placeholder" string and treated 401 as
    success, so it could never report bad credentials.
  - GitHubTool sent `Authorization: Bearer ` (empty token) — always failed.

Post-fix:
  - validate_auth(token) accepts the real token.
  - 200 -> True; 401/4xx -> False; network error -> False.
  - Missing token -> False (don't waste an API call).
"""

from __future__ import annotations

import httpx
import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeResp:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


class _FakeClient:
    """Captures URL + Authorization header, returns a canned response."""

    last_url: str | None = None
    last_headers: dict | None = None

    def __init__(self, response_or_exc):
        self._response_or_exc = response_or_exc

    def __call__(self, *args, **kwargs):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, url, headers=None, **kwargs):
        _FakeClient.last_url = url
        _FakeClient.last_headers = headers or {}
        if isinstance(self._response_or_exc, Exception):
            raise self._response_or_exc
        return self._response_or_exc


@pytest.fixture(autouse=True)
def _bypass_rate_limiter(monkeypatch):
    """integration_call's semaphore would block tests; pass through."""

    async def _passthrough(_integration, fn, *args, **kwargs):
        return await fn(*args, **kwargs)

    monkeypatch.setattr("backend.tools.stripe.integration_call", _passthrough)
    monkeypatch.setattr("backend.tools.github.integration_call", _passthrough)


# ---------------------------------------------------------------------------
# StripeTool
# ---------------------------------------------------------------------------


class TestStripeValidateAuth:
    @pytest.mark.asyncio
    async def test_returns_true_on_200(self, monkeypatch):
        from backend.tools.stripe import StripeTool

        fake = _FakeClient(_FakeResp(200))
        monkeypatch.setattr("backend.tools.stripe.httpx.AsyncClient", fake)

        ok = await StripeTool().validate_auth(token="sk_live_realtoken")

        assert ok is True
        # The real token, not the literal placeholder, must reach the wire
        assert _FakeClient.last_headers["Authorization"] == "Bearer sk_live_realtoken"
        assert "sk_test_placeholder" not in str(_FakeClient.last_headers)

    @pytest.mark.asyncio
    async def test_returns_false_on_401(self, monkeypatch):
        from backend.tools.stripe import StripeTool

        fake = _FakeClient(_FakeResp(401))
        monkeypatch.setattr("backend.tools.stripe.httpx.AsyncClient", fake)

        # Pre-fix this returned True (401 was in the success set).
        assert await StripeTool().validate_auth(token="sk_live_bad") is False

    @pytest.mark.asyncio
    async def test_returns_false_on_5xx(self, monkeypatch):
        from backend.tools.stripe import StripeTool

        fake = _FakeClient(_FakeResp(503))
        monkeypatch.setattr("backend.tools.stripe.httpx.AsyncClient", fake)
        assert await StripeTool().validate_auth(token="sk_live_x") is False

    @pytest.mark.asyncio
    async def test_returns_false_on_connection_error(self, monkeypatch):
        from backend.tools.stripe import StripeTool

        fake = _FakeClient(httpx.ConnectError("nope"))
        monkeypatch.setattr("backend.tools.stripe.httpx.AsyncClient", fake)
        assert await StripeTool().validate_auth(token="sk_live_x") is False

    @pytest.mark.asyncio
    async def test_returns_false_on_missing_token(self, monkeypatch):
        from backend.tools.stripe import StripeTool

        # Wire a fake client so we can detect if it was called when it shouldn't be
        fake = _FakeClient(_FakeResp(200))
        monkeypatch.setattr("backend.tools.stripe.httpx.AsyncClient", fake)
        _FakeClient.last_url = None

        assert await StripeTool().validate_auth(token=None) is False
        assert await StripeTool().validate_auth(token="") is False
        # No HTTP call attempted on the empty-token short-circuit
        assert _FakeClient.last_url is None


# ---------------------------------------------------------------------------
# GitHubTool — same pattern, same bug shape
# ---------------------------------------------------------------------------


class TestGitHubValidateAuth:
    @pytest.mark.asyncio
    async def test_returns_true_on_200(self, monkeypatch):
        from backend.tools.github import GitHubTool

        fake = _FakeClient(_FakeResp(200))
        monkeypatch.setattr("backend.tools.github.httpx.AsyncClient", fake)

        ok = await GitHubTool().validate_auth(token="ghp_realtoken")

        assert ok is True
        assert _FakeClient.last_headers["Authorization"] == "Bearer ghp_realtoken"

    @pytest.mark.asyncio
    async def test_returns_false_on_401(self, monkeypatch):
        from backend.tools.github import GitHubTool

        fake = _FakeClient(_FakeResp(401))
        monkeypatch.setattr("backend.tools.github.httpx.AsyncClient", fake)
        assert await GitHubTool().validate_auth(token="ghp_bad") is False

    @pytest.mark.asyncio
    async def test_returns_false_on_missing_token(self):
        from backend.tools.github import GitHubTool

        # No monkeypatch needed — should short-circuit before the HTTP layer
        assert await GitHubTool().validate_auth(token=None) is False
        assert await GitHubTool().validate_auth(token="") is False


# ---------------------------------------------------------------------------
# Source guard — the literal "sk_test_placeholder" must not return
# ---------------------------------------------------------------------------


class TestSourceGuard:
    def test_no_placeholder_token_in_stripe_module(self):
        import pathlib

        from backend.tools import stripe as stripe_mod

        source = pathlib.Path(stripe_mod.__file__).read_text()
        # The literal must not appear in any code (a docstring may legitimately
        # mention it as the bug being fixed; we only block code occurrences).
        for i, line in enumerate(source.splitlines(), 1):
            stripped = line.strip()
            if not stripped or stripped.startswith(('#', '"""', "'")) or stripped.startswith('*'):
                continue
            assert 'sk_test_placeholder' not in stripped or 'literal' in stripped.lower(), (
                f"line {i} still uses the sk_test_placeholder literal: {line!r}"
            )

    def test_no_empty_bearer_in_github_module(self):
        import pathlib

        from backend.tools import github as github_mod

        source = pathlib.Path(github_mod.__file__).read_text()
        assert 'f"Bearer {\'\'}"' not in source, (
            "GitHub validate_auth used to send `Bearer ` with empty token — see #44"
        )
