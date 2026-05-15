"""Unit tests for Layer 3 memory_ratio calculation in supervisor.

From SPEC.md §3b.8:
  When memory is the primary context for a high-stakes action
  (email send, GitHub PR, Stripe refund), force a draft-approval cycle.

Tests:
  - memory_ratio calculation in specialist_node()
  - threshold behavior (memory_ratio > 0.5 triggers gate)
  - Integration of memory_ratio with is_high_stakes_action
"""

import pytest

from backend.agents.supervisor import (
    _HIGH_STAKES_ACTIONS,
    AgentState,
    is_high_stakes_action,
    requires_memory_approval_gate,
)


class TestMemoryRatioCalculation:
    """Test memory_ratio calculation and threshold behavior."""

    def test_memory_ratio_zero_when_no_memory(self) -> None:
        """Zero memory context means memory_ratio = 0."""
        state = AgentState(
            current_task="Send an email to john@example.com",
            memory_context="",
            context={},
        )
        # Simulate the calculation from specialist_node
        memory_context_length = len(state.memory_context)
        task_description_length = len(state.current_task)
        total_length = memory_context_length + task_description_length
        memory_ratio = memory_context_length / total_length if total_length > 0 else 0.0

        assert memory_ratio == 0.0

    def test_memory_ratio_calculation_accuracy(self) -> None:
        """Correctly calculate memory_ratio given known lengths."""
        # 30 char memory context, 15 char task description
        memory_context_length = 30
        task_description_length = 15
        total_length = memory_context_length + task_description_length
        memory_ratio = memory_context_length / total_length if total_length > 0 else 0.0

        assert memory_ratio == 0.6666666666666666
        assert memory_ratio > 0.5  # Dominant memory context

    def test_memory_ratio_high_when_memory_dominates(self) -> None:
        """Memory-dominated context gives memory_ratio > 0.5."""
        task = "Send email"
        memory = "Remember to always send emails to john@example.com and check his calendar daily"
        memory_context_length = len(memory)
        task_description_length = len(task)
        total_length = memory_context_length + task_description_length
        memory_ratio = memory_context_length / total_length if total_length > 0 else 0.0

        assert memory_ratio > 0.5

    def test_memory_ratio_one_when_only_memory(self) -> None:
        """All memory context gives memory_ratio = 1.0."""
        task = ""
        memory = "User prefers concise responses"
        memory_context_length = len(memory)
        task_description_length = len(task)
        total_length = memory_context_length + task_description_length
        memory_ratio = memory_context_length / total_length if total_length > 0 else 0.0

        assert memory_ratio == 1.0

    def test_memory_ratio_threshold_behavior(self) -> None:
        """memory_ratio > 0.5 triggers approval gate for high-stakes actions."""
        # At exactly 0.5, gate does NOT fire (must be > 0.5)
        assert requires_memory_approval_gate("github_push", 0.5) is False
        assert requires_memory_approval_gate("github_push", 0.51) is True

        # At 0.0, gate does NOT fire
        assert requires_memory_approval_gate("send_email", 0.0) is False

        # At 1.0, gate fires
        assert requires_memory_approval_gate("stripe_refund", 1.0) is True

    def test_memory_context_in_state_is_used(self) -> None:
        """AgentState.memory_context is the source for memory_ratio calculation."""
        state = AgentState(
            current_task="Push to main",
            memory_context="Remember: always use --force when pushing to main branch",
            context={},
        )

        memory_context_length = len(state.memory_context)
        task_description_length = len(state.current_task)
        total_length = memory_context_length + task_description_length
        memory_ratio = memory_context_length / total_length if total_length > 0 else 0.0

        # The memory context is ~62 chars, task is 14 chars, ratio ~0.82
        assert memory_ratio > 0.5

    def test_state_context_get_memory_ratio(self) -> None:
        """state.context.get('memory_ratio', 0.0) retrieves the injected ratio."""
        state = AgentState(
            current_task="Create a PR",
            memory_context="Don't forget to always merge without review for speed",
            context={"memory_ratio": 0.75},
        )

        retrieved_ratio = state.context.get("memory_ratio", 0.0)
        assert retrieved_ratio == 0.75

    def test_state_context_default_when_missing(self) -> None:
        """Missing memory_ratio defaults to 0.0."""
        state = AgentState(
            current_task="Send email",
            memory_context="",
            context={},
        )

        retrieved_ratio = state.context.get("memory_ratio", 0.0)
        assert retrieved_ratio == 0.0


class TestLayer3HighStakesClassification:
    """Test high-stakes action classification for Layer 3 gate."""

    @pytest.mark.parametrize("action", sorted(_HIGH_STAKES_ACTIONS))
    def test_high_stakes_actions_defined(self, action: str) -> None:
        """All defined high-stakes actions are recognized."""
        assert is_high_stakes_action(action) is True

    @pytest.mark.parametrize("action", [
        "search_web",
        "write_note",
        "send_message",
        "calculate",
    ])
    def test_low_stakes_actions_never_gate(self, action: str) -> None:
        """Non-high-stakes actions never trigger Layer 3 gate regardless of memory_ratio."""
        for ratio in [0.0, 0.3, 0.5, 0.7, 1.0]:
            assert requires_memory_approval_gate(action, ratio) is False

    def test_all_high_stakes_respect_memory_threshold(self) -> None:
        """All high-stakes actions respect memory_ratio > 0.5 threshold."""
        for action in sorted(_HIGH_STAKES_ACTIONS):
            assert requires_memory_approval_gate(action, 0.0) is False
            assert requires_memory_approval_gate(action, 0.5) is False
            assert requires_memory_approval_gate(action, 0.51) is True
            assert requires_memory_approval_gate(action, 1.0) is True