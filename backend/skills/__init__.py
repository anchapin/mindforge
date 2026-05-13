"""MindForge skills — procedural memory and skill execution.

Public API:
    get_registry() -> SkillRegistry
    load_skill(skill_id: str) -> Skill | None
    list_skills() -> list[SkillMetadata]
    trigger_skill(task_description: str, llm_router=None) -> Skill | None
    execute_skill(skill, task_id, ...) -> SkillResult
    execute_skill_continue(ctx, approval_action, ...) -> SkillResult
    validate_skill_graph(skill_def: dict) -> list[str]
"""

from backend.skills.executor import (
    execute_skill,
    execute_skill_continue,
)
from backend.skills.models import (
    ApprovalRecord,
    ExecutionGraph,
    NodeResult,
    Skill,
    SkillExecutionContext,
    SkillMetadata,
    SkillNode,
    SkillResult,
)
from backend.skills.registry import (
    SkillRegistry,
    get_registry,
    validate_skill_graph,
)
from backend.skills.trigger import trigger_skill


def load_skill(skill_id: str) -> Skill | None:
    """Convenience: load a single skill by ID from the registry."""
    return get_registry().get(skill_id)


def list_skills() -> list[SkillMetadata]:
    """Convenience: list all loaded skills."""
    return get_registry().list()


__all__ = [
    # Registry
    "SkillRegistry",
    "get_registry",
    "load_skill",
    "list_skills",
    "validate_skill_graph",
    # Trigger
    "trigger_skill",
    # Executor
    "execute_skill",
    "execute_skill_continue",
    # Models
    "Skill",
    "SkillMetadata",
    "SkillNode",
    "ExecutionGraph",
    "SkillResult",
    "ApprovalRecord",
    "SkillExecutionContext",
    "NodeResult",
]
