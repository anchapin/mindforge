"""Skill triggering: keyword + explicit + intent classifier chain.

From SPEC.md Section 2.3 — trigger_skill() entry point.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from backend.skills.models import Skill
from backend.skills.registry import get_registry

if TYPE_CHECKING:
    from backend.llm.router import LLMRouter

logger = logging.getLogger(__name__)


async def trigger_skill(
    task_description: str,
    llm_router: "LLMRouter | None" = None,
) -> Skill | None:
    """Find the best-matching skill for a task description.

    Resolution order (SPEC.md Section 2.3):
    1. Explicit invocation — skill name appears verbatim in the task
    2. Keyword match — any trigger keyword present (fast path, no LLM)
    3. Intent classifier — lightweight LLM call, only if keyword missed

    Args:
        task_description: The raw user task string.
        llm_router: Optional LLM router for intent classification fallback.

    Returns:
        The matched Skill, or None if no skill applies.
    """
    registry = get_registry()

    # 1. Explicit match
    explicit = registry.find_by_name(task_description)
    if explicit:
        logger.info("trigger: explicit match skill=%s", explicit.id)
        return explicit

    # 2. Keyword match (fast path)
    keyword_match = registry.find_by_keyword(task_description)
    if keyword_match:
        logger.info("trigger: keyword match skill=%s", keyword_match.id)
        return keyword_match

    # 3. Intent classifier (LLM call, only if keyword missed)
    if llm_router is not None:
        intent = await _classify_intent(task_description, llm_router)
        skill = registry.find_by_intent(intent) if hasattr(registry, "find_by_intent") else None
        if skill:
            logger.info("trigger: intent=%s skill=%s", intent, skill.id)
            return skill
        logger.info("trigger: intent=%s — no skill matched", intent)

    logger.info("trigger: no skill matched for task")
    return None


async def _classify_intent(
    task_description: str,
    llm_router: "LLMRouter",
) -> str:
    """Classify a task into an intent string using a lightweight LLM call.

    This is a lightweight prompt — no tools, no multi-step reasoning.
    Returns an intent string like "request_refund", "summarize_commits", etc.
    """
    registry = get_registry()
    available_skills = [s.name for s in registry.list()]

    prompt = (
        "You are a task classifier. Given a user task, output the most fitting "
        "intent label from the available skills, or 'general' if none apply.\n\n"
        f"Available skills: {', '.join(available_skills) or 'none'}\n\n"
        f"Task: {task_description}\n\n"
        "Intent label:"
    )

    try:
        response = await llm_router.complete(
            prompt=prompt,
            tier=llm_router.__class__.__name__,
            system="You are a concise task classifier. Output only the intent label.",
            agent_role="cmo",
        )
        return response.strip().lower().replace(" ", "_")
    except Exception as exc:  # pragma: no cover
        logger.warning("intent classification failed: %s", exc)
        return "general"
