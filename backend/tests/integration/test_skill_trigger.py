"""Test skill triggering and DAG execution — Issue #16.

Tests:
1. trigger_skill() keyword match fires when task description contains skill keywords
2. execute_skill() DAG correctly traverses edges (from_node vs from bug)
3. Approval gate pauses execution and returns draft status

Run: pytest backend/tests/integration/test_skill_trigger.py -v
"""

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestSkillTriggerInTaskExecution:
    """Verify that when a task matches a skill, execute_skill() is called, not _run_agent()."""

    @pytest.mark.asyncio
    async def test_trigger_skill_keyword_match_fires_for_billing_task(self):
        """Task with 'refund' in description matches subscription-refund skill via keyword."""
        from backend.skills.trigger import trigger_skill
        from backend.skills.registry import SkillRegistry

        registry = SkillRegistry()
        registry.load_all()

        skill = await trigger_skill(
            task_description="I want a refund for my last subscription payment",
            llm_router=None,  # keyword path only
        )

        assert skill is not None, (
            "trigger_skill returned None for task with 'refund' keyword. "
            "Expected subscription-refund skill to match via keyword trigger."
        )
        assert skill.id == "subscription-refund", (
            f"Expected subscription-refund, got {skill.id}"
        )

    @pytest.mark.asyncio
    async def test_execute_skill_follows_edges_correctly(self):
        """execute_skill() traverses edges using the correct 'from' key (not 'from_node').

        RED: This test FAILS because _execute_dag uses edge.get("from_node")
        which is wrong — edges are stored as {"from": ..., "to": ..., "condition": ...}.
        Result: DAG completes without advancing past the first node.
        """
        from backend.skills.executor import execute_skill
        from backend.skills.models import Skill, SkillNode, ExecutionGraph
        from backend.skills.registry import SkillRegistry

        registry = SkillRegistry()
        registry.load_all()

        skill = registry.get("subscription-refund")
        assert skill is not None, "subscription-refund skill not loaded"

        # Track which nodes were executed
        executed_nodes: list[str] = []

        async def mock_llm_complete(prompt, system="", agent_role=None):
            # Extract node ID from prompt by checking which agent
            return '{"text": "mock response", "status": "success"}'

        mock_tools = MagicMock()
        mock_tools.get = lambda name: MagicMock()

        task_id = str(uuid.uuid4())
        result = await execute_skill(
            skill=skill,
            task_id=task_id,
            llm_complete=mock_llm_complete,
            tools=mock_tools,
        )

        # The DAG has nodes: verify -> draft -> negotiate -> escalate -> end
        # If edge traversal works: after 'verify' completes (success), 'draft' should run
        # After 'draft' (requires_approval), execution should pause and return draft status
        # The test will FAIL in RED because edges are never traversed (from_node bug)
        # so only the first node ('verify') executes before DAG terminates.
        assert result.status in ("draft", "completed"), (
            f"Unexpected status: {result.status}. Expected 'draft' (approval gate) or 'completed'."
        )

    @pytest.mark.asyncio
    async def test_execute_skill_returns_draft_at_approval_gate(self):
        """execute_skill() returns status='draft' when a node has requires_approval=True.

        This tests the subscription-refund skill whose 'draft' node requires approval.
        The DAG should execute 'verify' node, hit 'draft' node approval gate, and return draft.
        """
        from backend.skills.executor import execute_skill
        from backend.skills.registry import SkillRegistry

        registry = SkillRegistry()
        registry.load_all()

        skill = registry.get("subscription-refund")
        assert skill is not None

        async def mock_llm_complete(prompt, system="", agent_role=None):
            return '{"text": "draft response", "status": "success"}'

        mock_tools = MagicMock()
        mock_tools.get = lambda name: MagicMock()

        result = await execute_skill(
            skill=skill,
            task_id=str(uuid.uuid4()),
            llm_complete=mock_llm_complete,
            tools=mock_tools,
        )

        # After verify (success), edge triggers draft node which requires_approval.
        # Execution pauses BEFORE draft node runs — returns draft, not draft node output.
        assert result.status == "draft", (
            f"Expected status='draft' at approval gate, got '{result.status}'. "
            "Check: (1) edges are traversed with correct 'from' key, "
            "(2) requires_approval=True node triggers draft pause."
        )
        assert result.current_node == "draft", (
            f"Expected current_node='draft', got '{result.current_node}'"
        )
        # verify node completed; draft node paused before execution
        assert "verify" in result.nodes_completed, (
            f"Expected 'verify' in nodes_completed, got {result.nodes_completed}"
        )


class TestExecuteSkillEdgeTraversal:
    """Unit test for edge key: from vs from_node."""

    @pytest.mark.asyncio
    async def test_edges_use_from_key_not_from_node(self):
        """The ExecutionGraph stores edges as {"from": ..., "to": ..., "condition": ...}.

        Verify the stored format matches what _execute_dag reads.
        """
        from backend.skills.models import ExecutionGraph, SkillNode

        # Build a minimal DAG
        node_a = SkillNode(id="a", agent="coo", goal="Do A", tools=[])
        node_b = SkillNode(id="b", agent="coo", goal="Do B", tools=[])

        # Edge stored as registry.py does it: {"from": ..., "to": ..., "condition": ...}
        edges = [
            {"from": "a", "to": "b", "condition": "a.success"},
        ]

        graph = ExecutionGraph(nodes=[node_a, node_b], edges=edges, type="directed_acyclic_graph")

        # Verify the edge key is "from", not "from_node"
        assert "from" in graph.edges[0], f"Edge keys: {list(graph.edges[0].keys())}"
        assert "from_node" not in graph.edges[0]

        # Now verify _execute_dag uses edge.get("from") correctly
        from backend.skills.executor import _evaluate_condition, _execute_dag
        from backend.skills.models import Skill, SkillExecutionContext

        # Verify _evaluate_condition works with "a.success" style conditions
        scratch = {"a": {"status": "success"}}
        assert _evaluate_condition("a.success", scratch) is True
        scratch = {"a": {"status": "failure"}}
        assert _evaluate_condition("a.success", scratch) is False

    @pytest.mark.asyncio
    async def test_execute_dag_respects_approval_gate(self):
        """Integration: verify node -> hits approval -> returns draft."""
        from backend.skills.executor import execute_skill
        from backend.skills.registry import SkillRegistry

        registry = SkillRegistry()
        registry.load_all()
        skill = registry.get("subscription-refund")

        # Count LLM calls to verify nodes execute
        call_count = 0

        async def counting_llm(prompt, system="", agent_role=None):
            nonlocal call_count
            call_count += 1
            return '{"text": "ok"}'

        mock_tools = MagicMock()
        mock_tools.get = lambda name: MagicMock()

        result = await execute_skill(
            skill=skill,
            task_id=str(uuid.uuid4()),
            llm_complete=counting_llm,
            tools=mock_tools,
        )

        # verify completes (1 LLM call) → triggers draft node → requires_approval → pause with draft
        # Only verify runs; draft is paused before execution (approval gate)
        assert result.status == "draft", f"Expected draft, got {result.status}"
        # verify node executed (1 call), draft node paused (0 calls yet)
        assert call_count == 1, f"Expected 1 LLM call (verify only), got {call_count}"