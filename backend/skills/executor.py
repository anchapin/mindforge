"""DAG skill executor with approval gates and retry logic.

From SPEC.md Section 2.3, 5.1.
"""

from __future__ import annotations

import asyncio
import json
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


def _try_get_tool(registry, name):
    """ToolRegistry.get raises KeyError on miss; we want None for prompt-rendering."""
    try:
        return registry.get(name) if registry is not None else None
    except Exception:
        return None


def _format_tool_catalog(tool_names, registry):
    """Render the tools available to a node into a system-prompt block.

    Looks up each tool in the registry (silently skips unknown names so a
    misnamed tool doesn't kill the whole DAG). Each entry shows
    name + class description + required integrations.
    """
    if not tool_names or registry is None:
        return ""
    lines = []
    for name in tool_names:
        tool = _try_get_tool(registry, name)
        if tool is None:
            continue
        desc = (getattr(tool, "description", "") or "").strip()
        integrations = getattr(tool, "required_integrations", []) or []
        line = f"- {name}"
        if desc:
            line += f": {desc}"
        if integrations:
            line += f" (requires: {', '.join(integrations)})"
        lines.append(line)
    if not lines:
        return ""
    return "## Available tools\n" + "\n".join(lines)


def _format_scratch_context(scratch, nodes_completed):
    """Render prior-node outputs as a user-prompt block so a downstream
    node has access to what came before. Without this every node sees
    only its own goal and multi-step DAGs degenerate into independent
    single-shot calls."""
    if not nodes_completed:
        return ""
    blocks = []
    for node_id in nodes_completed:
        entry = scratch.get(node_id)
        if not isinstance(entry, dict) or entry.get("status") != "success":
            continue
        output = entry.get("output", {})
        if isinstance(output, dict):
            text = output.get("text") or json.dumps(output, default=str)
        else:
            text = str(output)
        blocks.append(f"### {node_id}\n{text}")
    if not blocks:
        return ""
    return "## Prior node outputs (scratch)\n" + "\n\n".join(blocks)


async def execute_node(
    node: SkillNode,
    ctx: SkillExecutionContext,
    llm_complete: Any,
    tools: Any,
) -> NodeResult:
    """Execute a single skill node.

    Builds the prompt from three layers and calls the injected llm_complete:
      1. System prompt: agent identity + node goal + the tool catalog (so the
         model knows what's available — names, descriptions, integration reqs).
      2. User prompt: skill description + node goal + prior scratch state (so
         the model can build on previous nodes' outputs instead of starting
         fresh every time — this is what makes multi-node DAGs work).
      3. Output is captured into ctx.scratch[node.id] so the next node can
         read it via _format_scratch_context.

    Args:
        node: The SkillNode to execute.
        ctx: The current execution context.
        llm_complete: Async callable(prompt, system, agent_role) -> str.
            In production this is LLMRouter.complete; tests pass a fake.
        tools: ToolRegistry (or any object with a .get(name) -> BaseTool).
    """
    scratch = ctx.scratch

    try:
        # Layer 1: system prompt — agent identity + goal + tool catalog
        tool_catalog = _format_tool_catalog(node.tools or [], tools)
        system_parts = [
            f"You are a {node.agent} agent.",
            f"Your task: {node.goal}",
        ]
        if tool_catalog:
            system_parts.append(tool_catalog)
        system = "\n\n".join(system_parts)

        # Layer 2: user prompt — skill description + goal + prior scratch
        prompt_parts = [
            f"## Skill\n{ctx.skill.description}",
            f"## Goal\n{node.goal}",
        ]
        scratch_block = _format_scratch_context(scratch, ctx.nodes_completed)
        if scratch_block:
            prompt_parts.append(scratch_block)
        prompt = "\n\n".join(prompt_parts)

        output_text = await llm_complete(
            prompt=prompt,
            system=system,
            agent_role=node.agent,
        )

        # Track which tools were actually offered to the model — useful for
        # observability / future tool-call enforcement.
        tools_offered = [
            name for name in (node.tools or [])
            if _try_get_tool(tools, name) is not None
        ]
        output: dict[str, Any] = {
            "text": output_text,
            "tools_offered": tools_offered,
            "tools_used": node.tools,  # kept for back-compat with existing tests
        }

        scratch[node.id] = {"status": "success", "output": output}
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
                node.id,
                attempt,
                max_attempts,
                backoff,
            )
            await asyncio.sleep(backoff)

    return last_result or NodeResult(
        node_id=node.id, status="failure", error="max retries exceeded"
    )


async def execute_skill(
    skill: Skill,
    task_id: str,
    llm_complete: Any,
    tools: Any,
    initial_context: dict[str, Any] | None = None,
    _ws_manager: Any = None,
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
    return await _execute_dag(ctx, graph, llm_complete, tools, ws_manager=_ws_manager)


async def _execute_dag(
    ctx: SkillExecutionContext,
    graph: ExecutionGraph,
    llm_complete: Any,
    tools: Any,
    ws_manager: Any = None,
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
            ws = ws_manager
            if ws is None:
                from backend.api.deps import get_ws_manager as _get_ws
                ws = _get_ws()
            deadline = (datetime.utcnow().timestamp() + node.approval_timeout_minutes * 60
                if node.approval_timeout_minutes else 0)
            deadline_iso = (
                datetime.fromtimestamp(deadline).isoformat()
                if deadline else datetime.utcnow().isoformat()
            )
            await ws.send_draft_ready(
                task_id=ctx.task_id,
                node_id=node.id,
                draft=ctx.scratch.get(node.id, {}).get("output", {}),
                approval_deadline_iso=deadline_iso,
            )
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
