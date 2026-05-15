"""Single source of truth for skill execution-graph validation (#45).

Replaces two divergent copies that previously lived in:
  - backend/skills/registry.py     (input shape: {execution_graph: {nodes, edges}})
  - backend/api/routes/skills.py   (input shape: {nodes, edges})

The two implementations also disagreed on cycle detection: the registry
used iterative DFS with an `on_stack` set (correct), while the route used
a recursive `has_path` that flagged any revisit as a cycle, producing
false positives on diamond-shaped DAGs. This module ports the registry's
logic and supports both input shapes via a single parameter.

Validation rules (SPEC.md Section 2.3):
  1. Every edge references an existing node (both `from` and `to`).
  2. Every node with `requires_approval` has at least one outgoing edge.
  3. The graph contains no cycles (no node is its own ancestor).
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any


def _extract_graph(skill_def: dict[str, Any]) -> tuple[list[dict], list[dict]]:
    """Pull (nodes, edges) from a skill_def regardless of which shape it uses.

    Accepts:
      - Full skill: {"execution_graph": {"nodes": [...], "edges": [...]}}
      - Bare graph: {"nodes": [...], "edges": [...]}

    The bare-graph case is what the POST /api/skills route receives; the
    full-skill case is what the registry loader sees from a YAML file.
    """
    if "execution_graph" in skill_def and isinstance(
        skill_def.get("execution_graph"), dict
    ):
        graph = skill_def["execution_graph"]
    else:
        graph = skill_def
    return graph.get("nodes", []) or [], graph.get("edges", []) or []


def _detect_cycles(
    nodes: list[dict], edges: list[dict], errors: list[str]
) -> None:
    """Iterative DFS cycle detection with on_stack set.

    A cycle exists iff a node is reachable from itself via directed edges.
    Self-loops are checked explicitly first (they're a degenerate cycle).
    """
    # Self-loops
    for node in nodes:
        node_id = node["id"]
        for edge in edges:
            if edge.get("from") == node_id and edge.get("to") == node_id:
                errors.append(f"Self-loop detected on node: {node_id}")

    # Build adjacency lookup once
    adjacency: dict[str, list[str]] = {n["id"]: [] for n in nodes}
    for edge in edges:
        frm = edge.get("from")
        to = edge.get("to")
        if frm in adjacency and to is not None:
            adjacency[frm].append(to)

    visited: set[str] = set()
    for start_node in nodes:
        start = start_node["id"]
        if start in visited:
            continue
        on_stack: set[str] = set()
        stack: list[tuple[str, Iterator[str]]] = [(start, iter(adjacency.get(start, [])))]
        on_stack.add(start)
        visited.add(start)
        while stack:
            node_id, neighbors = stack[-1]
            try:
                neighbor = next(neighbors)
            except StopIteration:
                stack.pop()
                on_stack.discard(node_id)
                continue
            if neighbor in on_stack:
                errors.append(f"Cycle detected via edge {node_id} -> {neighbor}")
                # Don't break — surface any other cycles too, but skip this branch
                continue
            if neighbor in visited:
                continue
            visited.add(neighbor)
            on_stack.add(neighbor)
            stack.append((neighbor, iter(adjacency.get(neighbor, []))))


def validate_skill_graph(skill_def: dict[str, Any]) -> list[str]:
    """Validate a skill execution graph.

    Args:
        skill_def: Either a full skill dict (containing `execution_graph`)
            or a bare graph dict (containing `nodes`/`edges`). Both shapes
            are accepted so this function works for both the YAML-load path
            (registry) and the API-create path (route).

    Returns:
        A list of human-readable error strings. Empty list = valid.
    """
    errors: list[str] = []
    nodes, edges = _extract_graph(skill_def)

    if not nodes:
        # An empty graph is technically vacuous; flag it so the user notices
        # rather than letting an empty skill silently load.
        errors.append("Skill execution graph contains no nodes")
        return errors

    node_ids = {n["id"] for n in nodes}

    # Rule 1: edges reference existing nodes
    for edge in edges:
        from_id = edge.get("from")
        to_id = edge.get("to")
        if from_id not in node_ids:
            errors.append(f"Edge references missing node: {from_id}")
        if to_id not in node_ids:
            errors.append(f"Edge references missing node: {to_id}")

    # Rule 2: approval nodes have outgoing edges
    outgoing: dict[str, list[dict]] = {n["id"]: [] for n in nodes}
    for edge in edges:
        from_id = edge.get("from")
        if from_id in outgoing:
            outgoing[from_id].append(edge)

    for node in nodes:
        if node.get("requires_approval") and not outgoing.get(node["id"]):
            errors.append(
                f"Node '{node['id']}' requires approval but has no outgoing edges"
            )

    # Rule 3: no cycles
    _detect_cycles(nodes, edges, errors)

    return errors


__all__ = ["validate_skill_graph"]
