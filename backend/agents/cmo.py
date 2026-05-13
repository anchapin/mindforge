"""CMO Agent — marketing, content, communications.

From SPEC.md Section 2.1.
Handles email drafting, social posts, blog articles, reports.
All external outputs go through draft-first approval workflow.
"""

from __future__ import annotations

import json as json_lib
import logging
from typing import Any

from ..llm.router import llm_complete, InferenceTier

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are the CMO (Chief Marketing Officer) of a small team of AI agents.
Your job is marketing, content creation, and communications.

You draft emails, social posts, blog articles, newsletters, and reports
in the user's voice — grounded in the memory context provided.

You NEVER send externally. You always surface a draft for human approval
before any external action (send, post, publish, submit).

When you produce a draft, structure it so the user can easily review,
edit, and approve or reject it.
"""


async def run(
    task_description: str,
    memory_context: str,
    context: dict[str, Any],
) -> dict[str, Any]:
    """Run the CMO agent.

    Args:
        task_description: The user's request.
        memory_context: Formatted memory from SharedMemoryStore.
        context: Additional execution context.

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
Analyze the request and produce content in the user's voice.
If this is an email, include subject line and body.
If this is social content, include the post text and any hashtags.
If this is a blog article, include title, outline, and body.

Always surface a draft suitable for human review. Never auto-send.

Return your response as JSON with fields: summary, result, next_steps.
"""

    try:
        response = await llm_complete(
            prompt,
            system="You are the CMO agent. Output only valid JSON with summary/result/next_steps fields.",
            tier=InferenceTier.CLOUD_HEAVY,
        )
        result = json_lib.loads(response)
        logger.info("CMO completed: %s", result.get("summary", ""))
        return result
    except json_lib.JSONDecodeError as exc:
        logger.error("CMO returned non-JSON: %s", exc)
        return {"summary": "CMO parse error", "result": "", "next_steps": []}
    except Exception as exc:
        logger.exception("CMO error: %s", exc)
        return {"summary": f"CMO error: {exc}", "result": "", "next_steps": []}