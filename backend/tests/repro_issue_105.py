
import pytest

from backend.skills.executor import execute_skill
from backend.skills.registry import SkillRegistry


class MockLLM:
    async def complete(self, prompt, system, agent_role):
        return "mock response"

@pytest.mark.asyncio
async def test_invocation_validation_catch_disk_change(tmp_path):
    # 1. Setup a valid skill on disk
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    skill_file = skills_dir / "test-skill.yaml"
    valid_yaml = """
name: Test Skill
description: A test skill
version: 1
trigger:
  type: keyword
  keywords: ["test"]
execution_graph:
  nodes:
    - id: start
      goal: start
"""
    skill_file.write_text(valid_yaml)

    registry = SkillRegistry(skills_dir=skills_dir)
    registry.load_all()

    skill = registry.get("test-skill")
    assert skill is not None

    # 2. Break the skill on disk (outside of API/registry) - Add a cycle
    invalid_yaml = """
name: Test Skill
description: A test skill
version: 1
trigger:
  type: keyword
  keywords: ["test"]
execution_graph:
  nodes:
    - id: start
      goal: start
  edges:
    - from: start
      to: start
"""
    skill_file.write_text(invalid_yaml)

    # 3. Try to execute - should ideally fail because it's re-validated
    # Currently it will likely PASS because it uses the in-memory skill object
    # which still has the old valid graph.

    llm = MockLLM()
    # In a real scenario, we might want it to reload from disk or at least validate the file on disk.
    # The requirement says: "Validate once per skill version", "Invalidate cache on skill update",
    # "Lightweight check: only validate if YAML changed since last validation"

    # If we want it to catch disk changes, execute_skill needs to call validate_for_execution
    # and if that fails, maybe we should also reload the skill object?
    # The AC says: "Invalid skills rejected at invocation"

    # Let's see if we can call validate_for_execution manually first
    errors = registry.validate_for_execution("test-skill")
    # This SHOULD return errors because the file on disk changed.
    assert len(errors) > 0, "Should have detected invalid YAML on disk"

    # Now verify that execute_skill actually fails
    # Currently it will likely PASS because it doesn't call validation
    result = await execute_skill(
        skill=skill,
        task_id="test-task",
        llm_complete=llm.complete,
        tools=None
    )

    assert result.status == "failed"
    assert "validation" in result.error.lower()
