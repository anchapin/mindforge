"""Pydantic models for API requests/responses. From SPEC.md Section 4.2."""

from __future__ import annotations
from datetime import datetime
from enum import Enum
from typing import Any
from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DRAFT = "draft"
    APPROVED = "approved"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"


class TaskType(str, Enum):
    GITHUB = "github"
    EMAIL = "email"
    RESEARCH = "research"
    CONTENT = "content"
    FINANCE = "finance"
    ENGINEERING = "engineering"
    OPERATIONS = "operations"
    GENERAL = "general"


class AgentRole(str, Enum):
    COO = "coo"
    CMO = "cmo"
    RESEARCHER = "researcher"
    ENGINEER = "engineer"


class TaskContext(BaseModel):
    nodes_completed: list[str] = Field(default_factory=list)
    current_node: str | None = None
    draft_content: dict[str, Any] | None = None
    constraint: str | None = None
    error: str | None = None
    escalation_message: str | None = None
    approval_deadline_iso: str | None = None


class TaskStep(BaseModel):
    id: str
    task_id: str
    node_id: str
    agent_role: AgentRole
    step_order: int
    status: TaskStatus
    action_taken: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    approval_required: bool = False
    approval_status: str | None = None
    approval_edited_content: dict[str, Any] | None = None
    approved_at: datetime | None = None
    error: str | None = None
    retry_count: int = 0


class Task(BaseModel):
    id: str
    skill_id: str | None
    skill_version: int = 1
    status: TaskStatus
    task_type: TaskType
    project_id: str | None
    description: str
    context: TaskContext = Field(default_factory=TaskContext)
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    steps: list[TaskStep] = Field(default_factory=list)


class Integration(BaseModel):
    id: str
    app_name: str
    auth_token_enc: str
    refresh_token_enc: str | None = None
    token_key_id: str = "local"
    status: str
    permissions: list[str] = Field(default_factory=list)
    allowed_agents: list[str] = Field(default_factory=list)
    last_sync_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class SkillNode(BaseModel):
    id: str
    agent: AgentRole
    goal: str
    tools: list[str] = Field(default_factory=list)
    outcome_on_failure: str = "skip"
    retry: dict[str, Any] | None = None
    requires_approval: bool = False
    approval_timeout_minutes: int = 1440
    memory_layers: list[str] = Field(default_factory=list)
    output_schema: dict[str, Any] | None = None


class SkillEdge(BaseModel):
    from_node: str = Field(alias="from")
    to: str
    condition: str


class Skill(BaseModel):
    id: str
    name: str
    description: str
    category: str
    agent_role: AgentRole
    yaml_content: str
    version: int = 1
    tools: list[str] = Field(default_factory=list)
    memory_layers: list[str] = Field(default_factory=list)
    trigger_type: str
    trigger_keywords: list[str] | None = None
    trigger_intents: list[str] | None = None
    success_count: int = 0
    failure_count: int = 0
    last_run_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
