"""Tests for scripts/soak_report.py (#58, Phase 4 exit criterion).

The soak harness writes JSONL events; soak_report.py turns them into a
markdown report with a PASS/FAIL verdict. The PASS criteria from the
issue body are:

  1. Zero process restarts (no `container_restart` events).
  2. Zero unbounded memory growth (final-vs-initial growth ratio capped).
  3. Draft-first completes on >= 5 distinct skill types
     (>= 5 unique `skill` values across `skill_trigger` events).

Tests pin each of those individually, then a happy-path test exercises
the full report generation.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "soak_report.py"
FIXTURE_DIR = pathlib.Path(__file__).parent / "fixtures"


def _load_module():
    spec = importlib.util.spec_from_file_location("soak_report", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["soak_report"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def soak_report():
    return _load_module()


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


class TestLoadEvents:
    def test_load_pass_fixture(self, soak_report):
        events = soak_report.load_events(FIXTURE_DIR / "soak_events_pass.jsonl")
        assert len(events) == 12
        assert events[0]["kind"] == "harness_start"
        assert events[-1]["kind"] == "harness_stop"

    def test_load_skips_blank_lines(self, soak_report, tmp_path):
        p = tmp_path / "events.jsonl"
        p.write_text(
            '{"ts":"2026-05-15T00:00:00Z","kind":"harness_start","run_id":"x"}\n'
            "\n"
            '{"ts":"2026-05-15T00:00:05Z","kind":"harness_stop","run_id":"x","duration_seconds":5}\n'
        )
        events = soak_report.load_events(p)
        assert len(events) == 2

    def test_load_raises_on_missing_file(self, soak_report, tmp_path):
        with pytest.raises(FileNotFoundError):
            soak_report.load_events(tmp_path / "missing.jsonl")


# ---------------------------------------------------------------------------
# PASS criterion #1: zero process restarts
# ---------------------------------------------------------------------------


class TestRestartCriterion:
    def test_pass_when_no_restarts(self, soak_report):
        events = soak_report.load_events(FIXTURE_DIR / "soak_events_pass.jsonl")
        check = soak_report.check_no_restarts(events)
        assert check.passed is True
        assert check.observed == 0

    def test_fail_when_restart_present(self, soak_report):
        events = soak_report.load_events(
            FIXTURE_DIR / "soak_events_fail_restart.jsonl"
        )
        check = soak_report.check_no_restarts(events)
        assert check.passed is False
        assert check.observed == 1


# ---------------------------------------------------------------------------
# PASS criterion #2: bounded memory growth
# ---------------------------------------------------------------------------


class TestMemoryCriterion:
    def test_pass_when_memory_stable(self, soak_report):
        events = soak_report.load_events(FIXTURE_DIR / "soak_events_pass.jsonl")
        check = soak_report.check_bounded_memory(events)
        assert check.passed is True
        assert check.growth_ratio is not None
        assert check.growth_ratio < 1.5

    def test_fail_when_memory_grows_unbounded(self, soak_report):
        events = soak_report.load_events(
            FIXTURE_DIR / "soak_events_fail_memory.jsonl"
        )
        check = soak_report.check_bounded_memory(events)
        # 100 -> 1500 = 15x growth, well above the 1.5x ceiling
        assert check.passed is False
        assert check.growth_ratio is not None
        assert check.growth_ratio > 5.0

    def test_undetermined_when_no_stats(self, soak_report, tmp_path):
        p = tmp_path / "events.jsonl"
        p.write_text(
            '{"ts":"2026-05-15T00:00:00Z","kind":"harness_start","run_id":"x"}\n'
        )
        events = soak_report.load_events(p)
        check = soak_report.check_bounded_memory(events)
        # Without container_stats events we cannot judge, so PASS the
        # check (operator-set ceiling, not a positive failure signal).
        assert check.passed is True
        assert check.growth_ratio is None


# ---------------------------------------------------------------------------
# PASS criterion #3: >= 5 distinct skill types
# ---------------------------------------------------------------------------


class TestSkillDiversityCriterion:
    def test_pass_when_five_distinct_skills(self, soak_report):
        events = soak_report.load_events(FIXTURE_DIR / "soak_events_pass.jsonl")
        check = soak_report.check_skill_diversity(events)
        assert check.passed is True
        assert check.distinct_skills >= 5

    def test_fail_when_only_one_skill_repeated(self, soak_report):
        events = soak_report.load_events(
            FIXTURE_DIR / "soak_events_fail_skill_diversity.jsonl"
        )
        check = soak_report.check_skill_diversity(events)
        assert check.passed is False
        assert check.distinct_skills == 1


# ---------------------------------------------------------------------------
# Aggregate report
# ---------------------------------------------------------------------------


class TestRenderReport:
    def test_pass_report_contains_verdict_and_all_checks(self, soak_report):
        events = soak_report.load_events(FIXTURE_DIR / "soak_events_pass.jsonl")
        md = soak_report.render_report(events, run_id="test-run-1")

        assert "# MindForge Phase 4 soak report" in md
        assert "**Verdict:** ✅ PASS" in md
        assert "Zero process restarts" in md
        assert "Bounded memory growth" in md
        assert "Skill diversity" in md
        # Operator-visible degradation when /metrics is missing
        assert "metrics_endpoint_not_implemented" in md

    def test_fail_report_lists_each_failing_check(self, soak_report):
        events = soak_report.load_events(
            FIXTURE_DIR / "soak_events_fail_restart.jsonl"
        )
        md = soak_report.render_report(events, run_id="test-run-2")
        assert "**Verdict:** ❌ FAIL" in md
        assert "Zero process restarts" in md
        # The failing line must be obvious on a quick scan
        assert "❌" in md
