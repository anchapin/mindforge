"""COO Agent — planning, coordination, oversight, escalation handling.

From SPEC.md Section 2.1.
The COO is the orchestration layer: decomposes tasks, assigns to specialists,
monitors progress, and escalates ambiguous or high-stakes decisions to the human.
"""

from __future__ import annotations

import logging
from typing import Any

from ..llm.router import InferenceTier, llm_complete

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are the COO (Chief Operating Officer) of a small team of AI agents.
Your job is planning, coordination, and oversight.

You decompose complex requests into clear sub-tasks, assign them to the right
specialist agents, and synthesize their results into coherent outcomes.

You represent the user's strategic interests. You are the last line of defense
before an action reaches the outside world — always surface drafts for human
approval when the stakes are unclear.

When uncertain, escalate to the user rather than proceed. Never guess at intent.
"""


async def run(
    task_description: str,
    memory_context: str,
    context: dict[str, Any],
) -> dict[str, Any]:
    """Run the COO agent.

    Args:
        task_description: The user's request.
        memory_context: Formatted memory from SharedMemoryStore.
        context: Additional execution context (task_type, project_id, etc.)

    Returns:
        Agent response dict with 'summary', 'result', 'next_steps' keys.
    """
    task_type = context.get("task_type", "general")
    project_id = context.get("project_id")

    prompt = f"""{SYSTEM_PROMPT}

## Memory Context
{memory_context}

## Current Task
{task_description}

## Task Type
{task_type}

## Instructions
1. Determine if this task should be handled by a specialist agent (CMO, Researcher, Engineer)
   or by you directly.
2. If it requires specialist input, return next_steps that delegate to them.
3. If it is a planning/coordination task, handle it directly and return the result.
4. Return your response as JSON with fields: summary, result, next_steps.

## Output Format
Return a JSON object with these exact fields (no others):
- "summary": Brief summary of what you did or decided
- "result": The actual output or decision
- "next_steps": List of follow-up actions (can be empty list)
"""

    try:
        response = await llm_complete(
            prompt,
            system="You are the COO agent. Output only valid JSON with summary/result/next_steps fields.",
            tier=InferenceTier.CLOUD_HEAVY,
        )
        import json
        result = json.loads(response)
        logger.info("COO completed: %s", result.get("summary", ""))
        return result
    except json.JSONDecodeError as exc:
        logger.error("COO returned non-JSON: %s", exc)
        return {"summary": "COO parse error", "result": "", "next_steps": []}
    except Exception as exc:
        logger.exception("COO error: %s", exc)
        return {"summary": f"COO error: {exc}", "result": "", "next_steps": []}
