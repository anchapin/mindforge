"""Skill registry — load, validate, and enumerate YAML skills.

From SPEC.md Section 3b.5.
"""

from __future__ import annotations

import logging
from datetime import datetime
from itertools import chain
from pathlib import Path
from typing import Iterator

import yaml

from backend.skills.models import (
    ExecutionGraph,
    Skill,
    SkillMetadata,
    SkillNode,
    TriggerType,
)

logger = logging.getLogger(__name__)

SKILLS_DIR = Path(__file__).parent / "skills"


def validate_skill_graph(skill_def: dict) -> list[str]:
    """Validate a skill execution graph.

    Returns a list of error messages. Empty list means valid.
    Rules (SPEC.md Section 2.3):
    1. Every edge references an existing node (both 'from' and 'to')
    2. Every node with requires_approval has at least one outgoing edge
    3. No node is its own ancestor (no cycles reachable from start)
    """
    errors: list[str] = []
    nodes = skill_def.get("execution_graph", {}).get("nodes", [])
    edges = skill_def.get("execution_graph", {}).get("edges", [])

    node_ids = {n["id"] for n in nodes}
    outgoing: dict[str, list[str]] = {n["id"]: [] for n in nodes}

    # Rule 1: every edge references an existing node
    for edge in edges:
        from_id = edge.get("from")
        to_id = edge.get("to")
        if from_id not in node_ids:
            errors.append(f"Edge references missing node: {from_id}")
        if to_id not in node_ids:
            errors.append(f"Edge references missing node: {to_id}")
        if from_id in outgoing:
            outgoing[from_id].append(edge.get("condition", ""))

    # Rule 2: every approval node has at least one outgoing edge
    for node in nodes:
        if node.get("requires_approval"):
            if not outgoing.get(node["id"]):
                errors.append(
                    f"Node '{node['id']}' requires approval but has no outgoing edges"
                )

    # Rule 3: no cycles
    # A cycle exists iff a node is reachable from itself via directed edges.
    # We detect this with iterative DFS using an on_stack set:
    # a cycle = encountering a node already on the current DFS stack.
    # Self-loops are checked explicitly first.
    for node in nodes:
        for edge in edges:
            frm = edge.get("from", "")
            to = edge.get("to", "")
            if frm == node["id"] and to == node["id"]:
                errors.append(f"Self-loop detected on node: {node['id']}")

    class CycleChecker:
        __slots__ = ("on_stack",)

        def __init__(self) -> None:
            self.on_stack: set[str] = set()

        def has_cycle_from(self, start: str, visited: set[str]) -> bool:
            stack: list[tuple[str, Iterator[str]]] = [(start, iter([
                e.get("to", "") for e in edges if e.get("from") == start
            ]))]
            while stack:
                node_id, neighbors_iter = stack[-1]
                try:
                    neighbor: str = next(neighbors_iter)
                except StopIteration:
                    stack.pop()
                    self.on_stack.discard(node_id)
                    continue
                if neighbor in self.on_stack:
                    return True
                if neighbor in visited:
                    continue
                visited.add(neighbor)
                self.on_stack.add(neighbor)
                stack.append((neighbor, iter([
                    e.get("to", "") for e in edges if e.get("from") == neighbor
                ])))
            return False

    if nodes:
        checker = CycleChecker()
        visited: set[str] = set()
        for node_id in {n["id"] for n in nodes}:
            if node_id not in visited:
                if checker.has_cycle_from(node_id, visited):
                    errors.append(f"Cycle detected: {node_id} -> ...")

    return errors


