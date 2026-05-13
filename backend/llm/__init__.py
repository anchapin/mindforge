"""MindForge LLM -- inference routing, circuit breakers, cost tracking."""

from .cost_tracker import BUDGET_GUARD
from .inference import llm_complete, llm_complete_stream
from .router import LLM_ROUTER, InferenceTier, classify_tier

# Alias for backwards compatibility
CostTracker = BUDGET_GUARD

__all__ = [
    "LLM_ROUTER",
    "classify_tier",
    "InferenceTier",
    "llm_complete",
    "llm_complete_stream",
    "BUDGET_GUARD",
    "CostTracker",
]
