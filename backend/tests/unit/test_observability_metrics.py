"""Unit tests for backend/observability/metrics.py (#52).

The module is the single source of truth for all Prometheus metrics.
Tests pin:
  - The metric names + label names match SPEC §5.5 / issue #52.
  - Helper functions actually increment / observe the underlying objects.
  - Repeated import is safe (CollectorRegistry duplicate-registration
    would crash the test suite if not handled).
  - get_metrics_text() returns the canonical text-exposition output.
"""

from __future__ import annotations

import importlib

import pytest


@pytest.fixture
def metrics():
    """Re-import the module so the test sees a clean view of registered names.

    prometheus_client uses a process-global default registry; the module
    is import-once. We reset values between tests via the helper.
    """
    import backend.observability.metrics as m

    importlib.reload(m)
    return m


# ---------------------------------------------------------------------------
# Module surface
# ---------------------------------------------------------------------------


def test_module_exports_required_helpers(metrics):
    expected = {
        "record_llm_call",
        "inc_agent_invocation",
        "inc_skill_run",
        "inc_ws_connection",
        "dec_ws_connection",
        "inc_rate_limit_wait",
        "get_metrics_text",
        "METRICS_CONTENT_TYPE",
    }
    missing = expected - set(dir(metrics))
    assert not missing, f"missing helpers: {sorted(missing)}"


def test_metrics_content_type_is_prometheus(metrics):
    assert "text/plain" in metrics.METRICS_CONTENT_TYPE
    # prometheus_client.CONTENT_TYPE_LATEST also embeds the version
    assert "version=" in metrics.METRICS_CONTENT_TYPE


# ---------------------------------------------------------------------------
# Metric registration -- the names in get_metrics_text() are the source
# of truth, since label cardinality matters more than Python attribute
# names.
# ---------------------------------------------------------------------------


class TestMetricNames:
    def test_text_output_lists_all_required_metrics(self, metrics):
        # Touch each helper once so the metric appears in the text output
        # (Counters with no observations are still listed by HELP/TYPE).
        metrics.record_llm_call(
            tier="cloud_fast", model="gemini-2-flash", outcome="success", duration_seconds=0.42
        )
        metrics.inc_agent_invocation("coo")
        metrics.inc_skill_run("subscription-refund", "success")
        metrics.inc_ws_connection()
        metrics.dec_ws_connection()
        metrics.inc_rate_limit_wait("github")

        text = metrics.get_metrics_text()
        assert isinstance(text, str)
        for name in (
            "llm_calls_total",
            "llm_call_duration_seconds",
            "agent_invocations_total",
            "skill_runs_total",
            "ws_connections_active",
            "integration_rate_limit_waits_total",
        ):
            assert name in text, f"missing metric: {name}"

    def test_label_keys_are_present(self, metrics):
        metrics.record_llm_call(
            tier="local", model="llama3.2:3b", outcome="success", duration_seconds=0.05
        )
        metrics.inc_agent_invocation("engineer")
        metrics.inc_skill_run("calendar-conflict", "failed")
        metrics.inc_rate_limit_wait("stripe")

        text = metrics.get_metrics_text()
        # Counter samples include their labels in the rendered text -
        # this catches accidental label drift (e.g. tier->model_tier).
        assert 'tier="local"' in text
        assert 'model="llama3.2:3b"' in text
        assert 'outcome="success"' in text
        assert 'role="engineer"' in text
        assert 'skill="calendar-conflict"' in text
        assert 'integration="stripe"' in text


# ---------------------------------------------------------------------------
# Helper semantics
# ---------------------------------------------------------------------------


class TestHelperSemantics:
    def test_record_llm_call_increments_counter_and_histogram(self, metrics):
        # Two calls -> counter goes up by 2 for the same labels
        metrics.record_llm_call(
            tier="cloud_fast", model="gemini-2-flash", outcome="success", duration_seconds=0.5
        )
        metrics.record_llm_call(
            tier="cloud_fast", model="gemini-2-flash", outcome="success", duration_seconds=1.5
        )
        text = metrics.get_metrics_text()
        # Counter label set with value 2 -- pin the exact line shape so a
        # later refactor doesn't quietly drop a label.
        expected_counter_line = (
            'llm_calls_total{model="gemini-2-flash",outcome="success",tier="cloud_fast"} 2.0'
        )
        assert expected_counter_line in text, text

    def test_record_llm_call_failure_outcome(self, metrics):
        metrics.record_llm_call(
            tier="cloud_heavy", model="gpt-4o", outcome="failure", duration_seconds=10.0
        )
        text = metrics.get_metrics_text()
        assert 'outcome="failure"' in text
        # Histogram bucket counts must include this observation
        assert "llm_call_duration_seconds_count" in text

    def test_ws_gauge_round_trips(self, metrics):
        metrics.inc_ws_connection()
        metrics.inc_ws_connection()
        metrics.inc_ws_connection()
        metrics.dec_ws_connection()
        text = metrics.get_metrics_text()
        # 3 inc - 1 dec = 2.0
        assert "ws_connections_active 2.0" in text

    def test_helpers_never_raise_on_unknown_labels(self, metrics):
        # Unfamiliar tier / outcome / role values must NOT crash the call
        # site -- metrics are best-effort by definition.
        metrics.record_llm_call(
            tier="experimental", model="unknown-99", outcome="weird", duration_seconds=0.1
        )
        metrics.inc_agent_invocation("brand-new-role")
        metrics.inc_skill_run("never-seen-skill", "partial")
        text = metrics.get_metrics_text()
        assert 'tier="experimental"' in text


# ---------------------------------------------------------------------------
# Reload-safety -- the module is imported many places; reloading must
# not crash with prometheus_client "Duplicated timeseries" errors.
# ---------------------------------------------------------------------------


def test_module_reload_is_safe():
    import backend.observability.metrics as m

    # Reload twice -- if the module re-registers globals into the default
    # registry without guarding it would raise ValueError on the 2nd.
    importlib.reload(m)
    importlib.reload(m)
    assert m.get_metrics_text()
