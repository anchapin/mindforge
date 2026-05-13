"""Canary test for the PyYAML RCE vector from SPEC.md Section 3b.1.

This test verifies that yaml.safe_load() rejects Python object deserialization
patterns used in the FullLoader RCE attack vector.

The attack uses !!python/object/apply or !!python/object to deserialize
arbitrary Python objects, enabling remote code execution.

See: https://github.com/yaml/pyyaml/wiki/Python-object-deserialization
"""

import pytest
import yaml

MALICIOUS_YAML = """
name: bomb
yaml_content: |
  !!python/object/apply:os.system ["echo pwned"]
"""

MALICIOUS_YAML_LIST = """
data:
  - !!python/object/apply:os.system ["ls"]
  - !!python/object/apply:os.system ["whoami"]
"""

MALICIOUS_YAML_constructor = """
!!python/object/apply:yaml.constructor
  - !!python/object/apply:os.system
    - echo injected
"""


def test_safe_yaml_rejects_object_deserialization() -> None:
    """safe_load must raise ConstructorError for !!python/object tags.

    This is the canary test for the RCE vector in SPEC.md Section 3b.1.
    FullLoader would succeed here — safe_load must reject it.
    """
    with pytest.raises(yaml.constructor.ConstructorError):
        yaml.safe_load(MALICIOUS_YAML)


def test_safe_yaml_rejects_list_of_objects() -> None:
    """safe_load must reject lists containing Python object tags."""
    with pytest.raises(yaml.constructor.ConstructorError):
        yaml.safe_load(MALICIOUS_YAML_LIST)


def test_safe_yaml_rejects_constructor_injection() -> None:
    """safe_load must reject yaml.constructor injection attempts."""
    with pytest.raises(yaml.constructor.ConstructorError):
        yaml.safe_load(MALICIOUS_YAML_constructor)


def test_safe_yaml_accepts_normal_yaml() -> None:
    """safe_load must accept normal YAML without Python tags."""
    normal_yaml = """
name: test-skill
version: "1"
nodes:
  - id: start
    agent: coo
    goal: Start here
    tools: []
"""
    result = yaml.safe_load(normal_yaml)
    assert result["name"] == "test-skill"
    assert result["version"] == "1"
    assert len(result["nodes"]) == 1


def test_safe_yaml_accepts_standard_tags() -> None:
    """safe_load must accept standard YAML tags: !!str, !!int, !!float, !!bool, !!null."""
    yaml_with_tags = """
version: !!str "1"
count: !!int 42
rate: !!float 3.14
enabled: !!bool true
nothing: !!null null
"""
    result = yaml.safe_load(yaml_with_tags)
    assert result["version"] == "1"
    assert result["count"] == 42
    assert result["rate"] == 3.14
    assert result["enabled"] is True
    assert result["nothing"] is None
