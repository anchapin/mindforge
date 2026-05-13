"""OpenRouter client with streaming support, retry logic, and circuit breakers.

Implements SPEC.md §5.7.1 — OpenRouter client for cloud tiers.
"""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import AsyncGenerator

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from backend.exceptions import BudgetExceeded, RateLimitError

# ── Retry Config ──────────────────────────────────────────────────────────────


LLM_RETRY_CONFIG = {
    "max_attempts": 3,
    "backoff_factor": 2,
    "jitter": True,
}


def _is_retryable(exc: Exception) -> bool:
    """Return True for errors that are safe to retry."""
    return isinstance(exc, (RateLimitError, TimeoutError, httpx.TimeoutException))


# ── Circuit Breaker ───────────────────────────────────────────────────────────


class CircuitBreaker:
    """Circuit breaker for a single model.

    Tracks consecutive failures. After max_failures, the circuit opens for
    circuit_timeout seconds, preventing further requests to the failed model.
    """

    def __init__(
        self,
        model: str,
        max_failures: int = 5,
        circuit_timeout: float = 300.0,  # 5 minutes
    ):
        self.model = model
        self.max_failures = max_failures
        self.circuit_timeout = circuit_timeout
        self._failures = 0
        self._open_at: float | None = None
        self._lock = asyncio.Lock()

    @property
    def is_open(self) -> bool:
        """Check if circuit is currently open (tripped)."""
        if self._open_at is None:
            return False
        if time.monotonic() - self._open_at >= self.circuit_timeout:
            # Timeout expired — try to close the circuit
            self._open_at = None
            self._failures = 0
            return False
        return True

    async def record_failure(self) -> None:
        """Record a failure and potentially trip the circuit."""
        async with self._lock:
            self._failures += 1
            if self._failures >= self.max_failures:
                self._open_at = time.monotonic()

    async def record_success(self) -> None:
        """Reset on successful call."""
        async with self._lock:
            self._failures = 0
            self._open_at = None


# ── OpenRouter Client ────────────────────────────────────────────────────────


