"""Engineer Agent — code, GitHub, technical tasks.

From SPEC.md Section 2.1.
Writes, reviews, and refactors code; manages GitHub issues and PRs.
All code changes require human review before push.
"""

from __future__ import annotations

import json as json_lib
import logging
from typing import Any

from ..llm.router import InferenceTier, llm_complete

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are the Engineer agent of a small team of AI agents.
Your job is code, GitHub, and technical tasks.

You write, review, and refactor code; manage GitHub issues and PRs;
build and deploy software; debug and fix issues.

All code changes must be reviewed by the user before they are pushed or merged.
You draft code, not commit it. Surface the change for approval.
"""


async def run(
    task_description: str,
    memory_context: str,
    context: dict[str, Any],
) -> dict[str, Any]:  # type: ignore[no-any-return]
    """Run the Engineer agent.

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
1. Understand the technical request fully.
2. If it involves code changes, draft the changes for human review.
3. If it involves GitHub operations (issues, PRs, reviews), draft the action for approval.
4. Never push, merge, or deploy without explicit human approval.

Return your response as JSON with fields: summary, result, next_steps.
"""

    try:
        response = await llm_complete(
            prompt,
            system="You are the Engineer agent. Output only valid JSON with summary/result/next_steps fields.",
            tier=InferenceTier.CLOUD_HEAVY,
        )
        result = json_lib.loads(response)
        logger.info("Engineer completed: %s", result.get("summary", ""))
        return result
    except json_lib.JSONDecodeError as exc:
        logger.error("Engineer returned non-JSON: %s", exc)
        return {"summary": "Engineer parse error", "result": "", "next_steps": []}
    except Exception as exc:
        logger.exception("Engineer error: %s", exc)
        return {"summary": f"Engineer error: {exc}", "result": "", "next_steps": []}
