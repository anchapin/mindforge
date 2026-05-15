"""Researcher Agent — web research, data analysis, competitive intelligence.

From SPEC.md Section 2.1.
Gathers and analyzes information. Does not take external actions.
"""

from __future__ import annotations

import logging
from typing import Any

from ..llm.router import InferenceTier, llm_complete
from .json_utils import parse_with_recovery

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are the Researcher agent of a small team of AI agents.
Your job is web research, data analysis, and competitive intelligence.

You find information, synthesize findings, and present structured reports.
You do NOT take external actions — you only gather and analyze.

Present your findings in a clear, structured format with sources when possible.
"""


async def run(
    task_description: str,
    memory_context: str,
    context: dict[str, Any],
) -> dict[str, Any]:  # type: ignore[no-any-return]
    """Run the Researcher agent.

    Args:
        task_description: The user's request.
        memory_context: Formatted memory from SharedMemoryStore.
        context: Additional execution context.

    Returns:
        Agent response dict with 'summary', 'result', 'next_steps' keys.
    """
    task_type = context.get("task_type", "general")

    prompt = f"""{SYSTEM_PROMPT}

## Memory Context
{memory_context}

## Current Task
{task_description}

## Task Type
{task_type}

## Instructions
Research the topic thoroughly and return a structured report with:
- Key findings
- Data points and sources
- Analysis and implications
- Areas of uncertainty

Return your response as JSON with fields: summary, result, next_steps.
"""

    try:
        response = await llm_complete(
            prompt,
            system="You are the Researcher agent. Output only valid JSON with summary/result/next_steps fields.",
            tier=InferenceTier.CLOUD_HEAVY,
        )
        result = await parse_with_recovery(response, "Researcher", llm_complete)
        logger.info("Researcher completed: %s", result.get("summary", ""))
        return result
    except Exception as exc:
        logger.exception("Researcher error: %s", exc)
        return {"summary": f"Researcher error: {exc}", "result": "", "next_steps": []}
