"""Shared JSON parsing utilities for agents.

Provides robust JSON parsing with retry logic and error recovery.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

MAX_RETRIES = 2


async def parse_with_recovery(
    response: str,
    agent_name: str,
    llm_complete_fn,
    max_retries: int = MAX_RETRIES,
) -> dict[str, Any]:
    """Parse JSON with retry and correction on failure.

    Args:
        response: Raw LLM response text
        agent_name: Name of agent for logging
        llm_complete_fn: Function to call for correction prompt
        max_retries: Maximum retry attempts

    Returns:
        Parsed JSON dict or error dict
    """
    for attempt in range(max_retries):
        try:
            result = json.loads(response)
            return result
        except json.JSONDecodeError as exc:
            if attempt == max_retries - 1:
                # Last attempt - try to extract JSON-like content
                json_match = re.search(r"\{.*\}", response, re.DOTALL)
                if json_match:
                    try:
                        return json.loads(json_match.group())
                    except json.JSONDecodeError:
                        pass

                # Give up - return error with raw response truncated for safety
                logger.error(
                    "%s JSON parse failed after %d attempts: %s",
                    agent_name,
                    max_retries,
                    exc,
                )
                return {
                    "error": f"JSON parse failed after {max_retries} attempts: {exc}",
                    "raw_response": response[:500] if len(response) > 500 else response,
                    "status": "error",
                    "summary": f"{agent_name} parse error",
                    "result": "",
                    "next_steps": [],
                }

            # Retry with correction prompt
            correction_prompt = (
                f"Remove any markdown formatting (```json blocks), explanations, "
                f"or text outside the JSON structure. Return only valid JSON.\n\n"
                f"Invalid output:\n{response}\n\nCorrected JSON:"
            )

            try:
                response = await llm_complete_fn(
                    prompt=correction_prompt,
                    system="Output only valid JSON, no markdown or explanations.",
                    tier="CLOUD_FAST",
                )
            except Exception as e:
                logger.warning(
                    "%s correction prompt failed: %s, trying extraction",
                    agent_name,
                    e,
                )
                # Fall back to extraction on correction failure
                break

    # Final fallback - return error with raw response preserved
    return {
        "error": f"JSON parse failed after {max_retries} attempts",
        "raw_response": response[:500] if len(response) > 500 else response,
        "status": "error",
        "summary": f"{agent_name} parse error",
        "result": "",
        "next_steps": [],
    }
