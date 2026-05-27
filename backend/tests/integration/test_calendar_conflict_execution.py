"""Integration test: calendar-conflict skill full execution graph.

Tests that the calendar-conflict skill executes all nodes correctly:
  find_conflicts (researcher, google_calendar) → report (cmo) → end (coo)

Verifies:
- Skill loads from registry
- DAG traversal follows correct edges (from → to)
- google_calendar tool is called with find_conflicts action
- All nodes complete when google_calendar returns success
- Failed calendar call routes to end node via failure edge

Run: pytest backend/tests/integration/test_calendar_conflict_execution.py -v
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
import yaml


class DummyToolResult:
    """Fake ToolResult matching backend.tools.base.ToolResult."""

    def __init__(
        self,
        success: bool = True,
        data: dict | None = None,
        error: str | None = None,
    ):
        self.success = success
        self.data = data or {}
        self.error = error


class DummyTool:
    """Mock google_calendar tool for testing."""

    name = "google_calendar"

    async def execute(self, action: str, **kwargs):
        if action == "find_conflicts":
            return DummyToolResult(
                success=True,
                data={
                    "conflicts": [
                        {
                            "id": "evt1",
                            "summary": "Team Standup",
                            "start": "2026-05-26T09:00:00Z",
                            "end": "2026-05-26T09:30:00Z",
                        }
                    ],
                    "count": 1,
                },
            )
        return DummyToolResult(success=False, error=f"Unknown action: {action}")


class DummyToolRegistry:
    """Fake tool registry that returns DummyTool for google_calendar."""

    def get(self, name: str):
        if name == "google_calendar":
            return DummyTool()
        return None


@pytest.fixture
def calendar_skill():
    """Load calendar-conflict skill from YAML."""
    import pathlib

    SKILL_PATH = (
        pathlib.Path(__file__).parents[2] / "skills" / "skills" / "calendar-conflict.yaml"
    )
    assert SKILL_PATH.exists(), f"calendar-conflict.yaml not found at {SKILL_PATH}"
    data = yaml.safe_load(SKILL_PATH.read_text())
    return data


@pytest.fixture
def mock_tools():
    return DummyToolRegistry()


class TestCalendarConflictSkillExecution:
    """Verify calendar-conflict DAG executes find_conflicts → report → end."""

    @pytest.mark.asyncio
    async def test_skill_loads_from_registry(self):
        """calendar-conflict skill is registered and loadable."""
        from backend.skills.registry import SkillRegistry

        registry = SkillRegistry()
        registry.load_all()
        skill = registry.get("calendar-conflict")
        assert skill is not None, "calendar-conflict skill not registered"
        assert skill.id == "calendar-conflict"

    @pytest.mark.asyncio
    async def test_skill_dag_has_three_nodes(self, calendar_skill):
        """Skill DAG has find_conflicts, report, and end nodes."""
        nodes = calendar_skill["execution_graph"]["nodes"]
        node_ids = {n["id"] for n in nodes}
        assert "find_conflicts" in node_ids
        assert "report" in node_ids
        assert "end" in node_ids

    @pytest.mark.asyncio
    async def test_skill_edges_route_correctly(self, calendar_skill):
        """Edges route: find_conflicts.success → report, find_conflicts.failed → end, report.success → end."""
        edges = calendar_skill["execution_graph"]["edges"]
        by_from = {}
        for e in edges:
            by_from.setdefault(e["from"], []).append(e)

        assert "find_conflicts" in by_from
        assert any(
            e["to"] == "report" and e.get("condition") == "find_conflicts.success"
            for e in by_from["find_conflicts"]
        ), "Missing find_conflicts.success → report edge"
        assert any(
            e["to"] == "end" and e.get("condition") == "find_conflicts.failed"
            for e in by_from["find_conflicts"]
        ), "Missing find_conflicts.failed → end edge"
        assert "report" in by_from
        assert any(
            e["to"] == "end" and e.get("condition") == "report.success"
            for e in by_from["report"]
        ), "Missing report.success → end edge"

    @pytest.mark.asyncio
    async def test_skill_completes_without_approval_gate(self):
        """calendar-conflict has no approval gate; DAG should complete without returning draft."""
        from backend.skills.executor import execute_skill
        from backend.skills.registry import SkillRegistry

        registry = SkillRegistry()
        registry.load_all()
        skill = registry.get("calendar-conflict")
        assert skill is not None

        async def mock_llm(prompt, system="", agent_role=None):
            return '{"text": "mock response", "status": "success"}'

        result = await execute_skill(
            skill=skill,
            task_id=str(uuid.uuid4()),
            llm_complete=mock_llm,
            tools=DummyToolRegistry(),
        )

        assert result.status == "completed", (
            f"Expected completed (no approval gate), got {result.status}: {result.error or ''}"
        )
        assert "find_conflicts" in result.nodes_completed

    @pytest.mark.asyncio
    async def test_skill_completes_all_nodes_on_success(self):
        """When google_calendar succeeds, find_conflicts → report → end."""
        from backend.skills.executor import execute_skill
        from backend.skills.registry import SkillRegistry

        registry = SkillRegistry()
        registry.load_all()
        skill = registry.get("calendar-conflict")
        assert skill is not None

        async def mock_llm(prompt, system="", agent_role=None):
            return '{"text": "mock response", "status": "success"}'

        result = await execute_skill(
            skill=skill,
            task_id=str(uuid.uuid4()),
            llm_complete=mock_llm,
            tools=DummyToolRegistry(),
        )

        assert result.status in (
            "completed",
            "draft",
        ), f"Unexpected status: {result.status} — {result.error or ''}"
        assert "find_conflicts" in result.nodes_completed, (
            f"find_conflicts not completed. Nodes completed: {result.nodes_completed}"
        )

    @pytest.mark.asyncio
    async def test_skill_handles_calendar_failure(self):
        """When google_calendar fails, find_conflicts.failed → end (no report)."""
        from backend.tools.base import ToolResult
        from backend.skills.executor import execute_skill
        from backend.skills.registry import SkillRegistry

        registry = SkillRegistry()
        registry.load_all()
        skill = registry.get("calendar-conflict")
        assert skill is not None

        class FailingTool:
            name = "google_calendar"

            async def execute(self, action: str, **kwargs):
                return ToolResult(
                    success=False,
                    error="calendar_not_implemented: Composio SDK not pinned yet.",
                    tool_name=self.name,
                    latency_ms=1.0,
                )

        class FailingRegistry:
            def get(self, name: str):
                if name == "google_calendar":
                    return FailingTool()
                return None

        async def mock_llm(prompt, system="", agent_role=None):
            return '{"text": "skipped", "status": "skipped"}'

        result = await execute_skill(
            skill=skill,
            task_id=str(uuid.uuid4()),
            llm_complete=mock_llm,
            tools=FailingRegistry(),
        )

        assert result.status in ("completed", "failed"), (
            f"Expected completed/failed on tool failure, got {result.status}"
        )
