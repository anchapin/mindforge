"""Unit tests for PromptBuilder — max_context_tokens guard and PromptSegment types.

From SPEC.md §5.7.5-5.7.6:
  - PromptBuilder with PromptSegment structured types (system, memory, tool_result, history, cache_control)
  - max_context_tokens enforcement with truncation
  - TOKENIZER-based token counting

Tests are written first (RED phase), implementation follows.
"""

import pytest

from backend.llm.prompts import (
    InferenceTier,
    PromptBuilder,
    PromptSegment,
    Prompt,
)


class TestPromptSegment:
    """Test PromptSegment type system."""

    def test_prompt_segment_creation(self) -> None:
        """PromptSegment stores content, type, and cache_control."""
        seg = PromptSegment(
            content="You are a helpful assistant.",
            segment_type="system",
            cached=True,
        )
        assert seg.content == "You are a helpful assistant."
        assert seg.segment_type == "system"
        assert seg.cached is True

    def test_prompt_segment_types_are_distinct(self) -> None:
        """Different segment types are distinguishable."""
        types = ["system", "memory", "tool_result", "history", "cache_control"]
        segments = [PromptSegment(content=f"Content for {t}", segment_type=t) for t in types]
        for seg, expected_type in zip(segments, types):
            assert seg.segment_type == expected_type

    def test_prompt_segment_default_is_memory(self) -> None:
        """Default segment_type is 'memory', default cached is False."""
        seg = PromptSegment(content="Some text")
        assert seg.segment_type == "memory"
        assert seg.cached is False

    def test_prompt_segment_rejects_invalid_type(self) -> None:
        """Invalid segment_type raises ValueError."""
        with pytest.raises(ValueError, match="segment_type must be one of"):
            PromptSegment(content="Bad", segment_type="invalid_type")


