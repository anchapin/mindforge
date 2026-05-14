"""DAG skill executor with approval gates and retry logic.

From SPEC.md Section 2.3, 5.1.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from backend.skills.models import (
    ApprovalRecord,
    ExecutionGraph,
    NodeResult,
    Skill,
    SkillExecutionContext,
    SkillNode,
    SkillResult,
)

logger = logging.getLogger(__name__)


class SkillExecutionError(Exception):
    """Raised when a skill execution fails unrecoverably."""


def _evaluate_condition(condition: str, scratch: dict[str, Any]) -> bool:
    """Evaluate a simple condition string against the scratch dict.

    Supports patterns like:
      - "fetch_commits.success"
      - "verify.completed_no_changes"
      - "draft.approved"
      - "draft.rejected"
      - "draft.timeout"

    Returns True if the condition is satisfied.
    """
    if "." not in condition:
        return bool(condition)

    node_id, _, status = condition.rpartition(".")
    node_outcome = scratch.get(node_id)
    if isinstance(node_outcome, dict):
        return node_outcome.get("status") == status
    return False


async def execute_node(
    node: SkillNode,
    ctx: SkillExecutionContext,
    llm_complete: Any,
    tools: Any,
) -> NodeResult:
    """Execute a single skill node.

    Args:
        node: The SkillNode to execute.
        ctx: The current execution context.
        llm_complete: Callable(prompt, system, agent_role) -> str.
        tools: ToolRegistry instance for resolving tool names.
    """
    scratch = ctx.scratch

    try:
        # Build system prompt from node goal
        system = (
            f"You are a {node.agent} agent. "
            f"Your task: {node.goal}\n"
            f"Working directory: skill scratch pad."
        )

        # Assemble tools if any
        available_tools = []
        if node.tools:
            for tool_name in node.tools:
                tool = tools.get(tool_name) if tools else None
                if tool:
                    available_tools.append(tool)

        # Call LLM — currently a stub that returns a simple completion
        # The actual LLM call is wired through the supervisor
        prompt = ctx.skill.description + "\n\nGoal: " + node.goal
        output_text = await llm_complete(
            prompt=prompt,
            system=system,
            agent_role=node.agent,
        )

        output: dict[str, Any] = {"text": output_text, "tools_used": node.tools}

        scratch[node.id] = {
            "status": "success",
            "output": output,
        }
        ctx.nodes_completed.append(node.id)

        return NodeResult(node_id=node.id, status="success", output=output)

    except Exception as exc:  # pragma: no cover
        logger.exception("node %s failed: %s", node.id, exc)
        scratch[node.id] = {"status": "failure", "error": str(exc)}

        if node.outcome_on_failure == "skip":
            ctx.nodes_completed.append(node.id)
            return NodeResult(node_id=node.id, status="skipped", error=str(exc))
        elif node.outcome_on_failure == "fail":
            ctx.error = str(exc)
            return NodeResult(node_id=node.id, status="failure", error=str(exc))
        else:
            ctx.nodes_completed.append(node.id)
            return NodeResult(node_id=node.id, status="skipped", error=str(exc))


async def execute_with_retry(
    node: SkillNode,
    ctx: SkillExecutionContext,
    llm_complete: Any,
    tools: Any,
) -> NodeResult:
    """Execute a node with retry logic per node.retry config."""
    max_attempts = node.retry.get("max_attempts", 1) if node.retry else 1
    backoff = node.retry.get("backoff_seconds", 30) if node.retry else 30

    last_result: NodeResult | None = None
    for attempt in range(1, max_attempts + 1):
        result = await execute_node(node, ctx, llm_complete, tools)
        last_result = result

        if result.status == "success":
            return result

        if attempt < max_attempts:
            logger.info(
                "node %s attempt %d/%d failed, retrying in %ds",
                node.id, attempt, max_attempts, backoff,
            )
            await asyncio.sleep(backoff)

    return last_result or NodeResult(node_id=node.id, status="failure", error="max retries exceeded")


async def execute_skill(
    skill: Skill,
    task_id: str,
    llm_complete: Any,
    tools: Any,
    initial_context: dict[str, Any] | None = None,
) -> SkillResult:
    """Execute a skill DAG from start to finish or first approval gate.

    This runs the DAG until either:
    - All nodes complete (returns completed)
    - A node with requires_approval=True is hit (returns draft)

    After approval, call execute_skill_continue() to resume.

    Args:
        skill: The Skill to execute.
        task_id: Associated task ID for context.
        llm_complete: Async callable for LLM inference.
        tools: ToolRegistry or similar.
        initial_context: Optional scratch pad to start with.

    Returns:
        SkillResult with current execution state.
    """
    graph = skill.execution_graph
    if not graph or not graph.nodes:
        return SkillResult(
            skill_id=skill.id,
            skill_version=skill.version,
            status="failed",
            error="skill has no execution graph",
            started_at=datetime.utcnow(),
            completed_at=datetime.utcnow(),
        )

    ctx = SkillExecutionContext(
        task_id=task_id,
        skill=skill,
        node_id=graph.nodes[0].id,
        scratch=initial_context or {},
        nodes_completed=[],
        started_at=datetime.utcnow(),
    )

    return await _execute_dag(ctx, graph, llm_complete, tools)


async def _execute_dag(
    ctx: SkillExecutionContext,
    graph: ExecutionGraph,
    llm_complete: Any,
    tools: Any,
) -> SkillResult:
    """Internal DAG executor — walks edges, handles condition evaluation."""
    node_map: dict[str, SkillNode] = {n.id: n for n in graph.nodes}
    pending = list(graph.nodes)  # nodes in order
    idx = 0

    while idx < len(pending):
        node = pending[idx]
        idx += 1

        # Skip if already handled
        if node.id in ctx.nodes_completed:
            continue

        ctx.node_id = node.id

        # Check approval requirement BEFORE executing
        if node.requires_approval:
            # Pause and return draft state
            return SkillResult(
                skill_id=ctx.skill.id,
                skill_version=ctx.skill.version,
                status="draft",
                nodes_completed=list(ctx.nodes_completed),
                current_node=node.id,
                draft_content=ctx.scratch.get(node.id, {}).get("output"),
                approval_history=list(ctx.approval_history),
                started_at=ctx.started_at,
                completed_at=datetime.utcnow(),
            )

        # Execute the node
        result = await execute_with_retry(node, ctx, llm_complete, tools)

        if result.status == "failure":
            return SkillResult(
                skill_id=ctx.skill.id,
                skill_version=ctx.skill.version,
                status="failed",
                nodes_completed=list(ctx.nodes_completed),
                current_node=node.id,
                error=result.error,
                approval_history=list(ctx.approval_history),
                started_at=ctx.started_at,
                completed_at=datetime.utcnow(),
            )

        # Evaluate outgoing edges and enqueue next nodes
        for edge in graph.edges:
            if edge.get("from") == node.id:
                if _evaluate_condition(edge.get("condition", ""), ctx.scratch):
                    next_node = node_map.get(edge.get("to", ""))
                    if next_node and next_node.id not in ctx.nodes_completed:
                        pending.append(next_node)

    # DAG complete
    return SkillResult(
        skill_id=ctx.skill.id,
        skill_version=ctx.skill.version,
        status="completed",
        nodes_completed=list(ctx.nodes_completed),
        current_node=None,
        final_output=ctx.scratch,
        approval_history=list(ctx.approval_history),
        started_at=ctx.started_at,
        completed_at=datetime.utcnow(),
    )


async def execute_skill_continue(
    ctx: SkillExecutionContext,
    approval_action: str,  # "approved" | "rejected" | "timeout"
    edited_content: dict[str, Any] | None = None,
    llm_complete: Any = None,
    tools: Any = None,
) -> SkillResult:
    """Resume execution after an approval decision.

    Args:
        ctx: The execution context saved during the draft pause.
        approval_action: One of approved, rejected, timeout.
        edited_content: If approved with edits, the modified draft.
        llm_complete: LLM callable (required for continuation).
        tools: ToolRegistry (required for continuation).
    """
    graph = ctx.skill.execution_graph
    if not graph:
        return SkillResult(
            skill_id=ctx.skill.id,
            skill_version=ctx.skill.version,
            status="failed",
            nodes_completed=list(ctx.nodes_completed),
            error="skill has no execution graph",
            approval_history=list(ctx.approval_history),
            started_at=ctx.started_at,
            completed_at=datetime.utcnow(),
        )

    node_map: dict[str, SkillNode] = {n.id: n for n in graph.nodes}

    # Record the approval
    record = ApprovalRecord(
        node_id=ctx.node_id,
        action=approval_action,
        edited_content=edited_content,
        timestamp=datetime.utcnow(),
    )
    ctx.approval_history.append(record)

    # Update scratch with the decision
    ctx.scratch[ctx.node_id] = {
        "status": approval_action,
        "edited_content": edited_content,
    }

    if approval_action in ("rejected", "timeout"):
        ctx.error = f"Approval {approval_action} for node {ctx.node_id}"
        return SkillResult(
            skill_id=ctx.skill.id,
            skill_version=ctx.skill.version,
            status=approval_action,
            nodes_completed=list(ctx.nodes_completed),
            current_node=ctx.node_id,
            error=ctx.error,
            approval_history=list(ctx.approval_history),
            started_at=ctx.started_at,
            completed_at=datetime.utcnow(),
        )

    # approved — inject edited content if any
    if edited_content:
        ctx.draft_content = edited_content
        ctx.scratch[ctx.node_id]["output"] = edited_content

    # Continue DAG from current node
    pending = [node_map[ctx.node_id]]
    idx = 0

    while idx < len(pending):
        node = pending[idx]
        idx += 1

        if node.id in ctx.nodes_completed:
            continue

        ctx.node_id = node.id

        # Skip approval check for the node we just got approval for.
        # We are resuming FROM ctx.node_id after approval — must execute, not re-pause.
        already_approved = (
            node.requires_approval
            and node.id == ctx.node_id
            and ctx.node_id in [r.node_id for r in ctx.approval_history]
        )
        if node.requires_approval and not already_approved:
            return SkillResult(
                skill_id=ctx.skill.id,
                skill_version=ctx.skill.version,
                status="draft",
                nodes_completed=list(ctx.nodes_completed),
                current_node=node.id,
                draft_content=ctx.scratch.get(node.id, {}).get("output"),
                approval_history=list(ctx.approval_history),
                started_at=ctx.started_at,
                completed_at=datetime.utcnow(),
            )

        result = await execute_with_retry(node, ctx, llm_complete, tools)

        if result.status == "failure":
            return SkillResult(
                skill_id=ctx.skill.id,
                skill_version=ctx.skill.version,
                status="failed",
                nodes_completed=list(ctx.nodes_completed),
                current_node=node.id,
                error=result.error,
                approval_history=list(ctx.approval_history),
                started_at=ctx.started_at,
                completed_at=datetime.utcnow(),
            )

        for edge in graph.edges:
            if edge.get("from") == node.id:
                if _evaluate_condition(edge.get("condition", ""), ctx.scratch):
                    next_node = node_map.get(edge.get("to", ""))
                    if next_node and next_node.id not in ctx.nodes_completed:
                        pending.append(next_node)

    return SkillResult(
        skill_id=ctx.skill.id,
        skill_version=ctx.skill.version,
        status="completed",
        nodes_completed=list(ctx.nodes_completed),
        current_node=None,
        final_output=ctx.scratch,
        approval_history=list(ctx.approval_history),
        started_at=ctx.started_at,
        completed_at=datetime.utcnow(),
    )
