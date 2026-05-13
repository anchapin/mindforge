"""Pydantic models for skills. From SPEC.md Section 2.3."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class TriggerType(str, Enum):
    KEYWORD = "keyword"
    INTENT_CLASSIFIER = "intent_classifier"
    EXPLICIT_ONLY = "explicit_only"


class SkillTrigger(BaseModel):
    type: TriggerType = TriggerType.KEYWORD
    keywords: list[str] | None = None
    intents: list[str] | None = None


class SkillNode(BaseModel):
    id: str
    agent: str
    goal: str
    tools: list[str] = Field(default_factory=list)
    outcome_on_failure: str = "skip"
    retry: dict[str, Any] | None = None
    requires_approval: bool = False
    approval_timeout_minutes: int = 1440
    memory_layers: list[str] = Field(default_factory=list)
    output_schema: dict[str, Any] | None = None


class ExecutionGraph(BaseModel):
    type: str = "directed_acyclic_graph"
    nodes: list[SkillNode] = Field(default_factory=list)
    # Edges stored as dicts to avoid Python reserved-word issues with 'from'
    edges: list[dict] = Field(default_factory=list)


class Skill(BaseModel):
    id: str
    name: str
    description: str
    category: str
    agent_role: str
    yaml_content: str
    version: int = 1
    tools: list[str] = Field(default_factory=list)
    memory_layers: list[str] = Field(default_factory=list)
    trigger_type: TriggerType = TriggerType.KEYWORD
    trigger_keywords: list[str] | None = None
    trigger_intents: list[str] | None = None
    success_count: int = 0
    failure_count: int = 0
    last_run_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    execution_graph: ExecutionGraph | None = None


class SkillMetadata(BaseModel):
    id: str
    name: str
    description: str
    category: str
    version: int
    tools: list[str]
    memory_layers: list[str]
    trigger_type: TriggerType
    trigger_keywords: list[str] | None = None
    trigger_intents: list[str] | None = None
    success_count: int = 0
    failure_count: int = 0
    last_run_at: datetime | None = None


class ApprovalRecord(BaseModel):
    node_id: str
    action: str  # "approved" | "rejected" | "timeout"
    edited_content: dict[str, Any] | None = None
    timestamp: datetime


class SkillResult(BaseModel):
    skill_id: str
    skill_version: int
    status: str  # "draft" | "approved" | "rejected" | "completed" | "failed" | "escalated"
    nodes_completed: list[str] = Field(default_factory=list)
    current_node: str | None = None
    draft_content: dict[str, Any] | None = None
    final_output: dict[str, Any] | None = None
    approval_history: list[ApprovalRecord] = Field(default_factory=list)
    escalation_message: str | None = None
    error: str | None = None
    started_at: datetime
    completed_at: datetime | None = None


class NodeResult(BaseModel):
    node_id: str
    status: str  # "success" | "failure" | "skipped" | "waiting_approval"
    output: dict[str, Any] | None = None
    error: str | None = None


class SkillExecutionContext(BaseModel):
    task_id: str
    skill: Skill
    node_id: str
    scratch: dict[str, Any] = Field(default_factory=dict)
    nodes_completed: list[str] = Field(default_factory=list)
    draft_content: dict[str, Any] | None = None
    approval_history: list[ApprovalRecord] = Field(default_factory=list)
    started_at: datetime
    error: str | None = None
