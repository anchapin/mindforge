"""Pytest fixtures for MindForge backend tests.

This module provides shared fixtures for unit and integration tests.
See SPEC.md Section 5.6.2 for the full test stack documentation.
"""

import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def pglite_test_db(tmp_path: Path) -> MagicMock:  # type: ignore[misc,return-value]
    """Isolated PGLite DB for each test.

    Creates a temporary SQLite database and initializes the schema.
    Yields a mock connection for unit tests.
    """
    import sqlite3

    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    schema = Path(__file__).parent.parent / "db" / "schema.sql"
    if schema.exists():
        conn.executescript(schema.read_text())
    yield conn
    conn.close()


@pytest.fixture
def chroma_tmp_dir(tmp_path: Path) -> str:
    """Isolated ChromaDB directory for each test."""
    d = tmp_path / "chroma"
    d.mkdir()
    return str(d)


@pytest.fixture
def mock_openrouter():
    """Pretend OpenRouter that returns fixed responses for routing tests."""
    with patch("openrouter.chat.completions.create") as mock:
        mock.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="engineer"))]
        )
        yield mock


@pytest.fixture
def skill_yaml_valid() -> str:
    """Path to a valid skill YAML for positive tests."""
    path = (
        Path(__file__).parent / "fixtures" / "skills" / "valid-github-daily-summary.yaml"
    )
    return path.read_text()


@pytest.fixture
def skill_yaml_with_cycle() -> str:
    """Path to a skill YAML containing a cycle for negative tests."""
    path = Path(__file__).parent / "fixtures" / "skills" / "invalid-cycle-skill.yaml"
    return path.read_text()


@pytest.fixture
def valid_skill_data() -> dict:
    """Valid skill data dict for graph validation tests."""
    return {
        "version": "1",
        "name": "test-skill",
        "description": "A test skill for unit testing",
        "category": "testing",
        "trigger": {"type": "keyword", "keywords": ["test"]},
        "execution_graph": {
            "type": "directed_acyclic_graph",
            "nodes": [
                {
                    "id": "start",
                    "agent": "engineer",
                    "goal": "Start the task",
                    "tools": [],
                    "outcome_on_failure": "skip_to_approve",
                },
                {
                    "id": "end",
                    "agent": "coo",
                    "goal": "End the task",
                    "tools": [],
                },
            ],
            "edges": [
                {"from": "start", "to": "end", "condition": "start.success"},
            ],
        },
        "memory_layers": ["semantic", "episodic"],
    }


@pytest.fixture
def skill_with_cycle_data() -> dict:
    """Skill data containing a cycle for negative tests."""
    return {
        "version": "1",
        "name": "cycle-skill",
        "description": "A skill with a cycle in its graph",
        "category": "testing",
        "trigger": {"type": "keyword", "keywords": ["cycle"]},
        "execution_graph": {
            "type": "directed_acyclic_graph",
            "nodes": [
                {"id": "a", "agent": "coo", "goal": "Node A", "tools": []},
                {"id": "b", "agent": "cmo", "goal": "Node B", "tools": []},
                {"id": "c", "agent": "researcher", "goal": "Node C", "tools": []},
            ],
            "edges": [
                {"from": "a", "to": "b", "condition": "a.done"},
                {"from": "b", "to": "c", "condition": "b.done"},
                {"from": "c", "to": "a", "condition": "c.done"},  # cycle!
            ],
        },
        "memory_layers": [],
    }


@pytest.fixture
def skill_missing_node_data() -> dict:
    """Skill data where an edge references a non-existent node."""
    return {
        "version": "1",
        "name": "missing-node-skill",
        "description": "A skill with missing node reference",
        "category": "testing",
        "trigger": {"type": "keyword", "keywords": ["missing"]},
        "execution_graph": {
            "type": "directed_acyclic_graph",
            "nodes": [
                {"id": "start", "agent": "coo", "goal": "Start", "tools": []},
            ],
            "edges": [
                {"from": "start", "to": "nonexistent", "condition": "start.done"},
            ],
        },
        "memory_layers": [],
    }


@pytest.fixture
def skill_approval_no_outgoing_data() -> dict:
    """Skill where a node requires approval but has no outgoing edges."""
    return {
        "version": "1",
        "name": "orphan-approval-skill",
        "description": "A skill with approval node lacking outgoing edges",
        "category": "testing",
        "trigger": {"type": "keyword", "keywords": ["orphan"]},
        "execution_graph": {
            "type": "directed_acyclic_graph",
            "nodes": [
                {
                    "id": "draft",
                    "agent": "cmo",
                    "goal": "Draft something",
                    "tools": [],
                    "requires_approval": True,
                },
            ],
            "edges": [],
        },
        "memory_layers": [],
    }
