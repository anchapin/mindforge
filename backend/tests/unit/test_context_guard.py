"""Unit tests for the max_context_tokens guard (#51, SPEC §5.7.6).

Pin the contract:
  - LLMConfig has a per-tier max_context_tokens budget.
  - LLMRouter.complete() raises ContextTooLong when system+prompt token
    estimate exceeds the tier budget BEFORE any network call.
  - ContextTooLong is in the exception taxonomy with category=ESCALATE.
  - Under-limit prompts pass through unchanged.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

# ---------------------------------------------------------------------------
# Exception taxonomy
# ---------------------------------------------------------------------------


class TestContextTooLongException:
    def test_is_importable_from_exceptions_module(self):
        from backend.exceptions import ContextTooLong

        exc = ContextTooLong("too big")
        assert isinstance(exc, Exception)
        assert "too big" in str(exc)

    def test_classified_as_escalate(self):
        """ContextTooLong belongs to the ESCALATE category -- caller
        decides whether to summarize or surface to the user."""
        from backend.exceptions import (
            ContextTooLong,
            ExceptionCategory,
            classify_exception,
        )

        category = classify_exception(ContextTooLong("oversize"))
        assert category == ExceptionCategory.ESCALATE


# ---------------------------------------------------------------------------
# Per-tier budget
# ---------------------------------------------------------------------------


class TestLLMConfigBudget:
    def test_each_tier_declares_max_context_tokens(self):
        from backend.llm.router import TIER_CONFIGS, InferenceTier

        for tier in (InferenceTier.LOCAL, InferenceTier.CLOUD_FAST, InferenceTier.CLOUD_HEAVY):
            cfg = TIER_CONFIGS[tier]
            assert hasattr(cfg, "max_context_tokens"), f"{tier} missing max_context_tokens"
            assert cfg.max_context_tokens > 0


# ---------------------------------------------------------------------------
# Router enforcement
# ---------------------------------------------------------------------------


class TestRouterGuard:
    @pytest.mark.asyncio
    async def test_under_budget_passes_through(self, monkeypatch):
        """A small prompt must NOT raise -- guard only fires on oversize."""
        from backend.llm.router import InferenceTier, LLMRouter

        router = LLMRouter()
        # Skip real initialization
        router._initialized = True

        # Patch the local completion path to avoid Ollama
        router._ollama_complete = AsyncMock(return_value="ok")  # type: ignore[assignment]

        result = await router.complete(
            prompt="short", tier=InferenceTier.LOCAL, system=""
        )
        assert result == "ok"
        router._ollama_complete.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_over_budget_raises_context_too_long(self, monkeypatch):
        """Oversize prompt must raise BEFORE any network call."""
        from backend.exceptions import ContextTooLong
        from backend.llm.router import TIER_CONFIGS, InferenceTier, LLMRouter

        router = LLMRouter()
        router._initialized = True

        # Spy that should NEVER be called when the guard fires
        router._ollama_complete = AsyncMock(return_value="should not be called")  # type: ignore[assignment]
        router._openrouter_complete = AsyncMock(  # type: ignore[assignment]
            return_value="should not be called"
        )

        # Build a prompt that estimates well over the LOCAL tier's budget.
        # estimate_tokens is len(text)//4, so 5x the limit guarantees overage.
        budget = TIER_CONFIGS[InferenceTier.LOCAL].max_context_tokens
        oversize_prompt = "x" * (budget * 5 * 4)

        with pytest.raises(ContextTooLong):
            await router.complete(
                prompt=oversize_prompt, tier=InferenceTier.LOCAL, system=""
            )

        router._ollama_complete.assert_not_awaited()
        router._openrouter_complete.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_system_plus_prompt_combined_against_budget(self):
        """The guard counts system + prompt tokens together -- a system
        prompt that overflows must trip the guard even if the user prompt
        is small."""
        from backend.exceptions import ContextTooLong
        from backend.llm.router import TIER_CONFIGS, InferenceTier, LLMRouter

        router = LLMRouter()
        router._initialized = True
        router._ollama_complete = AsyncMock(return_value="x")  # type: ignore[assignment]

        budget = TIER_CONFIGS[InferenceTier.LOCAL].max_context_tokens
        oversize_system = "s" * (budget * 5 * 4)

        with pytest.raises(ContextTooLong):
            await router.complete(
                prompt="hi", tier=InferenceTier.LOCAL, system=oversize_system
            )
