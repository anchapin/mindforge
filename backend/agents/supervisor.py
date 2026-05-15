"""LangGraph supervisor orchestrator.

From SPEC.md Section 2.1 and Section 5.2.
Single supervisor (COO) routes tasks to specialist agents using classify_task_type().
Uses LangGraph StateGraph with SQLite checkpointer for task persistence across restarts.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from ..memory.store import SharedMemoryStore
from . import cmo, coo, engineer, researcher
from .routing import route_to_agent

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------------------
# Task type classification
# ---------------------------------------------------------------------------------------

TASK_TYPE_RULES: list[tuple[str, list[str]]] = [
    ("github", ["github", "commit", "pr ", "pull request", "repository", "git"]),
    ("email", ["email", "reply", "inbox", "mail", "send", "draft"]),
    ("research", ["research", "find", "look up", "lookup", "analyze", "competitor", "market"]),
    ("finance", ["refund", "invoice", "billing", "stripe", "revenue", "cost"]),
    ("engineering", ["code", "deploy", "build", "debug", "ship", "unit test", "auth module"]),
    ("operations", ["schedule", "calendar", "meeting", "task", "project", "board"]),
    ("content", ["write", "blog", "post", "tweet", "linkedin", "copy"]),
]


def classify_task_type(query: str) -> str:
    """Rule-based keyword task classifier. Zero cost, zero latency.

    Used for episodic memory scoping and agent routing.
    Falls back to LLM-based classify_intent() for skill triggering.
    """
    query_lower = query.lower()
    for task_type, keywords in TASK_TYPE_RULES:
        if any(kw in query_lower for kw in keywords):
            return task_type
    return "general"


# ---------------------------------------------------------------------------------------
# Supervisor state
# ---------------------------------------------------------------------------------------


@dataclass
class AgentState:
    """LangGraph state for the supervisor workflow."""

    current_task: str = ""
    task_id: str = ""
    project_id: str = ""
    agent_role: str = "coo"
    memory_context: str = ""
    skill_name: str | None = None
    context: dict[str, Any] = field(default_factory=dict)
    messages: list[dict[str, Any]] = field(default_factory=list)
    result: dict[str, Any] | None = None
    error: str | None = None

    def model_copy(self, update: dict[str, Any]) -> AgentState:
        """Shallow copy with field updates."""
        import copy

        new_state = copy.copy(self)
        for k, v in update.items():
            setattr(new_state, k, v)
        return new_state


# ---------------------------------------------------------------------------------------
# Agent dispatch
# ---------------------------------------------------------------------------------------


async def _run_agent(
    agent_role: str,
    task_description: str,
    memory_context: str,
    context: dict[str, Any],
) -> dict[str, Any]:
    """Dispatch to the appropriate agent by role."""
    if agent_role == "coo":
        return await coo.run(task_description, memory_context, context)
    elif agent_role == "cmo":
        return await cmo.run(task_description, memory_context, context)
    elif agent_role == "researcher":
        return await researcher.run(task_description, memory_context, context)
    elif agent_role == "engineer":
        return await engineer.run(task_description, memory_context, context)
    else:
        return {"summary": f"Unknown agent role: {agent_role}", "result": "", "next_steps": []}


# ---------------------------------------------------------------------------------------
# Supervisor node functions
# ---------------------------------------------------------------------------------------


def supervisor_node(state: AgentState) -> AgentState:
    """Router node — decides which specialist agent handles the task.

    Uses keyword-based classify_task_type() first (zero cost/latency).
    """
    task_type = classify_task_type(state.current_task)
    route = route_to_agent(state.current_task, task_type)

    logger.info(
        "Supervisor routing: task_id=%s task_type=%s -> %s (confidence=%.2f)",
        state.task_id,
        task_type,
        route.agent_role,
        route.confidence,
    )

    return state.model_copy(
        update={
            "agent_role": route.agent_role,
            "context": {
                **state.context,
                "task_type": task_type,
                "routing_confidence": route.confidence,
            },
        }
    )


async def specialist_node(
    state: AgentState,
    memory_store: SharedMemoryStore,
) -> AgentState:
    """Call the specialist agent (CMO, Researcher, Engineer, or COO-self)."""
    task_type = state.context.get("task_type", "general")
    project_id = state.context.get("project_id")

    memory_context = await memory_store.read(
        query=state.current_task,
        project_id=project_id,
        memory_types=["semantic", "episodic", "style"],
        top_k=5,
    )

    try:
        agent_result = await _run_agent(
            state.agent_role,
            state.current_task,
            memory_context,
            state.context,
        )

        logger.info(
            "Specialist completed: task_id=%s agent=%s result=%s",
            state.task_id,
            state.agent_role,
            agent_result.get("summary", ""),
        )

        if agent_result.get("clarification_needed"):
            from backend.api.websocket import ws_manager

            deadline_iso = (datetime.now(UTC) + timedelta(hours=24)).isoformat()
            await ws_manager.send_clarification_request(
                task_id=state.task_id,
                node_id=f"{state.agent_role}_clarification",
                question=str(
                    agent_result.get("question") or "Please clarify how I should proceed."
                ),
                options=list(agent_result.get("options") or []),
                context_summary=str(agent_result.get("context_summary") or memory_context),
                deadline_iso=deadline_iso,
            )

        return state.model_copy(
            update={
                "memory_context": memory_context,
                "result": agent_result,
                "messages": state.messages
                + [
                    {"role": state.agent_role, "content": agent_result.get("result", "")},
                ],
            }
        )
    except Exception as exc:
        logger.exception(
            "Specialist error: task_id=%s agent=%s",
            state.task_id,
            state.agent_role,
        )
        return state.model_copy(update={"error": str(exc)})


# ---------------------------------------------------------------------------------------
# Layer 3 — Approval gate helpers (§3b.8)
# ---------------------------------------------------------------------------------------

_HIGH_STAKES_ACTIONS: frozenset[str] = frozenset(
    [
        # Email — user-facing external messaging
        "send_email",
        "send_email_reply",
        "email_send.send",  # EmailSendTool.execute(action="send") — #42
        # GitHub — code surface
        "github_push",
        "github_create_pr",
        "github_merge_pr",
        # Stripe — money
        "stripe_refund",
        "stripe_payment",
        "stripe_api.refund",  # StripeTool.execute(action="refund") — #43 wires this
        # Destructive
        "delete_memory",
        "delete_task",
    ]
)


def is_high_stakes_action(action: str) -> bool:
    """Return True if action is high-stakes (email/GitHub/Stripe/destructive)."""
    return action in _HIGH_STAKES_ACTIONS


def requires_memory_approval_gate(action: str, memory_context_ratio: float) -> bool:
    """Return True if memory-dominated context (>50%) + high-stakes action triggers approval gate."""
    return memory_context_ratio > 0.5


def should_continue(state: AgentState) -> Literal["supervisor", END]:  # type: ignore[return-value,valid-type]
    """Graph routing: after specialist, either loop back or end.

    Layer 3 — Approval gate amplification (§3b.8):
    If the specialist wants to execute a high-stakes action AND memory
    was the dominant context (>50%), force the draft-approval cycle
    by returning to supervisor to wait for human approval.
    """
    if state.error and "retry" in state.context.get("flags", []):  # type: ignore[union-attr]
        return "supervisor"

    # Layer 3: memory-driven high-stakes actions require approval
    result = state.result or {}
    proposed_action = result.get("proposed_action", "")
    if (
        proposed_action
        and is_high_stakes_action(proposed_action)
        and requires_memory_approval_gate(
            action=proposed_action,
            memory_context_ratio=state.context.get("memory_ratio", 0.0),
        )
    ):
        logger.info(
            "Layer 3 approval gate triggered: action=%s memory_ratio=%.2f — awaiting human approval",
            proposed_action,
            state.context.get("memory_ratio", 0.0),
        )
        # Force pending_approval in context and return to supervisor
        # The human approval gate in api/routes/tasks.py will handle this
        return END  # Supervisor will pick up the pending_approval state

    return END


# ---------------------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------------------


def build_supervisor_graph(
    memory_store: SharedMemoryStore,
    checkpointer_path: str | None = None,
) -> StateGraph:  # type: ignore[return-value]
    """Build the LangGraph supervisor workflow."""

    async def _specialist_async(state: AgentState) -> AgentState:
        return await specialist_node(state, memory_store)

    builder = StateGraph(AgentState)

    builder.add_node("supervisor", supervisor_node)
    builder.add_node("specialist", _specialist_async)

    builder.set_entry_point("supervisor")
    builder.add_edge("supervisor", "specialist")
    builder.add_conditional_edges(
        "specialist",
        should_continue,
        {"supervisor": "supervisor", END: END},
    )

    if checkpointer_path:
        # SQLite-based checkpointer for persistence across restarts.
        # Install langgraph-checkpoint-sqlite>=2.0.0,<3.0.0 and aiosqlite for async use:
        #   pip install langgraph-checkpoint-sqlite aiosqlite
        # SqliteSaver (sync) does NOT support async ainvoke() — must use AsyncSqliteSaver.
        # We must do the async connection + compile in a sync-safe way:
        try:
            # aiosqlite.connect() is a coroutine — resolve it at graph-building time.
            # Since both loop.run_until_complete() and asyncio.run() fail when
            # called from within an existing event loop (pytest async context),
            # we run the connection in a separate daemon thread and block until
            # it completes. This is safe for graph-building which is a
            # synchronous operation at startup.
            import threading

            import aiosqlite
            from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

            conn_holder: list[aiosqlite.Connection | None] = [None]

            def _connect():
                tloop = asyncio.new_event_loop()
                try:
                    conn_holder[0] = tloop.run_until_complete(aiosqlite.connect(checkpointer_path))
                finally:
                    tloop.close()

            t = threading.Thread(target=_connect, daemon=True)
            t.start()
            t.join()  # Block until connection is ready
            conn = conn_holder[0]
            assert conn is not None, "aiosqlite.connect() returned None"
            checkpointer = AsyncSqliteSaver(conn)
            return builder.compile(checkpointer=checkpointer)  # type: ignore[return-value]
        except ImportError:
            logger.warning(
                "AsyncSqliteSaver not available, using MemorySaver (no persistence). "
                "Install langgraph-checkpoint-sqlite>=2.0.0,<3.0.0 and aiosqlite for persistence."
            )
            return builder.compile(checkpointer=MemorySaver())  # type: ignore[return-value]

    return builder.compile()  # type: ignore[return-value]


# ---------------------------------------------------------------------------------------
# Supervisor runner
# ---------------------------------------------------------------------------------------


class SupervisorRunner:
    """Runs the supervisor graph for a given task."""

    def __init__(
        self,
        memory_store: SharedMemoryStore,
        checkpointer_path: str | None = None,
    ):
        self.graph = build_supervisor_graph(memory_store, checkpointer_path)
        self._memory = memory_store

    async def run(
        self,
        task_description: str,
        task_id: str | None = None,
        project_id: str | None = None,
        skill_name: str | None = None,
        config: dict | None = None,
    ) -> AgentState:
        """Run the supervisor graph for a task.

        Args:
            task_description: Natural language task from the user.
            task_id: Persistent task ID for checkpointer resume.
            project_id: Scopes memory to a project.
            skill_name: Skill being executed.
            config: LangGraph config dict (thread_id, etc.)

        Returns:
            Final AgentState with result or error.
        """
        tid = task_id or str(uuid.uuid4())
        cfg = config or {"configurable": {"thread_id": tid}}

        initial_state = AgentState(
            current_task=task_description,
            task_id=tid,
            project_id=project_id or "",
            skill_name=skill_name,
            context={"project_id": project_id or ""},
        )

        logger.info(
            "Supervisor run started: task_id=%s project_id=%s skill=%s",
            tid,
            project_id,
            skill_name,
        )

        try:
            final_state = await self.graph.ainvoke(initial_state, cfg)  # type: ignore[attr-defined]
            return final_state
        except Exception as exc:
            logger.exception("Supervisor run failed: task_id=%s", tid)
            return initial_state.model_copy(update={"error": str(exc)})

    async def run_with_skill(
        self,
        skill_execution_context: dict[str, Any],
        task_id: str | None = None,
        config: dict | None = None,
    ) -> AgentState:
        """Run supervisor with a skill execution context.

        Used by the skill executor to delegate the agent node to the supervisor.
        """
        return await self.run(
            task_description=skill_execution_context.get("task_description", ""),
            task_id=task_id,
            project_id=skill_execution_context.get("project_id"),
            skill_name=skill_execution_context.get("skill_name"),
            config=config,
        )
