import os
import shutil
import tempfile
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

# Create a temporary directory for DATA_DIR and set env before importing app
test_data_dir = tempfile.mkdtemp()
os.environ["DATA_DIR"] = test_data_dir
os.environ["MINDFORGE_VERSION"] = "0.1.0-test"

from backend.main import app  # noqa: E402


def teardown_module(module):
    shutil.rmtree(test_data_dir)

def test_startup_llm_router_fatal():
    """Test that LLM router failure stops startup (Fatal)."""
    with (
        patch("backend.main.LLM_ROUTER.initialize", side_effect=Exception("LLM failure")),
        patch("backend.main.logger") as mock_logger,
        pytest.raises(Exception) as excinfo,
        TestClient(app),
    ):
        pass
    assert "LLM failure" in str(excinfo.value)
    # Find the critical call
    critical_calls = [call for call in mock_logger.critical.call_args_list if call.args[0] == "llm_router_init_failed"]
    assert len(critical_calls) == 1
    assert critical_calls[0].kwargs.get("exc_info") is True

def test_startup_chroma_recoverable():
    """Test that ChromaDB failure is recoverable and results in degraded status."""
    with (
        patch("backend.db.check_chroma", new_callable=AsyncMock) as mock_check,
        patch("backend.main.LLM_ROUTER.initialize", new_callable=AsyncMock),
        patch("backend.main.register_all_tools"),
        patch("backend.main.TemporalClient") as mock_temporal_cls,
    ):
        mock_check.return_value = False
        mock_temporal = mock_temporal_cls.return_value
        mock_temporal.start = AsyncMock()
        mock_temporal.shutdown = AsyncMock()
        with (
            patch("backend.main.run_migrations"),
            patch("backend.main.logger") as mock_logger,
            TestClient(app) as client,
        ):
            # App should start
            resp = client.get("/health/detail")
            assert resp.status_code == 200
            data = resp.json()
            assert data["components"]["chroma"] == "failed"
            assert data["status"] == "degraded"

        # Check if chroma_check_failed or chroma_init_failed was logged
        warning_names = [call.args[0] for call in mock_logger.warning.call_args_list]
        assert "chroma_check_failed" in warning_names or "chroma_init_failed" in warning_names

def test_startup_tool_registry_recoverable():
    """Test that Tool Registry failure is recoverable and results in degraded status."""
    with (
        patch("backend.main.register_all_tools", side_effect=Exception("Registry failure")),
        patch("backend.main.LLM_ROUTER.initialize", new_callable=AsyncMock),
        patch("backend.db.check_chroma", new_callable=AsyncMock) as mock_check,
        patch("backend.main.TemporalClient") as mock_temporal_cls,
    ):
        mock_check.return_value = True
        mock_temporal = mock_temporal_cls.return_value
        mock_temporal.start = AsyncMock()
        mock_temporal.shutdown = AsyncMock()
        with (
            patch("backend.main.run_migrations"),
            patch("backend.main.logger") as mock_logger,
            TestClient(app) as client,
        ):
            resp = client.get("/health/detail")
            assert resp.status_code == 200
            data = resp.json()
            assert data["components"]["tool_registry"] == "failed"
            assert data["status"] == "degraded"

        # Check if tool_registry_init_failed was logged with exc_info=True
        warning_calls = [call for call in mock_logger.warning.call_args_list if call.args[0] == "tool_registry_init_failed"]
        assert len(warning_calls) == 1
        assert warning_calls[0].kwargs.get("exc_info") is True
