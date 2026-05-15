"""Tests for JSON parsing utilities in agents.

Verifies robust JSON parse error handling with retry logic and recovery.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.agents.json_utils import MAX_RETRIES, parse_with_recovery


class TestParseWithRecovery:
    """Test parse_with_recovery handles various JSON scenarios."""

    @pytest.fixture
    def mock_llm_complete(self):
        """Mock LLM completion function."""
        return AsyncMock()

    @pytest.mark.asyncio
    async def test_valid_json_returns_parsed_result(self, mock_llm_complete):
        """Valid JSON should parse successfully on first attempt."""
        valid_json = '{"summary": "test", "result": "output", "next_steps": []}'
        result = await parse_with_recovery(valid_json, "TestAgent", mock_llm_complete)

        assert result == {"summary": "test", "result": "output", "next_steps": []}
        mock_llm_complete.assert_not_called()

    @pytest.mark.asyncio
    async def test_json_with_markdown_formatting_retries(self, mock_llm_complete):
        """JSON wrapped in markdown blocks triggers retry with correction."""
        mock_llm_complete.return_value = '{"summary": "fixed", "result": "ok", "next_steps": []}'
        markdown_json = '```json\n{"summary": "test", "result": "bad", "next_steps": []}\n```'

        result = await parse_with_recovery(markdown_json, "TestAgent", mock_llm_complete)

        # Should have retried with correction prompt
        assert mock_llm_complete.called
        assert result["summary"] == "fixed"

    @pytest.mark.asyncio
    async def test_invalid_json_returns_error_dict(self, mock_llm_complete):
        """Invalid JSON should return error dict after exhausting retries."""
        mock_llm_complete.side_effect = Exception("LLM unavailable")
        invalid_json = '{"summary":'

        result = await parse_with_recovery(invalid_json, "TestAgent", mock_llm_complete)

        assert result["status"] == "error"
        assert result["summary"] == "TestAgent parse error"
        assert "error" in result
        assert result["result"] == ""
        assert result["next_steps"] == []

    @pytest.mark.asyncio
    async def test_totally_invalid_response_returns_error_dict(self, mock_llm_complete):
        """Non-JSON text should return error dict with status error."""
        mock_llm_complete.side_effect = Exception("LLM unavailable")
        invalid_text = "This is not JSON at all, just plain text."

        result = await parse_with_recovery(invalid_text, "TestAgent", mock_llm_complete)

        assert result["status"] == "error"
        assert result["summary"] == "TestAgent parse error"

    @pytest.mark.asyncio
    async def test_max_retries_respected(self, mock_llm_complete):
        """Should only retry up to max_retries times."""
        mock_llm_complete.return_value = "still not json"
        invalid_json = '{"invalid":'

        result = await parse_with_recovery(invalid_json, "TestAgent", mock_llm_complete, max_retries=2)

        # MAX_RETRIES=2 means initial + 1 correction = 2 LLM calls
        assert mock_llm_complete.call_count == 1
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_raw_response_truncated_for_long_input(self, mock_llm_complete):
        """Raw response should be truncated to 500 chars for safety."""
        mock_llm_complete.side_effect = Exception("LLM unavailable")
        long_text = "x" * 1000

        result = await parse_with_recovery(long_text, "TestAgent", mock_llm_complete)

        assert "raw_response" in result
        assert len(result["raw_response"]) == 500

    @pytest.mark.asyncio
    async def test_correction_prompt_contains_json_instruction(self, mock_llm_complete):
        """Correction prompt should instruct LLM about valid JSON output."""
        mock_llm_complete.return_value = '{"summary": "corrected", "result": "fixed", "next_steps": []}'

        result = await parse_with_recovery('{"broken', "TestAgent", mock_llm_complete)

        assert mock_llm_complete.called
        call_args = mock_llm_complete.call_args
        prompt = call_args.kwargs.get("prompt", "")
        system = call_args.kwargs.get("system", "")
        # Verify the correction prompt mentions JSON
        assert "json" in prompt.lower() or "json" in system.lower()

    @pytest.mark.asyncio
    async def test_extraction_fallback_on_final_attempt(self, mock_llm_complete):
        """On final attempt, should try to extract JSON-like content from response."""
        mock_llm_complete.side_effect = Exception("fail")
        response_with_text = 'Some text before {"summary": "extracted", "result": "found", "next_steps": []} and some after'

        result = await parse_with_recovery(response_with_text, "TestAgent", mock_llm_complete, max_retries=1)

        # With max_retries=1, goes straight to extraction fallback
        assert result["summary"] == "extracted"

    @pytest.mark.asyncio
    async def test_agent_name_in_error_response(self, mock_llm_complete):
        """Error response should include agent name in summary."""
        mock_llm_complete.side_effect = Exception("fail")
        invalid = '{"summary":'

        result = await parse_with_recovery(invalid, "MyAgent", mock_llm_complete)

        assert "MyAgent" in result["summary"]
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_next_steps_defaults_to_empty_list_on_error(self, mock_llm_complete):
        """Error response should include empty next_steps list."""
        mock_llm_complete.side_effect = Exception("fail")
        invalid = "not json"

        result = await parse_with_recovery(invalid, "TestAgent", mock_llm_complete)

        assert result["next_steps"] == []
        assert result["result"] == ""

    @pytest.mark.asyncio
    async def test_result_defaults_to_empty_string_on_error(self, mock_llm_complete):
        """Error response should include empty result string."""
        mock_llm_complete.side_effect = Exception("fail")
        invalid = "not json"

        result = await parse_with_recovery(invalid, "TestAgent", mock_llm_complete)

        assert result["result"] == ""

    @pytest.mark.asyncio
    async def test_status_is_error_on_failure(self, mock_llm_complete):
        """Error response should have status='error'."""
        mock_llm_complete.side_effect = Exception("fail")
        invalid = "not json"

        result = await parse_with_recovery(invalid, "TestAgent", mock_llm_complete)

        assert result["status"] == "error"