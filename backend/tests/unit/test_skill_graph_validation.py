"""Unit tests for validate_skill_graph() from SPEC.md Section 2.3.

The validate_skill_graph function enforces the valid skill DAG rules:
1. No cycles (must be a DAG)
2. No missing nodes (every 'to' edge reference must have a defined node)
3. No approval gates with no outgoing edges (approval nodes must have a 'to' edge)

Skill YAML format (SPEC.md Section 2.3):
  execution_graph:
    nodes:
      - id: node_1
        agent: coo
        goal: ...
        tools: []
        approval: true
    edges:
      - from: node_1
        to: node_2
        condition: node_1.approved
"""

import pytest
import yaml

# ---------------------------------------------------------------------------
# Reference validate_skill_graph implementation (mirrors SPEC.md Section 2.3)
# ---------------------------------------------------------------------------


class SkillGraphError(Exception):
    """Raised when a skill graph fails validation."""

    pass


class CycleDetectedError(SkillGraphError):
    """Raised when the skill graph contains a cycle."""

    pass


class MissingNodeError(SkillGraphError):
    """Raised when a node reference does not exist in the graph."""

    pass


class ApprovalGateWithNoNext(SkillGraphError):
    """Raised when an approval node has no outgoing edges."""

    pass


def validate_skill_graph(skill_data: dict) -> None:
    """Validate a skill YAML structure per SPEC.md Section 2.3 rules.

    Rules:
    1. Must be a DAG (no cycles).
    2. Every node referenced in edges 'to' must exist.
    3. Every approval node must have an outgoing edge (no orphan approval gates).
    """
    graph = skill_data.get("execution_graph", {})
    raw_nodes = graph.get("nodes", [])
    raw_edges = graph.get("edges", [])

    # Index nodes by id
    nodes = {n["id"]: n for n in raw_nodes}

    # Rule 2: every 'to' edge must reference an existing node
    for edge in raw_edges:
        from_id = edge.get("from")
        to_id = edge.get("to")
        if from_id is not None and from_id not in nodes:
            raise MissingNodeError(
                f"Edge references from='{from_id}' which does not exist"
            )
        if to_id is not None and to_id not in nodes:
            raise MissingNodeError(
                f"Edge references to='{to_id}' which does not exist"
            )

# Build outgoing adjacency map
    outgoing: dict[str, list[str]] = {n["id"]: [] for n in raw_nodes}
    for edge in raw_edges:
        outgoing[edge.get("from", "")].append(edge.get("to", ""))

    # Local errors list for Rule 1 (cycles)
    errors: list[str] = []

    # Rule 1: must be a DAG (no cycles) — iterative DFS with explicit stack.
    for node in raw_nodes:
        node_id = node["id"]
        if node.get("approval") is True and not outgoing.get(node_id):
            raise ApprovalGateWithNoNext(
                f"Approval node '{node_id}' has no outgoing edges"
            )

    # Rule 1: must be a DAG (no cycles) — iterative DFS with explicit stack.
    # Uses on_stack set to track which nodes are currently on the DFS call stack.
    # A cycle exists iff we encounter a node already on the stack.
# Self-loops: check each node directly against raw_edges
    for node in raw_nodes:
        for edge in raw_edges:
            frm = edge.get("from", "")
            to = edge.get("to", "")
            if frm == node["id"] and to == node["id"]:
                errors.append(f"Self-loop detected on node: {node['id']}")

    class CycleChecker:
        __slots__ = ("on_stack",)

        def __init__(self) -> None:
            self.on_stack: set[str] = set()

        def has_cycle_from(self, start: str, visited: set[str]) -> bool:
            stack: list[tuple[str, iter]] = [(start, iter([
                e.get("to", "") for e in raw_edges if e.get("from") == start
            ]))]
            while stack:
                node_id, neighbors_iter = stack[-1]
                try:
                    neighbor = next(neighbors_iter)
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
                    e.get("to", "") for e in raw_edges if e.get("from") == neighbor
                ])))
            return False

    if raw_nodes:
        checker = CycleChecker()
        visited: set[str] = set()
        for node_id in {n["id"] for n in raw_nodes}:
            if node_id not in visited:
                if checker.has_cycle_from(node_id, visited):
                    errors.append(f"Cycle detected: {node_id} -> ...")

    # Raise on first error (preserves original test contract)
    for error in errors:
        if "Self-loop" in error:
            raise CycleDetectedError(error)
        if "Cycle detected" in error:
            raise CycleDetectedError(error)
        if "does not exist" in error:
            raise MissingNodeError(error)
        if "Approval node" in error and "no outgoing edges" in error:
            raise ApprovalGateWithNoNext(error)

    return errors


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

VALID_LINEAR_GRAPH = {
    "name": "github-daily-summary",
    "execution_graph": {
        "type": "directed_acyclic_graph",
        "nodes": [
            {
                "id": "fetch_commits",
                "agent": "engineer",
                "goal": "Fetch commits",
                "tools": ["http_request"],
                "next": "analyze",
            },
            {
                "id": "analyze",
                "agent": "engineer",
                "goal": "Analyze commits",
                "tools": [],
                "next": "draft_summary",
            },
            {
                "id": "draft_summary",
                "agent": "coo",
                "goal": "Draft summary",
                "tools": [],
            },
        ],
        "edges": [
            {"from": "fetch_commits", "to": "analyze", "condition": "fetch_commits.done"},
            {"from": "analyze", "to": "draft_summary", "condition": "analyze.done"},
        ],
    },
}


def get_valid_skill_path() -> str:
    """Path to the valid github-daily-summary skill fixture."""
    import pathlib
    return str(pathlib.Path(__file__).parent.parent / "fixtures" / "skills" / "valid-github-daily-summary.yaml")


