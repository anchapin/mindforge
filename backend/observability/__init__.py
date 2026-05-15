"""Observability surface -- metrics, traces, structured logging.

Currently exposes a single Prometheus metrics module (#52). The
opentelemetry hooks live elsewhere and may be folded in later.
"""

from .metrics import (
    METRICS_CONTENT_TYPE,
    dec_ws_connection,
    get_metrics_text,
    inc_agent_invocation,
    inc_rate_limit_wait,
    inc_skill_run,
    inc_ws_connection,
    record_llm_call,
)

__all__ = [
    "METRICS_CONTENT_TYPE",
    "dec_ws_connection",
    "get_metrics_text",
    "inc_agent_invocation",
    "inc_rate_limit_wait",
    "inc_skill_run",
    "inc_ws_connection",
    "record_llm_call",
]
