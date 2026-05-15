"""Prometheus metrics surface (#52, SPEC §5.5).

This module is the **single source of truth** for every metric the
backend exposes. Call sites (LLM router, supervisor, skill registry,
WS manager, rate limiter) call the helpers here -- they never construct
``Counter`` / ``Histogram`` / ``Gauge`` themselves. That keeps label
cardinality reviewable in one place.

Reload-safe: tests reload this module repeatedly. The metrics live on a
module-private CollectorRegistry so re-import never trips
prometheus_client's "Duplicated timeseries" guard against the global
default registry; ``get_metrics_text()`` exposes the same registry.

Helpers must NEVER raise. A metrics outage must not fail an LLM call
or break a request -- emit on best-effort, swallow on error.
"""

from __future__ import annotations

import logging
from typing import Final

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

logger = logging.getLogger(__name__)

# Public constant -- used by the FastAPI route to set the right
# Content-Type. Mirrors the module-level constant from prometheus_client.
METRICS_CONTENT_TYPE: Final[str] = CONTENT_TYPE_LATEST

# Buckets sized for the 95/99 percentile spread we expect: local Ollama
# is sub-second; cloud_fast is 1-3s; cloud_heavy is 5-15s; runaway calls
# are caught by the budget guard before they hit 30s.
_LLM_LATENCY_BUCKETS: Final[tuple[float, ...]] = (
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.0,
    5.0,
    10.0,
    30.0,
)

# Module-private registry -- isolates us from the prometheus_client
# default registry so importing this module twice (test reload, multi-
# worker dev) doesn't crash the process.
REGISTRY: Final[CollectorRegistry] = CollectorRegistry()


# ---------------------------------------------------------------------------
# Metric instruments
# ---------------------------------------------------------------------------


_llm_calls_total = Counter(
    "llm_calls_total",
    "Total LLM completions, labelled by routing tier, model, and outcome.",
    labelnames=("tier", "model", "outcome"),
    registry=REGISTRY,
)

_llm_call_duration_seconds = Histogram(
    "llm_call_duration_seconds",
    "LLM completion wall-clock time, labelled by routing tier and model.",
    labelnames=("tier", "model"),
    buckets=_LLM_LATENCY_BUCKETS,
    registry=REGISTRY,
)

_agent_invocations_total = Counter(
    "agent_invocations_total",
    "Number of times each agent role was invoked by the supervisor.",
    labelnames=("role",),
    registry=REGISTRY,
)

_skill_runs_total = Counter(
    "skill_runs_total",
    "Skill executions, labelled by skill_id and outcome (success/failed/etc).",
    labelnames=("skill", "outcome"),
    registry=REGISTRY,
)

_ws_connections_active = Gauge(
    "ws_connections_active",
    "Currently-open dashboard WebSocket connections.",
    registry=REGISTRY,
)

_integration_rate_limit_waits_total = Counter(
    "integration_rate_limit_waits_total",
    "Times an integration call had to wait on its concurrency semaphore.",
    labelnames=("integration",),
    registry=REGISTRY,
)


# ---------------------------------------------------------------------------
# Helpers -- keep these tiny + best-effort. Call sites should be a single
# line each.
# ---------------------------------------------------------------------------


def record_llm_call(
    *, tier: str, model: str, outcome: str, duration_seconds: float
) -> None:
    """Record one completed LLM call.

    ``outcome`` should be one of: ``success`` | ``failure`` | ``budget``
    | ``timeout``. Unknown values are accepted (label cardinality is the
    caller's responsibility).
    """
    try:
        _llm_calls_total.labels(tier=tier, model=model, outcome=outcome).inc()
        _llm_call_duration_seconds.labels(tier=tier, model=model).observe(
            duration_seconds
        )
    except Exception:  # pragma: no cover - metrics must never raise
        logger.exception("metrics.record_llm_call failed")


def inc_agent_invocation(role: str) -> None:
    try:
        _agent_invocations_total.labels(role=role).inc()
    except Exception:  # pragma: no cover
        logger.exception("metrics.inc_agent_invocation failed")


def inc_skill_run(skill: str, outcome: str) -> None:
    try:
        _skill_runs_total.labels(skill=skill, outcome=outcome).inc()
    except Exception:  # pragma: no cover
        logger.exception("metrics.inc_skill_run failed")


def inc_ws_connection() -> None:
    try:
        _ws_connections_active.inc()
    except Exception:  # pragma: no cover
        logger.exception("metrics.inc_ws_connection failed")


def dec_ws_connection() -> None:
    try:
        _ws_connections_active.dec()
    except Exception:  # pragma: no cover
        logger.exception("metrics.dec_ws_connection failed")


def inc_rate_limit_wait(integration: str) -> None:
    try:
        _integration_rate_limit_waits_total.labels(integration=integration).inc()
    except Exception:  # pragma: no cover
        logger.exception("metrics.inc_rate_limit_wait failed")


# ---------------------------------------------------------------------------
# Exposition
# ---------------------------------------------------------------------------


def get_metrics_text() -> str:
    """Render the registry in Prometheus text exposition format.

    Returned as a UTF-8 string for FastAPI's ``Response(content=...)``.
    """
    return generate_latest(REGISTRY).decode("utf-8")
