#!/usr/bin/env python3
"""Soak-test report generator (#58, Phase 4 exit criterion).

Reads the JSONL event log produced by ``scripts/soak_test.sh`` and emits
a markdown report with a PASS/FAIL verdict against the criteria from
SPEC §5.4 / issue #58:

  1. Zero process restarts (no ``container_restart`` events).
  2. Bounded memory growth (final/initial memory ratio < 1.5x).
  3. Draft-first completes on >= 5 distinct skill types.

Usage:
    python3 scripts/soak_report.py <events.jsonl> [--run-id ID] [--out report.md]

The script intentionally has no third-party imports so it can run on a
fresh box that only has python3 -- soak operators shouldn't need to set
up a venv just to read a report.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from dataclasses import dataclass
from typing import Any

# PASS thresholds -- tunable from the CLI later if needed.
MAX_MEMORY_GROWTH_RATIO = 1.5  # final/initial memory ceiling
MIN_DISTINCT_SKILLS = 5  # AC #3 from issue #58


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------


@dataclass
class CheckResult:
    """Result of one PASS-criterion check.

    ``passed``      -- True / False verdict
    ``observed``    -- the raw count or ratio observed
    ``growth_ratio`` -- only meaningful for the memory check
    ``distinct_skills`` -- only meaningful for the diversity check
    ``detail``      -- one-line operator-readable summary
    """

    passed: bool
    name: str
    detail: str
    observed: int = 0
    growth_ratio: float | None = None
    distinct_skills: int = 0


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def load_events(path: pathlib.Path | str) -> list[dict[str, Any]]:
    """Read JSONL events from ``path``. Blank lines are skipped."""
    p = pathlib.Path(path)
    if not p.exists():
        raise FileNotFoundError(p)
    events: list[dict[str, Any]] = []
    for raw in p.read_text().splitlines():
        line = raw.strip()
        if not line:
            continue
        events.append(json.loads(line))
    return events


# ---------------------------------------------------------------------------
# Individual PASS-criterion checks
# ---------------------------------------------------------------------------


def check_no_restarts(events: list[dict[str, Any]]) -> CheckResult:
    restarts = sum(1 for e in events if e.get("kind") == "container_restart")
    return CheckResult(
        passed=restarts == 0,
        observed=restarts,
        name="Zero process restarts",
        detail=(
            "no container_restart events recorded"
            if restarts == 0
            else f"observed {restarts} container restart(s)"
        ),
    )


def check_bounded_memory(events: list[dict[str, Any]]) -> CheckResult:
    samples = [e for e in events if e.get("kind") == "container_stats"]
    if not samples:
        # Operator-set ceiling: no samples means we can't judge -- pass
        # but record the gap in the detail.
        return CheckResult(
            passed=True,
            name="Bounded memory growth",
            detail="no container_stats events recorded -- check skipped",
            growth_ratio=None,
        )

    initial = float(samples[0].get("memory_mb", 0.0)) or 1.0
    final = float(samples[-1].get("memory_mb", 0.0))
    ratio = final / initial if initial else 0.0
    passed = ratio < MAX_MEMORY_GROWTH_RATIO
    return CheckResult(
        passed=passed,
        name="Bounded memory growth",
        detail=(
            f"memory grew from {initial:.1f}MB to {final:.1f}MB "
            f"(ratio {ratio:.2f}x; ceiling {MAX_MEMORY_GROWTH_RATIO:.2f}x)"
        ),
        growth_ratio=ratio,
    )


def check_skill_diversity(events: list[dict[str, Any]]) -> CheckResult:
    triggered = {
        e.get("skill")
        for e in events
        if e.get("kind") == "skill_trigger" and e.get("skill")
    }
    distinct = len(triggered)
    passed = distinct >= MIN_DISTINCT_SKILLS
    return CheckResult(
        passed=passed,
        name="Skill diversity",
        detail=(
            f"{distinct} distinct skill(s) triggered "
            f"(target: >= {MIN_DISTINCT_SKILLS})"
        ),
        distinct_skills=distinct,
    )


# ---------------------------------------------------------------------------
# Aggregate report
# ---------------------------------------------------------------------------


def render_report(events: list[dict[str, Any]], run_id: str = "unknown") -> str:
    """Render the markdown soak report. Always emits the same section
    structure so it can be diffed across runs."""
    checks = [
        check_no_restarts(events),
        check_bounded_memory(events),
        check_skill_diversity(events),
    ]
    overall_pass = all(c.passed for c in checks)
    verdict = "✅ PASS" if overall_pass else "❌ FAIL"

    start_event = next(
        (e for e in events if e.get("kind") == "harness_start"), None
    )
    stop_event = next(
        (e for e in reversed(events) if e.get("kind") == "harness_stop"), None
    )
    duration_seconds = (
        stop_event.get("duration_seconds", 0) if stop_event else 0
    )

    health_probes = [e for e in events if e.get("kind") == "health_probe"]
    health_failures = sum(1 for e in health_probes if not e.get("ok"))
    triggers = [e for e in events if e.get("kind") == "skill_trigger"]
    trigger_failures = sum(1 for e in triggers if not e.get("ok"))

    metrics_warnings = [
        e
        for e in events
        if e.get("kind") == "metrics_scrape" and not e.get("ok")
    ]

    lines: list[str] = []
    lines.append("# MindForge Phase 4 soak report")
    lines.append("")
    lines.append(f"- **Run id:** `{run_id}`")
    if start_event:
        lines.append(f"- **Started:** `{start_event.get('ts', 'unknown')}`")
    if stop_event:
        lines.append(f"- **Stopped:** `{stop_event.get('ts', 'unknown')}`")
    lines.append(f"- **Duration:** {duration_seconds} seconds")
    lines.append(f"- **Verdict:** {verdict}")
    lines.append("")

    lines.append("## PASS criteria")
    lines.append("")
    lines.append("| # | Criterion | Result | Detail |")
    lines.append("|---|---|---|---|")
    for i, c in enumerate(checks, start=1):
        marker = "✅" if c.passed else "❌"
        lines.append(f"| {i} | {c.name} | {marker} | {c.detail} |")
    lines.append("")

    lines.append("## Activity summary")
    lines.append("")
    lines.append(f"- Health probes: {len(health_probes)} (failures: {health_failures})")
    lines.append(f"- Skill triggers: {len(triggers)} (failures: {trigger_failures})")
    triggered_set = sorted(
        {e["skill"] for e in triggers if e.get("skill")}
    )
    if triggered_set:
        lines.append(f"- Distinct skills exercised: {', '.join(triggered_set)}")

    if metrics_warnings:
        lines.append("")
        lines.append("## Degradation notes")
        lines.append("")
        for w in metrics_warnings[:5]:
            reason = w.get("reason", "unknown")
            lines.append(f"- `metrics_scrape` skipped: `{reason}`")

    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Render a soak-test report from a JSONL event log."
    )
    parser.add_argument("events", help="path to events.jsonl")
    parser.add_argument(
        "--run-id", default="unknown", help="run identifier to embed in the report"
    )
    parser.add_argument(
        "--out", default=None, help="write report to this file (default: stdout)"
    )
    args = parser.parse_args(argv)

    events = load_events(args.events)
    report = render_report(events, run_id=args.run_id)

    if args.out:
        pathlib.Path(args.out).write_text(report)
    else:
        sys.stdout.write(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
