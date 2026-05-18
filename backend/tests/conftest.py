"""Pytest fixtures for MindForge backend tests.

This module provides shared fixtures for unit and integration tests.
See SPEC.md Section 5.6.2 for the full test stack documentation.
"""

import asyncio
import gc
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def _strip_inline_comments(text: str) -> str:
    """Remove inline -- comments from SQL text, preserving string literals."""
    lines = []
    for line in text.splitlines():
        idx = line.find("--")
        if idx >= 0:
            line = line[:idx]
        if line.strip():
            lines.append(line.rstrip())
    return "\n".join(lines)


def _fix_default_func(sql: str) -> str:
    """Wrap bare DEFAULT <func>() expressions in parens for sqlite3 compatibility.

    Python's sqlite3 module cannot parse bare function expressions in DEFAULT
    clauses (e.g. ``DEFAULT lower(hex(randomblob(16)))``) — the tokenizer
    rejects them as "near \"(\": syntax error". This function wraps those
    bare function defaults in parentheses without modifying schema.sql.

    String literals (e.g. DEFAULT 'foo') are unaffected.
    """
    import re
    return re.sub(
        r"(?i)\bDEFAULT\s+lower\(hex\(randomblob\((\d+)\)\)\)",
        r"DEFAULT (lower(hex(randomblob(\1))))",
        sql,
    )


@pytest.fixture
def pglite_test_db(tmp_path: Path):
    """Isolated PGLite DB for each test.

    Creates a temporary SQLite database and initializes the schema.
    Yields a real sqlite3.Connection so tests can query it directly.

    Note: schema.sql uses bare DEFAULT expressions for generated IDs
    (e.g. ``DEFAULT lower(hex(randomblob(16)))``). Python's sqlite3 module
    cannot parse bare function expressions in DEFAULT clauses — the tokenizer
    rejects them as "near \"(\": syntax error". We fix this by wrapping bare
    DEFAULT function expressions in parentheses before execution, without
    modifying schema.sql on disk. String literals ('foo') are unaffected.
    """
    import sqlite3

    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    schema = Path(__file__).parent.parent / "db" / "schema.sql"
    if schema.exists():
        clean = _strip_inline_comments(schema.read_text())
        for stmt in clean.split(";"):
            stmt = stmt.strip()
            if not stmt:
                continue
            conn.execute(_fix_default_func(stmt))
        conn.commit()
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
        mock.return_value = MagicMock(choices=[MagicMock(message=MagicMock(content="engineer"))])
        yield mock


@pytest.fixture
def skill_yaml_valid() -> str:
    """Path to a valid skill YAML for positive tests."""
    path = Path(__file__).parent / "fixtures" / "skills" / "valid-github-daily-summary.yaml"
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


@pytest.fixture(scope="session", autouse=True)
def close_event_loops():
    """Close any lingering event loops after the test session.

    pytest-asyncio can leave event loops in a state that prevents proper
    process exit in CI environments. This fixture ensures cleanup happens
    after all tests complete.
    """
    yield
    gc.collect()
    for loop in list(asyncio.all_loops()):
        if not loop.is_closed():
            try:
                loop.run_until_complete(loop.shutdown_asyncgens())
            except Exception:
                pass
            try:
                loop.close()
            except Exception:
                pass
