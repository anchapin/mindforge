"""LLM inference router with tiered routing, circuit breakers, and fallback chain.

Implements SPEC.md §5.7.1 — Hybrid Inference Router.
Supports LOCAL (Ollama), CLOUD_FAST (gemini-2.0-flash), and CLOUD_HEAVY (gpt-4o) tiers.
"""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from enum import Enum

import httpx
import ollama

from backend.exceptions import BudgetExceeded

# ── Tier Enums and Configs ────────────────────────────────────────────────────


class InferenceTier(str, Enum):
    """Inference routing tier. Determines which LLM endpoint is used."""

    LOCAL = "local"
    CLOUD_FAST = "cloud_fast"
    CLOUD_HEAVY = "cloud_heavy"


@dataclass
class LLMConfig:
    """Configuration for a single inference tier."""

    tier: InferenceTier
    model: str
    local_url: str = "http://127.0.0.1:11434/api/generate"
    cloud_provider: str = "openrouter"
    max_tokens: int = 4096
    temperature: float = 0.0


TIER_CONFIGS: dict[InferenceTier, LLMConfig] = {
    InferenceTier.LOCAL: LLMConfig(InferenceTier.LOCAL, "llama3.2:3b"),
    InferenceTier.CLOUD_FAST: LLMConfig(
        InferenceTier.CLOUD_FAST, "google/gemini-2.0-flash"
    ),
    InferenceTier.CLOUD_HEAVY: LLMConfig(InferenceTier.CLOUD_HEAVY, "openai/gpt-4o"),
}

# Fallback chain when primary model fails (circuit breaker open)
FALLBACK_CHAIN = [
    "openai/gpt-4o",
    "anthropic/claude-3.5-sonnet",
    "google/gemini-2.0-flash",
]

# Agent role → inference tier mapping (per SPEC.md §5.7.1)
AGENT_MODEL_CONFIG: dict[str, InferenceTier] = {
    "coo": InferenceTier.CLOUD_HEAVY,  # planning, escalation decisions
    "cmo": InferenceTier.CLOUD_FAST,  # email drafting, most tasks
    "researcher": InferenceTier.CLOUD_HEAVY,  # multi-source analysis
    "engineer": InferenceTier.CLOUD_FAST,  # GitHub API summaries, code review
}


# ── Circuit Breaker ───────────────────────────────────────────────────────────


class CircuitBreaker:
    """Per-model circuit breaker that trips after max_failures consecutive errors.

    When open, the breaker blocks requests to that model for circuit_timeout seconds,
    allowing the upstream service to recover.
    """

    def __init__(
        self,
        models: list[str] | None = None,
        max_failures: int = 5,
        circuit_timeout: float = 300.0,
    ):
        self._models = models or FALLBACK_CHAIN
        self._max_failures = max_failures
        self._circuit_timeout = circuit_timeout
        self._failures: dict[str, int] = dict.fromkeys(self._models, 0)
        self._circuit_open: dict[str, float] = {}  # model → open_time
        self._lock = asyncio.Lock()

    async def record_failure(self, model: str) -> None:
        """Record a failure for a model, potentially tripping the circuit."""
        async with self._lock:
            self._failures[model] = self._failures.get(model, 0) + 1
            if self._failures[model] >= self._max_failures:
                self._circuit_open[model] = time.monotonic()
                # Reset so we don't keep incrementing while circuit is open
                self._failures[model] = 0

    async def record_success(self, model: str) -> None:
        """Reset failure count on successful call."""
        async with self._lock:
            self._failures[model] = 0
            self._circuit_open.pop(model, None)

    def is_available(self, model: str) -> bool:
        """Check if a model circuit is closed (available for requests)."""
        if model not in self._circuit_open:
            return True
        open_time = self._circuit_open[model]
        if time.monotonic() - open_time >= self._circuit_timeout:
            # Circuit timeout expired — try again
            self._circuit_open.pop(model, None)
            return True
        return False

    def get_next_available(self) -> str | None:
        """Return the first available model from the fallback chain.

        Returns None if all circuits are open.
        """
        for model in self._models:
            if self.is_available(model):
                return model
        return None


# ── Tier Classification ──────────────────────────────────────────────────────


