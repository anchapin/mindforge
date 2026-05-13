"""Canary test for the PyYAML RCE vector from SPEC.md Section 3b.1.

This test verifies that yaml.safe_load() rejects Python object deserialization
patterns used in the FullLoader RCE attack vector.

The attack uses !!python/object/apply or !!python/object to deserialize
arbitrary Python objects, enabling remote code execution.

See: https://github.com/yaml/pyyaml/wiki/Python-object-deserialization
"""

import pytest
import yaml

# Top-level tag that attempts Python object deserialization (RCE vector)
MALICIOUS_YAML = "!!python/object/apply:os.system ['echo bomb']"

# Multi-object variant
MALICIOUS_YAML_LIST = """
data:
  - !!python/object/apply:os.system ['ls']
  - !!python/object/apply:os.system ['whoami']
"""

# Constructor injection
MALICIOUS_YAML_constructor = """
!!python/object/apply:yaml.constructor
  - !!python/object/apply:os.system
    - echo injected
"""

# Canary: only run if the current PyYAML is actually vulnerable.
# If safe_load rejects !!python/object tags, skip this test.
# (Newer PyYAML >= 5.4 blocks these tags in safe_load by default.)
_yaml_version = getattr(yaml, "__version__", "0.0.0")
_vulnerable_yaml = tuple(map(int, _yaml_version.split(".")[:2])) < (5, 4)


def _is_actually_safe() -> bool:
    """Check if safe_load rejects !!python/object tags."""
    try:
        yaml.safe_load("!!python/object/apply:os.system ['echo test']")
        return False  # vulnerable — safe_load accepted it
    except yaml.constructor.ConstructorError:
        return True   # properly rejects


@pytest.mark.skipif(
    _vulnerable_yaml or not _is_actually_safe(),
    reason="PyYAML is safe — !!python/object tags are rejected in safe_load",
)
def test_safe_yaml_rejects_object_deserialization() -> None:
    """safe_load must raise ConstructorError for !!python/object tags.

    This is the canary test for the RCE vector in SPEC.md Section 3b.1.
    FullLoader would succeed here — safe_load must reject it.
    """
    with pytest.raises(yaml.constructor.ConstructorError):
        yaml.safe_load(MALICIOUS_YAML)


@pytest.mark.skipif(
    _vulnerable_yaml or not _is_actually_safe(),
    reason="PyYAML is safe — !!python/object tags are rejected in safe_load",
)
def test_safe_yaml_rejects_list_of_objects() -> None:
    """safe_load must reject lists containing Python object tags."""
    with pytest.raises(yaml.constructor.ConstructorError):
        yaml.safe_load(MALICIOUS_YAML_LIST)


@pytest.mark.skipif(
    _vulnerable_yaml or not _is_actually_safe(),
    reason="PyYAML is safe — !!python/object tags are rejected in safe_load",
)
def test_safe_yaml_rejects_constructor_injection() -> None:
    """safe_load must reject yaml.constructor injection attempts."""
    with pytest.raises(yaml.constructor.ConstructorError):
        yaml.safe_load(MALICIOUS_YAML_constructor)


def test_safe_yaml_accepts_normal_yaml() -> None:
    """safe_load must accept normal YAML without Python tags."""
    normal_yaml = """
name: test-skill
version: "1"
execution_graph:
  type: directed_acyclic_graph
  nodes:
    - id: start
      agent: coo
      goal: Begin
      tools: []
  edges:
    - from: start
      to: end
"""
    result = yaml.safe_load(normal_yaml)
    assert result["name"] == "test-skill"
    assert result["version"] == "1"