class SkillRegistry:
    """In-memory registry of loaded, validated skills.

    Loads all .yaml files from the skills directory on startup.
    """

    def __init__(self, skills_dir: Path | None = None) -> None:
        self._skills_dir = skills_dir or SKILLS_DIR
        self._skills: dict[str, Skill] = {}

    def load_all(self) -> None:
        """Scan skills_dir and load every .yaml file."""
        if not self._skills_dir.exists():
            logger.warning("skills directory does not exist: %s", self._skills_dir)
            return

        for path in sorted(self._skills_dir.glob("*.yaml")):
            try:
                self.load_skill_file(path)
            except Exception as exc:  # pragma: no cover
                logger.error("failed to load skill %s: %s", path.name, exc)

    def load_skill_file(self, path: Path) -> Skill | None:
        """Load and validate a single skill YAML file.

        Raises ValueError if the skill is invalid.
        """
        raw = yaml.safe_load(path.read_text())
        if not raw:
            raise ValueError(f"empty skill file: {path.name}")

        errors = validate_skill_graph(raw)
        if errors:
            raise ValueError(f"invalid skill {path.name}: {'; '.join(errors)}")

        skill = self._parse_skill(raw, yaml_content=path.read_text())
        skill.execution_graph = self._parse_graph(raw.get("execution_graph", {}))
        self._skills[skill.id] = skill
        logger.info("loaded skill: %s v%d", skill.id, skill.version)
        return skill

    def _parse_skill(self, raw: dict, yaml_content: str) -> Skill:
        """Parse raw YAML dict into a Skill model."""
        trigger_raw = raw.get("trigger", {})
        if isinstance(trigger_raw, dict):
            trigger_type = TriggerType(trigger_raw.get("type", "keyword"))
            trigger_keywords = trigger_raw.get("keywords")
            trigger_intents = trigger_raw.get("intents")
        else:
            trigger_type = TriggerType.KEYWORD
            trigger_keywords = None
            trigger_intents = None

        return Skill(
            id=raw.get("name", "").replace(" ", "-").lower(),
            name=raw.get("name", ""),
            description=raw.get("description", ""),
            category=raw.get("category", "general"),
            agent_role=raw.get("agent_role", "coo"),
            yaml_content=yaml_content,
            version=int(raw.get("version", 1)),
            tools=raw.get("tools", []),
            memory_layers=raw.get("memory_layers", []),
            trigger_type=trigger_type,
            trigger_keywords=trigger_keywords,
            trigger_intents=trigger_intents,
            success_count=0,
            failure_count=0,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )

    def _parse_graph(self, graph_raw: dict) -> ExecutionGraph:
        """Parse execution_graph section into model objects."""
        nodes = [
            SkillNode(
                id=n["id"],
                agent=n.get("agent", "coo"),
                goal=n.get("goal", ""),
                tools=n.get("tools", []),
                outcome_on_failure=n.get("outcome_on_failure", "skip"),
                retry=n.get("retry"),
                requires_approval=n.get("requires_approval", False),
                approval_timeout_minutes=n.get("approval_timeout_minutes", 1440),
                memory_layers=n.get("memory_layers", []),
                output_schema=n.get("output_schema"),
            )
            for n in graph_raw.get("nodes", [])
        ]

        # Edges are stored as raw dicts to avoid Python keyword issues with 'from'
        edges = [
            {"from": e.get("from", ""), "to": e.get("to", ""), "condition": e.get("condition", "")}
            for e in graph_raw.get("edges", [])
        ]

        return ExecutionGraph(
            type=graph_raw.get("type", "directed_acyclic_graph"),
            nodes=nodes,
            edges=edges,
        )

    def get(self, skill_id: str) -> Skill | None:
        """Get a skill by ID, or None if not found."""
        return self._skills.get(skill_id)

    def list(self) -> list[SkillMetadata]:
        """Return metadata for all loaded skills."""
        return [
            SkillMetadata(
                id=s.id,
                name=s.name,
                description=s.description,
                category=s.category,
                version=s.version,
                tools=s.tools,
                memory_layers=s.memory_layers,
                trigger_type=s.trigger_type,
                trigger_keywords=s.trigger_keywords,
                trigger_intents=s.trigger_intents,
                success_count=s.success_count,
                failure_count=s.failure_count,
                last_run_at=s.last_run_at,
            )
            for s in self._skills.values()
        ]

    def find_by_keyword(self, text: str) -> Skill | None:
        """Find first skill whose trigger.keywords match the text."""
        text_lower = text.lower()
        for skill in self._skills.values():
            if skill.trigger_type == TriggerType.KEYWORD and skill.trigger_keywords:
                if any(kw in text_lower for kw in skill.trigger_keywords):
                    return skill
        return None

    def find_by_name(self, text: str) -> Skill | None:
        """Find a skill by explicit invocation (name match)."""
        text_lower = text.lower()
        for skill in self._skills.values():
            if skill.name.lower() in text_lower or skill.id in text_lower:
                return skill
        return None

    def find_by_intent(self, intent: str) -> Skill | None:
        """Find a skill by intent label match."""
        intent_lower = intent.lower()
        for skill in self._skills.values():
            if skill.trigger_intents:
                if intent_lower in [i.lower() for i in skill.trigger_intents]:
                    return skill
        return None

    def increment_success(self, skill_id: str) -> None:
        skill = self._skills.get(skill_id)
        if skill:
            skill.success_count += 1
            skill.last_run_at = datetime.utcnow()

    def increment_failure(self, skill_id: str) -> None:
        skill = self._skills.get(skill_id)
        if skill:
            skill.failure_count += 1
            skill.last_run_at = datetime.utcnow()


# Module-level singleton — populated on first import
_registry: SkillRegistry | None = None


def get_registry() -> SkillRegistry:
    global _registry
    if _registry is None:
        _registry = SkillRegistry()
        _registry.load_all()
    return _registry
