"""Integration test for POST /api/skills/validate (#49 backend support).

The endpoint replaces the previous query-string version which the
frontend SkillEditor couldn't use. Body shape is now {yaml_content: str}
and the response carries the parsed graph for the DAG preview.
"""

from __future__ import annotations

# ----- pre-import patches -------------------------------------------------
import os
import pathlib

_ORIGINAL_MAKEDIRS = os.makedirs


def _safe_makedirs(path, *args, **kwargs):
    if isinstance(path, pathlib.Path):
        path = str(path)
    if str(path).startswith("/app"):
        return
    return _ORIGINAL_MAKEDIRS(path, *args, **kwargs)


os.makedirs = _safe_makedirs  # type: ignore[assignment]

from cryptography.fernet import Fernet  # noqa: E402

os.environ.setdefault("FERNET_KEY", Fernet.generate_key().decode())
# --------------------------------------------------------------------------

from collections.abc import Iterator  # noqa: E402

import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture
def client() -> Iterator[TestClient]:
    from backend.api.routes import skills

    app = FastAPI()
    app.include_router(skills.router)
    with TestClient(app) as c:
        yield c


VALID_YAML = """
name: test-skill
description: simple two-node DAG
execution_graph:
  nodes:
    - id: a
      agent: researcher
      goal: do A
    - id: b
      agent: cmo
      goal: do B
  edges:
    - from: a
      to: b
"""

CYCLE_YAML = """
name: cycle
execution_graph:
  nodes:
    - id: a
      agent: coo
    - id: b
      agent: cmo
  edges:
    - from: a
      to: b
    - from: b
      to: a
"""


class TestValidateEndpoint:
    def test_valid_yaml_returns_valid_true_with_graph(self, client: TestClient) -> None:
        resp = client.post("/api/skills/validate", json={"yaml_content": VALID_YAML})
        assert resp.status_code == 200
        body = resp.json()
        assert body["valid"] is True
        assert body["errors"] == []
        # Graph payload is suitable for the editor's DAG preview
        assert body["graph"] is not None
        assert {n["id"] for n in body["graph"]["nodes"]} == {"a", "b"}
        assert body["graph"]["edges"] == [{"from": "a", "to": "b"}]

    def test_cycle_returns_valid_false_with_error_AND_graph(
        self, client: TestClient
    ) -> None:
        """Even when invalid, the editor should be able to render whatever
        graph parsed out of the YAML so the user can spot the bad edge."""
        resp = client.post("/api/skills/validate", json={"yaml_content": CYCLE_YAML})
        body = resp.json()
        assert body["valid"] is False
        assert any("Cycle" in e for e in body["errors"])
        assert body["graph"] is not None
        assert len(body["graph"]["nodes"]) == 2

    def test_yaml_parse_error_is_caught(self, client: TestClient) -> None:
        resp = client.post(
            "/api/skills/validate", json={"yaml_content": "not: [valid: yaml"}
        )
        body = resp.json()
        assert body["valid"] is False
        assert any("parse error" in e.lower() for e in body["errors"])
        assert body["graph"] is None

    def test_non_mapping_yaml_is_rejected_clearly(self, client: TestClient) -> None:
        resp = client.post(
            "/api/skills/validate", json={"yaml_content": "- just\n- a\n- list"}
        )
        body = resp.json()
        assert body["valid"] is False
        assert any("mapping" in e.lower() for e in body["errors"])

    def test_missing_yaml_content_returns_422(self, client: TestClient) -> None:
        resp = client.post("/api/skills/validate", json={})
        assert resp.status_code == 422
