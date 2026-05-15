"""Smoke test for scripts/soak_test.sh (#58).

The full 7-day run is operational, not in PR scope. What we CAN verify
in CI is that the harness:

  - Is a valid bash script (parses, has the expected env-var contract).
  - Honours DRY_RUN=1 by writing a minimal event log and exiting 0.
  - The event log it writes is consumable by scripts/soak_report.py
    (so the two scripts stay in lockstep).
"""

from __future__ import annotations

import importlib.util
import os
import pathlib
import subprocess
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
HARNESS = REPO_ROOT / "scripts" / "soak_test.sh"
REPORT_SCRIPT = REPO_ROOT / "scripts" / "soak_report.py"


def _load_report_module():
    spec = importlib.util.spec_from_file_location("soak_report", REPORT_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["soak_report"] = module
    spec.loader.exec_module(module)
    return module


def test_harness_script_exists_and_is_executable():
    assert HARNESS.exists(), "scripts/soak_test.sh must ship in PR for #58"
    assert os.access(HARNESS, os.X_OK), "scripts/soak_test.sh must be executable"


def test_harness_script_parses():
    """`bash -n` must accept the script (catches syntax errors fast)."""
    proc = subprocess.run(
        ["bash", "-n", str(HARNESS)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 0, proc.stderr


def test_dry_run_produces_consumable_event_log(tmp_path):
    """DRY_RUN=1 must write a valid JSONL log that soak_report.py can parse."""
    run_dir = tmp_path / "run-test"
    env = {
        **os.environ,
        "DRY_RUN": "1",
        "RUN_ID": "dry-run-test",
        "RUN_DIR": str(run_dir),
        "INTERVAL_SECONDS": "1",
        "DURATION_SECONDS": "1",
    }
    proc = subprocess.run(
        ["bash", str(HARNESS)],
        capture_output=True,
        text=True,
        timeout=15,
        env=env,
    )
    assert proc.returncode == 0, f"stderr={proc.stderr}"
    event_log = run_dir / "events.jsonl"
    assert event_log.exists()

    # Round-trip through the report renderer to prove the contract holds.
    soak_report = _load_report_module()
    events = soak_report.load_events(event_log)
    assert any(e.get("kind") == "harness_start" for e in events)
    assert any(e.get("kind") == "dry_run" for e in events)
    assert any(e.get("kind") == "harness_stop" for e in events)

    # Even a dry-run report must render -- this catches drift between
    # the harness event shape and the report renderer.
    md = soak_report.render_report(events, run_id="dry-run-test")
    assert "# MindForge Phase 4 soak report" in md
    assert "dry-run-test" in md


def test_phase4_exit_doc_exists():
    """The Phase 4 exit-criteria doc lives at docs/phase4-exit.md and
    documents the PASS criteria + a placeholder for the actual run."""
    doc = REPO_ROOT / "docs" / "phase4-exit.md"
    assert doc.exists(), "docs/phase4-exit.md must ship in PR for #58"
    text = doc.read_text()
    assert "Zero process restarts" in text
    assert "Bounded memory growth" in text
    assert "5 distinct skill" in text or "5 skill" in text
    # Placeholder for the maintainer to drop in actual run evidence
    assert "Run evidence" in text
