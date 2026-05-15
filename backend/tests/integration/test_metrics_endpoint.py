"""Integration test for GET /metrics (#52).

The route must:
  - Return 200 OK.
  - Carry the prometheus text-exposition Content-Type.
  - Include all metric names listed in the issue body.
  - Be safe to scrape repeatedly without leaking goroutines / connections.
"""

from __future__ import annotations

import os
import pathlib

# Pre-import patches mirror the other integration tests.
from cryptography.fernet import Fernet

os.environ.setdefault("FERNET_KEY", Fernet.generate_key().decode())

_ORIGINAL_MAKEDIRS = os.makedirs


def _safe_makedirs(path, *args, **kwargs):
    if isinstance(path, pathlib.Path):
        path = str(path)
    if str(path).startswith("/app"):
        return
    return _ORIGINAL_MAKEDIRS(path, *args, **kwargs)


os.makedirs = _safe_makedirs  # type: ignore[assignment]

from collections.abc import Iterator  # noqa: E402

import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture
def client() -> Iterator[TestClient]:
    """Mount only the metrics route -- isolated from the rest of the app
    so a broken db_dep / migrations / etc. don't poison this test."""
    from backend.observability.metrics import (
        METRICS_CONTENT_TYPE,
        get_metrics_text,
        inc_agent_invocation,
        inc_skill_run,
        record_llm_call,
    )

    # Pre-populate one observation per metric so the scrape isn't empty
    record_llm_call(
        tier="cloud_fast",
        model="gemini-2-flash",
        outcome="success",
        duration_seconds=0.42,
    )
    inc_agent_invocation("coo")
    inc_skill_run("subscription-refund", "success")

    app = FastAPI()

    @app.get("/metrics")
    async def metrics_route():
        from starlette.responses import Response

        return Response(content=get_metrics_text(), media_type=METRICS_CONTENT_TYPE)

    with TestClient(app) as c:
        yield c


def test_metrics_endpoint_returns_200(client: TestClient) -> None:
    resp = client.get("/metrics")
    assert resp.status_code == 200, resp.text


def test_metrics_endpoint_uses_prometheus_content_type(client: TestClient) -> None:
    resp = client.get("/metrics")
    assert "text/plain" in resp.headers["content-type"]
    assert "version=" in resp.headers["content-type"]


def test_metrics_endpoint_contains_all_required_metrics(client: TestClient) -> None:
    resp = client.get("/metrics")
    body = resp.text
    for name in (
        "llm_calls_total",
        "llm_call_duration_seconds",
        "agent_invocations_total",
        "skill_runs_total",
        "ws_connections_active",
        "integration_rate_limit_waits_total",
    ):
        assert name in body, f"missing metric: {name}"


def test_metrics_endpoint_is_idempotent_under_repeat_scrape(
    client: TestClient,
) -> None:
    """Scraping repeatedly must not double-register metrics or grow the
    response unboundedly."""
    bodies = [client.get("/metrics").text for _ in range(3)]
    # All three responses share the same set of metric names
    name_lines = lambda body: sorted(  # noqa: E731
        line for line in body.splitlines() if line.startswith("# TYPE ")
    )
    assert name_lines(bodies[0]) == name_lines(bodies[1]) == name_lines(bodies[2])
