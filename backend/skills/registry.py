"""Skill registry — load, validate, and enumerate YAML skills.

From SPEC.md Section 3b.5.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

import yaml

from backend.skills.models import (
    ExecutionGraph,
    Skill,
    SkillMetadata,
    SkillNode,
    TriggerType,
)
from backend.skills.validator import validate_skill_graph

logger = logging.getLogger(__name__)

SKILLS_DIR = Path(__file__).parent / "skills"


class SkillRegistry:
    """In-memory registry of loaded, validated skills.

    Loads all .yaml files from the skills directory on startup.
    Validates at invocation time with caching: only re-validates if the YAML
    file's content (mtime + size) has changed since last validation (#105).
    """

    def __init__(self, skills_dir: Path | None = None) -> None:
        self._skills_dir = skills_dir or SKILLS_DIR
        self._skills: dict[str, Skill] = {}
        # Cache: skill_id -> (mtime, size, errors)
        self._validation_cache: dict[str, tuple[float, int, list[str] | None]] = {}

    def _file_fingerprint(self, path: Path) -> tuple[float, int]:
        """Return (mtime, size) for cache-busting — lightweight alternative to hashing."""
        try:
            st = path.stat()
            return (st.st_mtime, st.st_size)
        except OSError:
            return (0, 0)

    def _needs_validation(self, skill_id: str, path: Path) -> bool:
        """Return True if the file changed since last cached validation."""
        try:
            mtime, size = self._file_fingerprint(path)
            cached = self._validation_cache.get(skill_id)
            if cached is None:
                return True
            return cached[0] != mtime or cached[1] != size
        except Exception:
            return True

    def _get_cached_errors(self, skill_id: str) -> list[str] | None:
        """Return cached validation errors, or None if cache is stale."""
        return self._validation_cache.get(skill_id, (0, 0, None))[2]

    def _set_cached_validation(self, skill_id: str, path: Path, errors: list[str] | None) -> None:
        """Store validation result alongside file fingerprint."""
        try:
            mtime, size = self._file_fingerprint(path)
            self._validation_cache[skill_id] = (mtime, size, errors)
        except Exception:
            pass

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

    def _load_raw(self, path: Path) -> dict:
        """Load raw YAML content from a skill file.

        Raises ValueError if the file is empty or unreadable.
        """
        try:
            raw = yaml.safe_load(path.read_text())
        except Exception as exc:
            raise ValueError(f"failed to parse skill file {path.name}: {exc}") from exc
        if not raw:
            raise ValueError(f"empty skill file: {path.name}")
        return raw

    def validate_for_execution(self, skill_id: str) -> list[str]:
        """Lightweight invocation-time validation (cached).

        Only validates if the YAML file's content changed since last check.
        Returns a list of errors (empty = valid).
        """
        skill = self._skills.get(skill_id)
        if not skill:
            return [f"Skill '{skill_id}' not found in registry"]

        # Re-derive the expected path from skill id
        skill_yaml_path = self._skills_dir / f"{skill_id}.yaml"
        if not skill_yaml_path.exists():
            # Skill is loaded but YAML gone — treat as invalid rather than crashing
            return [f"Skill file for '{skill_id}' no longer exists on disk"]

        if not self._needs_validation(skill_id, skill_yaml_path):
            cached = self._get_cached_errors(skill_id)
            return cached if cached is not None else []

        # Validate and cache result
        raw = self._load_raw(skill_yaml_path)
        errors = validate_skill_graph(raw)
        self._set_cached_validation(skill_id, skill_yaml_path, errors if errors else None)
        return errors

    def load_skill_file(self, path: Path) -> Skill | None:
        """Load and validate a single skill YAML file.

        Raises ValueError if the skill is invalid.
        """
        raw = self._load_raw(path)

        errors = validate_skill_graph(raw)
        if errors:
            raise ValueError(f"invalid skill {path.name}: {'; '.join(errors)}")

        skill = self._parse_skill(raw, yaml_content=path.read_text())
        skill.execution_graph = self._parse_graph(raw.get("execution_graph", {}))
        self._skills[skill.id] = skill
        self._set_cached_validation(skill.id, path, None)
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
            self._invalidate_cache(skill_id)

    def increment_failure(self, skill_id: str) -> None:
        skill = self._skills.get(skill_id)
        if skill:
            skill.failure_count += 1
            skill.last_run_at = datetime.utcnow()
            self._invalidate_cache(skill_id)

    def _invalidate_cache(self, skill_id: str) -> None:
        """Clear the validation cache when a skill is updated."""
        self._validation_cache.pop(skill_id, None)


# Module-level singleton — populated on first import
_registry: SkillRegistry | None = None


def get_registry() -> SkillRegistry:
    global _registry
    if _registry is None:
        _registry = SkillRegistry()
        _registry.load_all()
    return _registry


__all__ = ['validate_skill_graph', 'get_registry', 'SkillRegistry', 'SKILLS_DIR']