class OpenRouterClient:
    """HTTP client for the OpenRouter API with retry and circuit breaker support."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = "https://openrouter.ai/api/v1",
        timeout: float = 60.0,
    ):
        self.api_key = api_key or os.environ.get("OPENROUTER_API_KEY", "")
        self.base_url = base_url
        self._client: httpx.AsyncClient | None = None
        self._timeout = timeout
        self._circuit_breakers: dict[str, CircuitBreaker] = {}

    async def initialize(self) -> None:
        """Create the HTTP client and initialize circuit breakers."""
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(self._timeout),
        )
        # One circuit breaker per model in the fallback chain
        for model in [
            "openai/gpt-4o",
            "anthropic/claude-3.5-sonnet",
            "google/gemini-2.0-flash",
        ]:
            self._circuit_breakers[model] = CircuitBreaker(model=model)

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    def _get_circuit_breaker(self, model: str) -> CircuitBreaker | None:
        return self._circuit_breakers.get(model)

    @retry(
        stop=stop_after_attempt(LLM_RETRY_CONFIG["max_attempts"]),
        wait=wait_exponential_jitter(
            jitter=LLM_RETRY_CONFIG["jitter"],
            base=LLM_RETRY_CONFIG["backoff_factor"],
        ),
        retry=retry_if_exception_type((RateLimitError, TimeoutError)),
        reraise=True,
    )
    async def complete(
        self,
        prompt: str,
        model: str = "openai/gpt-4o",
        system: str = "",
        max_tokens: int = 4096,
        temperature: float = 0.0,
        stream: bool = False,
    ) -> str | AsyncGenerator[str, None]:
        """Call the OpenRouter chat completions endpoint.

        Args:
            prompt: The user prompt.
            model: OpenRouter model ID (e.g. "openai/gpt-4o").
            system: Optional system prompt.
            max_tokens: Maximum tokens in response.
            temperature: Sampling temperature.
            stream: If True, returns an async generator of tokens.

        Returns:
            Complete response string, or async generator of tokens if stream=True.

        Raises:
            BudgetExceeded: When the budget guard blocks the call.
            RateLimitError: When the model returns 429.
            RuntimeError: When all fallback models are unavailable.
        """
        if self._client is None:
            raise RuntimeError("OpenRouter client not initialized — call initialize() first")

        # Check budget guard
        from backend.llm.cost_tracker import BUDGET_GUARD

        tokens_estimate = len(prompt) // 4 + max_tokens
        allowed, reason = BUDGET_GUARD.check(tokens_estimate=tokens_estimate)
        if not allowed:
            raise BudgetExceeded(f"OpenRouter budget limit: {reason}")

        # Check circuit breaker
        cb = self._get_circuit_breaker(model)
        if cb and cb.is_open:
            raise RateLimitError(f"Circuit breaker open for {model}")

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        try:
            if stream:
                return self._stream(model, messages, max_tokens, temperature, cb)

            response = await self._client.post(
                "/chat/completions",
                json={
                    "model": model,
                    "messages": messages,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                },
            )

            if response.status_code == 429:
                if cb:
                    await cb.record_failure()
                raise RateLimitError("OpenRouter rate limit (429)")

            response.raise_for_status()
            data = response.json()

            # Record usage
            tokens_used = data.get("usage", {}).get("total_tokens", 0)
            BUDGET_GUARD.record(tokens_used=tokens_used)

            if cb:
                await cb.record_success()

            return data["choices"][0]["message"]["content"]

        except (RateLimitError, httpx.HTTPStatusError, TimeoutError):
            if cb:
                await cb.record_failure()
            raise

    async def _stream(
        self,
        model: str,
        messages: list[dict],
        max_tokens: int,
        temperature: float,
        cb: CircuitBreaker | None,
    ) -> AsyncGenerator[str, None]:
        """Streaming response from OpenRouter."""
        if self._client is None:
            raise RuntimeError("Client not initialized")

        try:
            async with self._client.stream(
                "POST",
                "/chat/completions",
                json={
                    "model": model,
                    "messages": messages,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                    "stream": True,
                },
            ) as response:
                if response.status_code == 429:
                    if cb:
                        await cb.record_failure()
                    raise RateLimitError("OpenRouter rate limit (429)")

                response.raise_for_status()

                async for line in response.aiter_lines():
                    if not line or line.startswith(":"):
                        continue
                    if line.startswith("data: "):
                        data_str = line[6:]
                        if data_str == "[DONE]":
                            break

                        import json

                        chunk = json.loads(data_str)
                        token = chunk.get("choices", [{}])[0].get("delta", {}).get(
                            "content", ""
                        )
                        if token:
                            yield token

                # Record success
                if cb:
                    await cb.record_success()

        except Exception:
            if cb:
                await cb.record_failure()
            raise


# ── Ollama client (LOCAL tier) ───────────────────────────────────────────────


async def _ollama_complete(
    prompt: str,
    model: str = "llama3.2:3b",
    system: str = "",
    max_tokens: int = 4096,
    temperature: float = 0.0,
) -> str:
    """Call local Ollama server for LOCAL tier inference.

    Uses the Ollama Python client library.
    """
    import ollama

    try:
        response = ollama.generate(
            model=model,
            prompt=prompt,
            system=system if system else None,
            options={
                "num_predict": max_tokens,
                "temperature": temperature,
            },
        )
        return response["response"]
    except ollama.ResponseError as e:
        raise RuntimeError(f"Ollama error: {e}") from e
    except Exception as e:
        raise RuntimeError(f"Ollama call failed: {e}") from e


async def _ollama_stream(
    prompt: str,
    model: str = "llama3.2:3b",
    system: str = "",
    max_tokens: int = 4096,
    temperature: float = 0.0,
) -> AsyncGenerator[str, None]:
    """Streaming response from local Ollama server."""
    import ollama

    try:
        response = await ollama.async_generate(
            model=model,
            prompt=prompt,
            system=system if system else None,
            options={
                "num_predict": max_tokens,
                "temperature": temperature,
            },
            stream=True,
        )
        async for part in response:
            if "response" in part:
                yield part["response"]
    except Exception as e:
        raise RuntimeError(f"Ollama stream failed: {e}") from e
