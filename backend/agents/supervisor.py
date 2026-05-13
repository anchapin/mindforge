"""LangGraph supervisor orchestrator.

From SPEC.md Section 2.1 and Section 5.2.
Single supervisor (COO) routes tasks to specialist agents using classify_task_type().
Uses LangGraph StateGraph with SQLite checkpointer for task persistence across restarts.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, StateGraph
from sqlalchemy import create_engine

from ..llm.router import InferenceTier, llm_complete
from ..memory.store import SharedMemoryStore
from .routing import AGENT_ROLES, classify_task_type, route_to_agent

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------------------
# Supervisor state
# ---------------------------------------------------------------------------------------

@dataclass
class AgentState:
    """LangGraph state for the supervisor workflow."""
    current_task: str = ""
    task_id: str = ""
    agent_role: str = "coo"
    memory_context: str = ""
    skill_name: str | None = None
    context: dict[str, Any] = field(default_factory=dict)
    messages: list[dict[str, Any]] = field(default_factory=list)
    result: dict[str, Any] | None = None
    error: str | None = None

    def model_copy(self, update: dict[str, Any]) -> AgentState:
        """Shallow copy with field updates (compatible with Pydantic-like usage)."""
        import copy
        new_state = copy.copy(self)
        for k, v in update.items():
            setattr(new_state, k, v)
        return new_state


# ---------------------------------------------------------------------------------------
# Supervisor node functions
# ---------------------------------------------------------------------------------------

def supervisor_node(state: AgentState) -> AgentState:
    """Router node - decides which specialist agent handles the task.

    Uses keyword-based classify_task_type() first (zero cost/latency).
    """
    task_type = classify_task_type(state.current_task)
    route = route_to_agent(state.current_task, task_type)

    logger.info(
        "Supervisor routing: task_id=%s task_type=%s -> %s (confidence=%.2f)",
        state.task_id, task_type, route.agent_role, route.confidence,
    )

    return state.model_copy(update={
        "agent_role": route.agent_role,
        "context": {
            **state.context,
            "task_type": task_type,
            "routing_confidence": route.confidence,
        },
    })


async def specialist_node(
    state: AgentState,
    memory_store: SharedMemoryStore,
) -> AgentState:
    """Call the specialist agent (CMO, Researcher, Engineer, or COO-self)."""
    role_prompt = AGENT_ROLES.get(state.agent_role, AGENT_ROLES["coo"])

    memory_context = await memory_store.read(
        query=state.current_task,
        project_id=state.context.get("project_id"),
        memory_types=["semantic", "episodic", "style"],
        top_k=5,
    )

    system_msg = (
        role_prompt + "\n\n" +
        memory_context + "\n\n" +
        "## Current Task\n" + state.current_task + "\n\n" +
        "## Output Format\n" +
        "Return your response as a JSON object with fields: summary, result, next_steps.\n" +
        "Do not include any fields not listed above."
    )

    try:
        response = await llm_complete(
            system_msg,
            tier=InferenceTier.CLOUD_HEAVY,
        )

        result_data = json.loads(response)
        logger.info(
            "Specialist completed: task_id=%s agent=%s",
            state.task_id, state.agent_role,
        )

        return state.model_copy(update={
            "memory_context": memory_context,
            "result": result_data,
            "messages": state.messages + [
                {"role": state.agent_role, "content": result_data.get("result", "")},
            ],
        })
    except json.JSONDecodeError as exc:
        logger.error("Specialist returned non-JSON response: %s", exc)
        return state.model_copy(update={
            "error": f"Specialist parse error: {exc}",
        })
    except Exception as exc:
        logger.exception("Specialist error: task_id=%s agent=%s", state.task_id, state.agent_role)
        return state.model_copy(update={"error": str(exc)})


def should_continue(state: AgentState) -> Literal["supervisor", "__end__"]:
    """Graph routing: after specialist, either loop back or end."""
    if state.error and "retry" in state.context.get("flags", []):
        return "supervisor"
    return END


# ---------------------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------------------

def build_supervisor_graph(
    memory_store: SharedMemoryStore,
    checkpointer_path: str | None = None,
) -> StateGraph:
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
        engine = create_engine(f"sqlite:///{checkpointer_path}")
        checkpointer = SqliteSaver(engine)
        return builder.compile(checkpointer=checkpointer)

    return builder.compile()


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
            project_id=project_id,
            skill_name=skill_name,
            context={"project_id": project_id},
        )

        logger.info(
            "Supervisor run started: task_id=%s project_id=%s skill=%s",
            tid, project_id, skill_name,
        )

        try:
            final_state = await self.graph.ainvoke(initial_state, cfg)
            return final_state
        except Exception as exc:
            logger.exception("Supervisor run failed: task_id=%s", tid)
            return initial_state.model_copy(update={"error": str(exc)})