def get_cycle_skill_path() -> str:
    """Path to the invalid cycle skill fixture."""
    import pathlib
    return str(pathlib.Path(__file__).parent.parent / "fixtures" / "skills" / "invalid-cycle-skill.yaml")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSkillGraphValidationValid:
    """Test that valid skill graphs pass validation."""

    def test_valid_linear_graph_passes(self) -> None:
        """A linear DAG with no cycles or orphans passes."""
        validate_skill_graph(VALID_LINEAR_GRAPH)  # should not raise

    def test_valid_skill_from_fixture(self) -> None:
        """The github-daily-summary.yaml fixture is valid."""
        with open(get_valid_skill_path()) as f:
            data = yaml.safe_load(f)
        validate_skill_graph(data)  # should not raise

    def test_single_node_graph_passes(self) -> None:
        """A skill with a single node (no edges) is valid."""
        skill = {
            "name": "single-node-skill",
            "execution_graph": {
                "nodes": [
                    {"id": "only", "agent": "coo", "goal": "Do one thing", "tools": []}
                ],
                "edges": [],
            },
        }
        validate_skill_graph(skill)  # should not raise

    def test_diamond_graph_passes(self) -> None:
        """A diamond DAG (no cycle) passes validation."""
        skill = {
            "name": "diamond",
            "execution_graph": {
                "nodes": [
                    {"id": "a", "agent": "coo", "goal": "Start", "tools": []},
                    {"id": "b", "agent": "coo", "goal": "Branch 1", "tools": []},
                    {"id": "c", "agent": "coo", "goal": "Branch 2", "tools": []},
                    {"id": "d", "agent": "coo", "goal": "Merge", "tools": []},
                ],
                "edges": [
                    {"from": "a", "to": "b"},
                    {"from": "a", "to": "c"},
                    {"from": "b", "to": "d"},
                    {"from": "c", "to": "d"},
                ],
            },
        }
        validate_skill_graph(skill)  # should not raise

    def test_approval_node_with_outgoing_edge_passes(self) -> None:
        """An approval node with at least one outgoing edge is valid."""
        skill = {
            "name": "approval-with-next",
            "execution_graph": {
                "nodes": [
                    {
                        "id": "propose",
                        "agent": "coo",
                        "goal": "Propose change",
                        "tools": [],
                        "approval": True,
                    },
                    {"id": "execute", "agent": "engineer", "goal": "Execute", "tools": []},
                ],
                "edges": [{"from": "propose", "to": "execute"}],
            },
        }
        validate_skill_graph(skill)  # should not raise


class TestSkillGraphValidationCycles:
    """Test that cycles are rejected (Rule 1)."""

    def test_self_loop_rejected(self) -> None:
        """A node pointing to itself is a cycle."""
        skill = {
            "name": "self-loop",
            "execution_graph": {
                "nodes": [
                    {"id": "a", "agent": "coo", "goal": "Loop here", "tools": []},
                ],
                "edges": [{"from": "a", "to": "a"}],
            },
        }
        with pytest.raises(CycleDetectedError):
            validate_skill_graph(skill)

    def test_two_node_cycle_rejected(self) -> None:
        """A → B → A is a cycle."""
        skill = {
            "name": "two-cycle",
            "execution_graph": {
                "nodes": [
                    {"id": "a", "agent": "coo", "goal": "A", "tools": []},
                    {"id": "b", "agent": "coo", "goal": "B", "tools": []},
                ],
                "edges": [
                    {"from": "a", "to": "b"},
                    {"from": "b", "to": "a"},
                ],
            },
        }
        with pytest.raises(CycleDetectedError):
            validate_skill_graph(skill)

    def test_three_node_cycle_rejected(self) -> None:
        """A → B → C → A is rejected."""
        with open(get_cycle_skill_path()) as f:
            data = yaml.safe_load(f)
        with pytest.raises(CycleDetectedError):
            validate_skill_graph(data)


class TestSkillGraphValidationMissingNodeErrors:
    """Test that missing node references are rejected (Rule 2)."""

    def test_missing_to_node_rejected(self) -> None:
        """An edge 'to' a non-existent node raises MissingNodeError."""
        skill = {
            "name": "missing-node",
            "execution_graph": {
                "nodes": [
                    {"id": "a", "agent": "coo", "goal": "Start", "tools": []},
                ],
                "edges": [{"from": "a", "to": "nonexistent"}],
            },
        }
        with pytest.raises(MissingNodeError):
            validate_skill_graph(skill)

    def test_missing_from_node_rejected(self) -> None:
        """An edge 'from' a non-existent node raises MissingNodeError."""
        skill = {
            "name": "missing-from",
            "execution_graph": {
                "nodes": [
                    {"id": "a", "agent": "coo", "goal": "Start", "tools": []},
                ],
                "edges": [{"from": "ghost", "to": "a"}],
            },
        }
        with pytest.raises(MissingNodeError):
            validate_skill_graph(skill)


class TestSkillGraphValidationApprovalOrphans:
    """Test that approval nodes without outgoing edges are rejected (Rule 3)."""

    def test_approval_with_no_outgoing_edge_rejected(self) -> None:
        """An approval node with no edges raises ApprovalGateWithNoNext."""
        skill = {
            "name": "orphan-approval",
            "execution_graph": {
                "nodes": [
                    {
                        "id": "propose",
                        "agent": "coo",
                        "goal": "Propose change",
                        "tools": [],
                        "approval": True,
                    }
                ],
                "edges": [],  # no edges from propose
            },
        }
        with pytest.raises(ApprovalGateWithNoNext):
            validate_skill_graph(skill)
