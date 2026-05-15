"""Validate the calendar-conflict skill YAML (#57 part C).

The skill must:
  - Parse with yaml.safe_load (AGENTS.md Rule 3).
  - Pass validate_skill_graph (single-source validator from #45/#64).
  - Reference google_calendar (find_conflicts) so the registered tool
    resolves at execution time.
"""

from __future__ import annotations

import pathlib

import yaml

from backend.skills.validator import validate_skill_graph

SKILL_PATH = pathlib.Path("backend/skills/skills/calendar-conflict.yaml")


def test_skill_yaml_parses_with_safe_load():
    assert SKILL_PATH.exists(), "calendar-conflict skill must ship in PR C"
    data = yaml.safe_load(SKILL_PATH.read_text())
    assert isinstance(data, dict)
    assert data["name"] == "calendar-conflict"


def test_skill_graph_passes_validator():
    data = yaml.safe_load(SKILL_PATH.read_text())
    errors = validate_skill_graph(data)
    assert errors == [], f"validator returned: {errors}"


def test_skill_uses_google_calendar_tool():
    data = yaml.safe_load(SKILL_PATH.read_text())
    nodes = data["execution_graph"]["nodes"]
    assert any(
        "google_calendar" in (node.get("tools") or [])
        for node in nodes
    ), "skill must call google_calendar tool"


def test_skill_uses_find_conflicts_action():
    """The conflict-detection node must call the find_conflicts action so
    the GoogleCalendarTool dispatcher is exercised end-to-end."""
    raw = SKILL_PATH.read_text()
    assert "find_conflicts" in raw
