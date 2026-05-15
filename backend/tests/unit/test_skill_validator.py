"""Unit tests for the canonical validate_skill_graph (#45).

Two prior copies of this function disagreed on:
  - input shape (full skill vs. bare graph)
  - cycle detection (iterative DFS vs. recursive has_path that
    false-positived on diamond DAGs)

This test pins the consolidated behavior:
  - Both input shapes accepted
  - Diamond DAGs accepted (regression for the route's old false positive)
  - Linear DAGs accepted
  - Self-loops, cycles, missing nodes, orphan-approval all detected
"""

from __future__ import annotations

import pathlib

from backend.skills.validator import validate_skill_graph

# ---------------------------------------------------------------------------
# Single source of truth assertion
# ---------------------------------------------------------------------------


class TestSingleSourceOfTruth:
    def test_registry_re_exports_canonical_function(self):
        from backend.skills.registry import validate_skill_graph as via_registry

        assert via_registry is validate_skill_graph

    def test_route_re_exports_canonical_function(self):
        # Route module imports cause /app/data side-effects; isolate.
        import os

        os.environ.setdefault("DATA_DIR", "/tmp/mf-validator-test")
        os.makedirs("/tmp/mf-validator-test", exist_ok=True)

        from backend.api.routes.skills import validate_skill_graph as via_route

        assert via_route is validate_skill_graph

    def test_no_local_definition_in_registry(self):
        from backend.skills import registry as registry_mod

        source = pathlib.Path(registry_mod.__file__).read_text()
        # Imports from validator are fine; what's banned is a `def` that
        # shadows the canonical function.
        assert "def validate_skill_graph(" not in source, (
            "registry.py must not re-define validate_skill_graph; import from "
            "backend.skills.validator instead (#45)"
        )

    def test_no_local_definition_in_route(self):
        import os

        os.environ.setdefault("DATA_DIR", "/tmp/mf-validator-test")
        os.makedirs("/tmp/mf-validator-test", exist_ok=True)

        from backend.api.routes import skills as route_mod

        source = pathlib.Path(route_mod.__file__).read_text()
        assert "def validate_skill_graph(" not in source, (
            "routes/skills.py must not re-define validate_skill_graph; "
            "import from backend.skills.validator instead (#45)"
        )


# ---------------------------------------------------------------------------
# Shape adapter
# ---------------------------------------------------------------------------


class TestInputShapes:
    def test_accepts_full_skill_dict(self):
        full = {
            "name": "x",
            "execution_graph": {
                "nodes": [{"id": "a"}, {"id": "b"}],
                "edges": [{"from": "a", "to": "b"}],
            },
        }
        assert validate_skill_graph(full) == []

    def test_accepts_bare_graph_dict(self):
        bare = {
            "nodes": [{"id": "a"}, {"id": "b"}],
            "edges": [{"from": "a", "to": "b"}],
        }
        assert validate_skill_graph(bare) == []

    def test_empty_graph_flagged(self):
        errs = validate_skill_graph({"nodes": [], "edges": []})
        assert any("no nodes" in e for e in errs)


# ---------------------------------------------------------------------------
# Rule 1 — edges reference existing nodes
# ---------------------------------------------------------------------------


class TestRule1MissingNodes:
    def test_unknown_to_node_flagged(self):
        errs = validate_skill_graph(
            {
                "nodes": [{"id": "a"}],
                "edges": [{"from": "a", "to": "ghost"}],
            }
        )
        assert any("ghost" in e for e in errs)

    def test_unknown_from_node_flagged(self):
        errs = validate_skill_graph(
            {
                "nodes": [{"id": "a"}],
                "edges": [{"from": "ghost", "to": "a"}],
            }
        )
        assert any("ghost" in e for e in errs)


# ---------------------------------------------------------------------------
# Rule 2 — approval nodes have outgoing edges
# ---------------------------------------------------------------------------


class TestRule2ApprovalGate:
    def test_orphan_approval_flagged(self):
        errs = validate_skill_graph(
            {
                "nodes": [{"id": "draft", "requires_approval": True}],
                "edges": [],
            }
        )
        assert any("requires approval" in e for e in errs)

    def test_approval_with_outgoing_edge_passes(self):
        errs = validate_skill_graph(
            {
                "nodes": [
                    {"id": "draft", "requires_approval": True},
                    {"id": "send"},
                ],
                "edges": [{"from": "draft", "to": "send"}],
            }
        )
        assert errs == []


# ---------------------------------------------------------------------------
# Rule 3 — no cycles (the regression that motivated this consolidation)
# ---------------------------------------------------------------------------


class TestRule3Cycles:
    def test_self_loop_detected(self):
        errs = validate_skill_graph(
            {
                "nodes": [{"id": "a"}],
                "edges": [{"from": "a", "to": "a"}],
            }
        )
        assert any("Self-loop" in e for e in errs)

    def test_two_cycle_detected(self):
        errs = validate_skill_graph(
            {
                "nodes": [{"id": "a"}, {"id": "b"}],
                "edges": [
                    {"from": "a", "to": "b"},
                    {"from": "b", "to": "a"},
                ],
            }
        )
        assert any("Cycle" in e for e in errs)

    def test_three_cycle_detected(self):
        errs = validate_skill_graph(
            {
                "nodes": [{"id": "a"}, {"id": "b"}, {"id": "c"}],
                "edges": [
                    {"from": "a", "to": "b"},
                    {"from": "b", "to": "c"},
                    {"from": "c", "to": "a"},
                ],
            }
        )
        assert any("Cycle" in e for e in errs)

    def test_diamond_dag_passes(self):
        """Regression: the old route copy used recursive `has_path` that
        flagged any node revisit as a cycle, producing false positives on
        diamond shapes (two paths from `a` to `d` look like a "revisit"
        without proper on-stack tracking)."""
        errs = validate_skill_graph(
            {
                "nodes": [{"id": "a"}, {"id": "b"}, {"id": "c"}, {"id": "d"}],
                "edges": [
                    {"from": "a", "to": "b"},
                    {"from": "a", "to": "c"},
                    {"from": "b", "to": "d"},
                    {"from": "c", "to": "d"},
                ],
            }
        )
        assert errs == [], f"Diamond DAG must be valid; got: {errs}"

    def test_long_linear_chain_passes(self):
        nodes = [{"id": f"n{i}"} for i in range(50)]
        edges = [{"from": f"n{i}", "to": f"n{i + 1}"} for i in range(49)]
        assert validate_skill_graph({"nodes": nodes, "edges": edges}) == []
