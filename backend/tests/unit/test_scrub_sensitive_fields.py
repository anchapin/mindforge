"""Unit tests for scrub() function from SPEC.md Section 3b.6.

The scrub() function recursively redacts sensitive fields in dicts and lists
before logging. It must redact ALL sensitive key patterns while preserving
non-sensitive fields like task_id, description, status.

Sensitive keys (case-insensitive match):
  - auth_token_enc, refresh_token_enc, access_token
  - password, secret, api_key, private_key
  - token, authorization, cookie, session
"""

import pytest

# SENSITIVE_KEYS from SPEC.md Section 3b.6
SENSITIVE_KEYS: set[str] = {
    "auth_token_enc",
    "refresh_token_enc",
    "access_token",
    "password",
    "secret",
    "api_key",
    "private_key",
    "token",
    "authorization",
    "cookie",
    "session",
}


def scrub(obj: dict | list) -> dict | list:
    """Recursively redact sensitive fields in a dict or list.

    This is the reference implementation from SPEC.md Section 3b.6.
    """
    if isinstance(obj, dict):
        return {
            k: "[REDACTED]" if k.lower() in SENSITIVE_KEYS else scrub(v)
            if isinstance(v, (dict, list))
            else v
            for k, v in obj.items()
        }
    elif isinstance(obj, list):
        return [scrub(i) for i in obj]
    return obj


@pytest.mark.parametrize(
    "key",
    [
        "auth_token_enc",
        "refresh_token_enc",
        "access_token",
        "password",
        "secret",
        "api_key",
        "private_key",
        "token",
        "authorization",
        "cookie",
        "session",
    ],
)
def test_scrub_redacts_sensitive_top_level_keys(key: str) -> None:
    """All top-level sensitive keys must be redacted."""
    payload = {key: "super-secret-value", "safe_field": "ok"}
    result = scrub(payload)
    assert result[key] == "[REDACTED]"    # type: ignore[call-overload]
    assert result["safe_field"] == "ok"    # type: ignore[call-overload]


def test_scrub_redacts_nested_sensitive_fields() -> None:
    """Sensitive fields nested inside dicts must be redacted."""
    payload = {
        "task_id": "123",
        "nested": {"access_token": "also-secret", "safe_field": "ok"},
    }
    result = scrub(payload)
    assert result["task_id"] == "123"    # type: ignore[call-overload]
    assert result["nested"]["access_token"] == "[REDACTED]"    # type: ignore[call-overload]
    assert result["nested"]["safe_field"] == "ok"    # type: ignore[call-overload]


def test_scrub_redacts_in_lists() -> None:
    """Sensitive fields inside list items must be redacted."""
    payload = {
        "list": [
            {"password": "bad", "role": "admin"},
            {"api_key": "worse", "name": "ok"},
        ]
    }
    result = scrub(payload)
    assert result["list"][0]["password"] == "[REDACTED]"    # type: ignore[call-overload]
    assert result["list"][0]["role"] == "admin"    # type: ignore[call-overload]
    assert result["list"][1]["api_key"] == "[REDACTED]"    # type: ignore[call-overload]
    assert result["list"][1]["name"] == "ok"    # type: ignore[call-overload]


def test_scrub_does_not_redact_task_id() -> None:
    """task_id must NOT be redacted."""
    payload = {"task_id": "123", "description": "Some task", "status": "running"}
    result = scrub(payload)
    assert result["task_id"] == "123"    # type: ignore[call-overload]
    assert result["description"] == "Some task"    # type: ignore[call-overload]
    assert result["status"] == "running"    # type: ignore[call-overload]


def test_scrub_does_not_redact_description() -> None:
    """description must NOT be redacted."""
    payload = {
        "task_id": "456",
        "description": "Draft an email to the customer",
        "auth_token_enc": "secret",
    }
    result = scrub(payload)
    assert result["description"] == "Draft an email to the customer"    # type: ignore[call-overload]
    assert result["auth_token_enc"] == "[REDACTED]"    # type: ignore[call-overload]


def test_scrub_does_not_redact_status() -> None:
    """status must NOT be redacted."""
    payload = {
        "task_id": "789",
        "status": "completed",
        "auth_token_enc": "secret",
    }
    result = scrub(payload)
    assert result["status"] == "completed"    # type: ignore[call-overload]
    assert result["auth_token_enc"] == "[REDACTED]"    # type: ignore[call-overload]


def test_scrub_case_insensitive_keys() -> None:
    """Sensitive key matching is case-insensitive."""
    payload = {
        "AUTH_TOKEN_ENC": "secret1",
        "Access_Token": "secret2",
        "PASSWORD": "secret3",
    }
    result = scrub(payload)
    assert result["AUTH_TOKEN_ENC"] == "[REDACTED]"    # type: ignore[call-overload]
    assert result["Access_Token"] == "[REDACTED]"    # type: ignore[call-overload]
    assert result["PASSWORD"] == "[REDACTED]"    # type: ignore[call-overload]


def test_scrub_preserves_non_sensitive_fields() -> None:
    """Non-sensitive fields must be preserved verbatim."""
    payload = {
        "task_id": "abc123",
        "agent_role": "engineer",
        "skill_name": "github-daily-summary",
        "created_at": "2026-05-13T10:00:00Z",
        "project_id": "proj_xyz",
    }
    result = scrub(payload)
    assert result == payload


def test_scrub_deeply_nested() -> None:
    """Scrub works on deeply nested structures."""
    payload = {
        "level1": {
            "level2": {
                "level3": {
                    "api_key": "nested-secret",
                    "task_id": "deep_task",
                }
            }
        }
    }
    result = scrub(payload)
    assert result["level1"]["level2"]["level3"]["api_key"] == "[REDACTED]"    # type: ignore[call-overload]
    assert result["level1"]["level2"]["level3"]["task_id"] == "deep_task"    # type: ignore[call-overload]


def test_scrub_empty_dict() -> None:
    """Scrub handles empty dicts."""
    assert scrub({}) == {}


def test_scrub_empty_list() -> None:
    """Scrub handles empty lists."""
    assert scrub([]) == []
