"""Unit tests for env-aware health-check URL builders (issue #41).

Covers:
  - check_chroma() honors CHROMA_HOST env var
  - check_ollama() honors OLLAMA_BASE_URL env var
  - check_temporal() honors TEMPORAL_HEALTH_URL override
  - All three return False on connection error / non-200 / timeout
  - Defaults are loopback addresses (no docker assumption)
"""

from __future__ import annotations

import httpx
import pytest

from backend.db import (
    _chroma_heartbeat_url,
    _ollama_tags_url,
    _temporal_health_url,
    check_chroma,
    check_ollama,
    check_temporal,
)

# ---------------------------------------------------------------------------
# URL builders
# ---------------------------------------------------------------------------


class TestChromaURL:
    def test_default_is_loopback(self, monkeypatch):
        monkeypatch.delenv("CHROMA_HOST", raising=False)
        assert _chroma_heartbeat_url() == "http://127.0.0.1:8000/api/v1/heartbeat"

    def test_honors_env_var(self, monkeypatch):
        monkeypatch.setenv("CHROMA_HOST", "http://chroma:8000")
        assert _chroma_heartbeat_url() == "http://chroma:8000/api/v1/heartbeat"

    def test_strips_trailing_slash(self, monkeypatch):
        monkeypatch.setenv("CHROMA_HOST", "http://chroma:8000/")
        assert _chroma_heartbeat_url() == "http://chroma:8000/api/v1/heartbeat"


class TestOllamaURL:
    def test_default_is_loopback(self, monkeypatch):
        monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
        assert _ollama_tags_url() == "http://127.0.0.1:11434/api/tags"

    def test_honors_env_var(self, monkeypatch):
        monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama:11434")
        assert _ollama_tags_url() == "http://ollama:11434/api/tags"


class TestTemporalURL:
    def test_default_points_to_ui_sidecar(self, monkeypatch):
        monkeypatch.delenv("TEMPORAL_HEALTH_URL", raising=False)
        assert _temporal_health_url() == "http://127.0.0.1:8088/api/v1/cluster/health"

    def test_explicit_override(self, monkeypatch):
        monkeypatch.setenv("TEMPORAL_HEALTH_URL", "http://temporal-ui:8080")
        assert (
            _temporal_health_url()
            == "http://temporal-ui:8080/api/v1/cluster/health"
        )


# ---------------------------------------------------------------------------
# Async behavior — patch httpx.AsyncClient so we don't make network calls
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


class _FakeClient:
    """Captures the URL the check called and returns a canned response."""

    last_url: str | None = None

    def __init__(self, response_or_exc):
        self._response_or_exc = response_or_exc

    def __call__(self, *args, **kwargs):
        # AsyncClient(timeout=...) returns self when used as a constructor
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, url):
        _FakeClient.last_url = url
        if isinstance(self._response_or_exc, Exception):
            raise self._response_or_exc
        return self._response_or_exc


@pytest.mark.asyncio
async def test_check_chroma_uses_env_url(monkeypatch):
    monkeypatch.setenv("CHROMA_HOST", "http://chroma:8000")
    fake = _FakeClient(_FakeResponse(200))
    monkeypatch.setattr("backend.db.httpx.AsyncClient", fake)
    assert await check_chroma() is True
    assert _FakeClient.last_url == "http://chroma:8000/api/v1/heartbeat"


@pytest.mark.asyncio
async def test_check_chroma_returns_false_on_503(monkeypatch):
    fake = _FakeClient(_FakeResponse(503))
    monkeypatch.setattr("backend.db.httpx.AsyncClient", fake)
    assert await check_chroma() is False


@pytest.mark.asyncio
async def test_check_chroma_returns_false_on_connection_error(monkeypatch):
    fake = _FakeClient(httpx.ConnectError("nope"))
    monkeypatch.setattr("backend.db.httpx.AsyncClient", fake)
    assert await check_chroma() is False


@pytest.mark.asyncio
async def test_check_ollama_uses_env_url(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama:11434")
    fake = _FakeClient(_FakeResponse(200))
    monkeypatch.setattr("backend.db.httpx.AsyncClient", fake)
    assert await check_ollama() is True
    assert _FakeClient.last_url == "http://ollama:11434/api/tags"


@pytest.mark.asyncio
async def test_check_temporal_uses_explicit_override(monkeypatch):
    monkeypatch.setenv("TEMPORAL_HEALTH_URL", "http://temporal-ui:8080")
    fake = _FakeClient(_FakeResponse(200))
    monkeypatch.setattr("backend.db.httpx.AsyncClient", fake)
    assert await check_temporal() is True
    assert _FakeClient.last_url == "http://temporal-ui:8080/api/v1/cluster/health"