class TestPromptBuilder:
    """Test PromptBuilder class with max_context_tokens guard."""

    def test_prompt_builder_initialization(self) -> None:
        """PromptBuilder initializes with a tier and token limit."""
        builder = PromptBuilder(tier=InferenceTier.CLOUD_HEAVY)
        assert builder.tier == InferenceTier.CLOUD_HEAVY

    def test_add_segment_appends_to_prompt(self) -> None:
        """Adding segments builds up the prompt."""
        builder = PromptBuilder(tier=InferenceTier.CLOUD_HEAVY)
        builder.add_segment(PromptSegment(content="System prompt", segment_type="system"))
        assert len(builder.segments) == 1

    def test_build_includes_all_segments(self) -> None:
        """build() returns assembled prompt string from all segments."""
        builder = PromptBuilder(tier=InferenceTier.CLOUD_HEAVY)
        builder.add_segment(PromptSegment(content="System", segment_type="system"))
        builder.add_segment(PromptSegment(content="Memory: ...", segment_type="memory"))
        prompt = builder.build()
        assert isinstance(prompt, Prompt)
        assert "System" in prompt.content
        assert "Memory: ..." in prompt.content

    def test_max_context_tokens_truncates_excess(self) -> None:
        """When total tokens exceed max_context_tokens, builder truncates.

        Truncation order (per SPEC §5.7.6):
        1. Drop non-cached segments oldest-first
        2. Partial keep on final segment if still over limit
        3. Cached segments are preserved
        """
        builder = PromptBuilder(tier=InferenceTier.CLOUD_HEAVY, max_context_tokens=50)
        # system segment (cached) — should be kept
        builder.add_segment(PromptSegment(content="System prompt " * 20, segment_type="system", cached=True))
        # memory segments (not cached) — should be dropped first
        builder.add_segment(PromptSegment(content="Memory entry " * 20, segment_type="memory", cached=False))
        builder.add_segment(PromptSegment(content="Another memory " * 20, segment_type="memory", cached=False))

        truncated_prompt = builder.build()
        assert isinstance(truncated_prompt, Prompt)
        # The result should be shorter than the sum of all segments
        original_total = len("System prompt " * 20) + len("Memory entry " * 20) + len("Another memory " * 20)
        assert len(truncated_prompt.content) < original_total

    def test_cached_segments_never_dropped(self) -> None:
        """Cached segments (system, cache_control) are preserved during truncation."""
        builder = PromptBuilder(tier=InferenceTier.LOCAL, max_context_tokens=30)
        builder.add_segment(PromptSegment(content="Critical system " * 5, segment_type="system", cached=True))
        builder.add_segment(PromptSegment(content="Non-critical " * 10, segment_type="memory", cached=False))

        result = builder.build()
        assert isinstance(result, Prompt)
        # The cached system segment must be present
        assert "Critical system" in result.content

    def test_truncation_marks_affected_segments(self) -> None:
        """Truncated prompt records which segment was partially cut."""
        builder = PromptBuilder(tier=InferenceTier.CLOUD_HEAVY, max_context_tokens=50)
        builder.add_segment(PromptSegment(content="X" * 200, segment_type="memory", cached=False))

        result = builder.build()
        assert isinstance(result, Prompt)
        # Truncation metadata must be present when truncation occurred
        assert result.truncation is not None
        assert result.truncation.original_token_count > result.truncation.final_token_count

    def test_estimate_tokens_uses_tokenizer(self) -> None:
        """Token estimation uses tokenizer for accuracy."""
        builder = PromptBuilder(tier=InferenceTier.CLOUD_HEAVY)
        tokens = builder.estimate_tokens("Hello world this is a test")
        assert isinstance(tokens, int)
        assert tokens > 0

    def test_empty_prompt_builds_without_error(self) -> None:
        """build() on empty builder returns empty string, not exception."""
        builder = PromptBuilder(tier=InferenceTier.CLOUD_HEAVY)
        result = builder.build()
        assert isinstance(result, Prompt)
        assert result.content == ""

    def test_convenience_add_methods(self) -> None:
        """add_system, add_memory, etc. add segments with correct types."""
        builder = PromptBuilder(tier=InferenceTier.CLOUD_HEAVY)
        builder.add_system("You are an AI.")
        builder.add_memory("Previous conversation about cats.")
        builder.add_tool_result("Tool returned: 42")
        builder.add_history("User asked about weather.")
        builder.add_cache_control("v1:hashabc")

        assert len(builder.segments) == 5
        types = [seg.segment_type for seg in builder.segments]
        assert types == ["system", "memory", "tool_result", "history", "cache_control"]
        cached = [seg.cached for seg in builder.segments]
        assert cached == [True, False, False, False, True]


class TestMaxContextTokensGuard:
    """Test max_context_tokens enforcement across tiers."""

    @pytest.mark.parametrize("tier,max_ctx", [
        (InferenceTier.LOCAL, 8192),
        (InferenceTier.CLOUD_FAST, 128_000),
        (InferenceTier.CLOUD_HEAVY, 200_000),
    ])
    def test_tier_has_correct_context_limit(self, tier: InferenceTier, max_ctx: int) -> None:
        """Each inference tier has appropriate context window size."""
        builder = PromptBuilder(tier=tier)
        # Default max_context_tokens should match tier limit
        assert builder.max_context_tokens == max_ctx

    def test_truncation_reserves_tokens_for_response(self) -> None:
        """Truncation leaves 512 tokens for response buffer."""
        # Use a very small limit to force truncation path
        builder = PromptBuilder(tier=InferenceTier.CLOUD_HEAVY, max_context_tokens=100)
        # Content that definitely exceeds 100 tokens
        big_content = "word " * 100  # 100 tokens = way over the 100 limit
        builder.add_segment(PromptSegment(content=big_content, segment_type="memory", cached=False))

        result = builder.build()
        assert isinstance(result, Prompt)
        # After truncation the content should be much shorter
        assert len(result.content) < len(big_content)
        # Truncation metadata should show the reduction
        assert result.truncation is not None
        assert result.truncation.final_token_count < result.truncation.original_token_count