def classify_tier(
    task_description: str,
    estimated_tokens: int,
    has_tools: bool = False,
    is_multi_step: bool = False,
) -> InferenceTier:
    """Route a prompt to the appropriate inference tier.

    Uses heuristic rules — no LLM call needed.

    Args:
        task_description: The task prompt text.
        estimated_tokens: Rough token count of the full context.
        has_tools: Whether the task requires tool/API calls.
        is_multi_step: Whether the task involves multi-step reasoning.

    Returns:
        The InferenceTier to use for this task.
    """
    # Local: small, no tools, no multi-step
    if estimated_tokens <= 256 and not has_tools and not is_multi_step:
        return InferenceTier.LOCAL

    # Cloud Fast: moderate size, no multi-step
    if estimated_tokens <= 2048 and not is_multi_step:
        return InferenceTier.CLOUD_FAST

    # Everything else: heavy
    return InferenceTier.CLOUD_HEAVY


def estimate_tokens(text: str) -> int:
    """Rough token estimate: 4 chars/token for English text.

    This is a conservative heuristic. Real tokenizers (cl100k_base) produce
    slightly higher counts for the same text.
    """
    return len(text) // 4


# ── LLM Router Singleton ──────────────────────────────────────────────────────


class LLMRouter:
    """Tiered LLM inference router with circuit breakers and fallback.

    This is the main entry point for all LLM calls in MindForge.
    """

    def __init__(self):
        self._circuit_breakers: dict[str, CircuitBreaker] = {}
        self._initialized = False
        self._openrouter_client: httpx.AsyncClient | None = None

    async def initialize(self) -> None:
        """Initialize the router — open HTTP client, warm up Ollama."""
        self._openrouter_client = httpx.AsyncClient(
            base_url="https://openrouter.ai/api/v1",
            headers={
                "Authorization": f"Bearer {os.environ.get('OPENROUTER_API_KEY', '')}",
            },
            timeout=httpx.Timeout(60.0),
        )
        # Pre-build circuit breakers per model
        for model in FALLBACK_CHAIN:
            self._circuit_breakers[model] = CircuitBreaker(max_failures=5)
        self._initialized = True

    async def close(self) -> None:
        """Close HTTP client on shutdown."""
        if self._openrouter_client:
            await self._openrouter_client.aclose()
            self._openrouter_client = None

    async def complete(
        self,
        prompt: str,
        tier: InferenceTier | None = None,
        system: str = "",
        agent_role: str | None = None,
        stream: bool = False,
    ) -> str | AsyncGenerator[str, None]:
        """Complete a prompt using the appropriate tier.

        Args:
            prompt: The user prompt.
            tier: Explicit tier override. If None, inferred from agent_role.
            system: System prompt string.
            agent_role: Agent role key used to look up tier from AGENT_MODEL_CONFIG.
            stream: Whether to yield tokens as they arrive.

        Returns:
            The complete response text, or an async generator of tokens if stream=True.
        """
        if not self._initialized:
            await self.initialize()

        # Determine tier
        if tier is None and agent_role is not None:
            tier = AGENT_MODEL_CONFIG.get(agent_role, InferenceTier.CLOUD_FAST)
        elif tier is None:
            tier = InferenceTier.CLOUD_FAST

        cfg = TIER_CONFIGS[tier]

        if cfg.tier == InferenceTier.LOCAL:
            return await self._ollama_complete(cfg, system, prompt)
        return await self._openrouter_complete(
            cfg, system, prompt, stream=stream, agent_role=agent_role
        )

    async def _ollama_complete(
        self, cfg: LLMConfig, system: str, prompt: str
    ) -> str:
        """Call local Ollama server."""
        try:
            opts = {"num_predict": cfg.max_tokens, "temperature": cfg.temperature}
            if system:
                response = ollama.generate(
                    model=cfg.model,
                    prompt=prompt,
                    system=system,
                    options=opts,
                )
            else:
                response = ollama.generate(
                    model=cfg.model,
                    prompt=prompt,
                    options=opts,
                )
            return response["response"]
        except Exception as e:
            raise RuntimeError(f"Ollama call failed: {e}") from e

    async def _openrouter_complete(
        self,
        cfg: LLMConfig,
        system: str,
        prompt: str,
        stream: bool = False,
        agent_role: str | None = None,
    ) -> str | AsyncGenerator[str, None]:
        """Call OpenRouter API with circuit breaker and fallback."""
        if self._openrouter_client is None:
            raise RuntimeError("OpenRouter client not initialized")

        # Check budget guard first
        from backend.llm.cost_tracker import BUDGET_GUARD

        tokens_estimate = estimate_tokens(prompt) + cfg.max_tokens
        allowed, reason = BUDGET_GUARD.check(tokens_estimate=tokens_estimate)
        if not allowed:
            raise BudgetExceeded(f"OpenRouter rate limit: {reason}")

        # Try fallback chain
        for model in FALLBACK_CHAIN:
            cb = self._circuit_breakers.get(model)
            if cb and not cb.is_available(model):
                continue  # circuit open, skip

            try:
                if stream:
                    return self._openrouter_stream(
                        cfg, system, prompt, model=model, agent_role=agent_role
                    )

                response = await self._openrouter_single(
                    cfg, system, prompt, model=model, agent_role=agent_role
                )

                # Record success
                if cb:
                    await cb.record_success(model)

                return response
            except Exception as e:
                # Record failure
                if cb:
                    await cb.record_failure(model)
                continue

        raise RuntimeError("All models in fallback chain are unavailable")

    async def _openrouter_single(
        self,
        cfg: LLMConfig,
        system: str,
        prompt: str,
        model: str,
        agent_role: str | None = None,
    ) -> str:
        """Single non-streaming OpenRouter call."""
        if self._openrouter_client is None:
            raise RuntimeError("OpenRouter client not initialized")

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        response = await self._openrouter_client.post(
            "/chat/completions",
            json={
                "model": model,
                "messages": messages,
                "max_tokens": cfg.max_tokens,
                "temperature": cfg.temperature,
            },
        )
        response.raise_for_status()
        data = response.json()

        # Record usage
        from backend.llm.cost_tracker import BUDGET_GUARD

        tokens_used = data.get("usage", {}).get("total_tokens", 0)
        BUDGET_GUARD.record(tokens_used=tokens_used)

        return data["choices"][0]["message"]["content"]

    async def _openrouter_stream(
        self,
        cfg: LLMConfig,
        system: str,
        prompt: str,
        model: str,
        agent_role: str | None = None,
    ) -> AsyncGenerator[str, None]:
        """Streaming OpenRouter call — yields tokens as they arrive."""
        if self._openrouter_client is None:
            raise RuntimeError("OpenRouter client not initialized")

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        async with self._openrouter_client.stream(
            "POST",
            "/chat/completions",
            json={
                "model": model,
                "messages": messages,
                "max_tokens": cfg.max_tokens,
                "temperature": cfg.temperature,
                "stream": True,
            },
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line or line.startswith(":"):
                    continue
                if line.startswith("data: "):
                    data = line[6:]
                    if data == "[DONE]":
                        break
                    import json

                    chunk = json.loads(data)
                    token = chunk.get("choices", [{}])[0].get("delta", {}).get(
                        "content", ""
                    )
                    if token:
                        yield token


# Global singleton
LLM_ROUTER = LLMRouter()


# ── Public API wrapper ────────────────────────────────────────────────────────
# Convenience functions that delegate to the router singleton.


async def llm_complete(
    prompt: str,
    tier: InferenceTier | None = None,
    system: str = "",
    agent_role: str | None = None,
) -> str:
    """Complete a prompt using the appropriate LLM tier.

    Args:
        prompt: The user prompt.
        tier: Explicit inference tier override.
        system: Optional system prompt.
        agent_role: Agent role key for tier inference.

    Returns:
        The complete response text.

    Raises:
        RuntimeError: When all models in the fallback chain are unavailable.
    """
    result = await LLM_ROUTER.complete(
        prompt=prompt,
        tier=tier,
        system=system,
        agent_role=agent_role,
        stream=False,
    )
    # complete() returns str when stream=False
    assert isinstance(result, str), f"expected str, got {type(result)}"
    return result


async def llm_complete_stream(
    prompt: str,
    tier: InferenceTier | None = None,
    system: str = "",
    agent_role: str | None = None,
) -> AsyncGenerator[str, None]:
    """Stream a prompt completion token by token."""
    result = await LLM_ROUTER.complete(
        prompt=prompt,
        tier=tier,
        system=system,
        agent_role=agent_role,
        stream=True,
    )
    # The router returns a generator directly when stream=True
    assert isinstance(result, AsyncGenerator), f"expected AsyncGenerator, got {type(result)}"
    return result
