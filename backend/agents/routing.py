"""Task classification and agent role routing.

From SPEC.md §2.1 and §2.2.
classify_task_type() — keyword rules for episodic memory scoping
classify_intent() — LLM-based skill intent classifier (for skill routing)
AGENT_ROLES — system prompts for each agent role
route_to_agent() — maps task_type to agent role
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from ..llm.router import InferenceTier, llm_complete

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------------------
# Agent role definitions
# ---------------------------------------------------------------------------------------

AGENT_ROLES: dict[str, str] = {
    "coo": (
        "You are the COO (Chief Operating Officer) agent. "
        "Your job is planning, coordination, and oversight. "
        "You decompose tasks, assign to specialists, monitor progress, "
        "and escalate when human input is needed. "
        "You represent the user's strategic interests."
    ),
    "cmo": (
        "You are the CMO (Chief Marketing Officer) agent. "
        "Your job is marketing, content creation, and communications. "
        "You draft emails, social posts, blog articles, and reports "
        "in the user's voice. You surface drafts for human approval "
        "before any external action."
    ),
    "researcher": (
        "You are the Researcher agent. "
        "Your job is web research, data analysis, and competitive intelligence. "
        "You find information, synthesize findings, and present structured reports. "
        "You do not take external actions — you gather and analyze."
    ),
    "engineer": (
        "You are the Engineer agent. "
        "Your job is code, GitHub, and technical tasks. "
        "You write, review, and refactor code; manage GitHub issues and PRs; "
        "build and deploy software. "
        "All code changes require human review before push."
    ),
}


# ---------------------------------------------------------------------------------------
# Agent routing
# ---------------------------------------------------------------------------------------

@dataclass
class RouteResult:
    agent_role: str
    confidence: float  # 0.0 - 1.0
    reasoning: str


def route_to_agent(task_description: str, task_type: str) -> RouteResult:
    """Route a task to the most appropriate agent role based on task_type.

    Uses deterministic keyword to task_type mapping.
    Falls back to COO for ambiguous cases.
    """
    ROLE_MAP: dict[str, str] = {
        "github":       "engineer",
        "engineering":  "engineer",
        "email":        "cmo",
        "content":      "cmo",
        "research":     "researcher",
        "finance":      "coo",
        "operations":   "coo",
        "general":      "coo",
    }

    agent_role = ROLE_MAP.get(task_type, "coo")
    confidence = 1.0 if task_type in ROLE_MAP else 0.5

    return RouteResult(
        agent_role=agent_role,
        confidence=confidence,
        reasoning=f"task_type={task_type!r} mapped to {agent_role}",
    )


# ---------------------------------------------------------------------------------------
# Intent classification for skills (LLM-based, heavier)
# ---------------------------------------------------------------------------------------

SKILL_INTENTS = [
    "email_draft", "email_reply", "email_summary",
    "github_activity", "github_issue", "github_pr_review",
    "refund_negotiation", "billing_inquiry", "invoice_review",
    "content_post", "content_edit", "content_strategy",
    "research_summary", "research_comparison", "research_alert",
    "calendar_schedule", "calendar_conflict", "meeting_prep",
    "general",
]

_CLASSIFY_INTENT_PROMPT = (
    "You are a task classifier. Given the user query, output exactly one intent label "
    "from this list: {intents}.\n\nQuery: {query}\nIntent:"
)


async def classify_intent(query: str) -> str:
    """Classify task intent for skill routing using LLM.

    Called when keyword matching does not match a skill trigger.
    Uses CLOUD_FAST tier — never local, never heaviest model.

    Returns one of SKILL_INTENTS labels.
    """
    rendered = _CLASSIFY_INTENT_PROMPT.format(
        intents=", ".join(SKILL_INTENTS),
        query=query,
    )
    try:
        result = await llm_complete(
            rendered,
            tier=InferenceTier.CLOUD_FAST,
            system="Output only the intent label, nothing else.",
        )
        label = result.strip().lower()
        if label in SKILL_INTENTS:
            return label
        for intent in SKILL_INTENTS:
            if intent.startswith(label.split()[0]):
                return intent
        return "general"
    except Exception as exc:
        logger.warning("Intent classification failed, falling back to general: %s", exc)
        return "general"
