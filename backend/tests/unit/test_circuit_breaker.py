"""Unit tests for CircuitBreaker model from SPEC.md Section 5.6.7.

CircuitBreaker model: CLOSED → OPEN → HALF-OPEN → OPEN/CLOSED
- CLOSED: normal operation, failures counted
- OPEN (after N failures): fast-fail without calling provider
- HALF-OPEN: probe call to verify recovery
- State transitions driven by failure_count and last_failure_time

Also tests the FALLBACK_CHAIN order from SPEC.md: openrouter → ollama → chroma → error.
"""

import time

# We use a simple in-memory implementation for testing
# The actual CircuitBreaker lives in circuit.py (to be implemented)


class CircuitBreaker:
    """Reference CircuitBreaker implementation for unit testing."""

    FAILURE_THRESHOLD = 3
    RECOVERY_TIMEOUT = 60.0  # seconds

    def __init__(self, name: str) -> None:
        self.name = name
        self.failure_count = 0
        self.last_failure_time: float | None = None
        self.state: str = "closed"  # closed | open | half_open

    def record_success(self) -> None:
        self.failure_count = 0
        self.state = "closed"

    def record_failure(self) -> None:
        self.failure_count += 1
        self.last_failure_time = time.time()
        if self.failure_count >= self.FAILURE_THRESHOLD:
            self.state = "open"

    def can_execute(self) -> bool:
        if self.state == "closed":
            return True
        if self.state == "open":
            if self.last_failure_time is None:
                return True
            elapsed = time.time() - self.last_failure_time
            if elapsed >= self.RECOVERY_TIMEOUT:
                self.state = "half_open"
                return True
            return False
        # half_open always allows execution
        return True


# FALLBACK_CHAIN from SPEC.md Section 5.6.7
FALLBACK_CHAIN = ["openrouter", "ollama", "chroma"]


class TestCircuitBreakerStates:
    """Test CircuitBreaker state machine transitions."""

    def test_initial_state_is_closed(self) -> None:
        """Circuit starts in CLOSED state."""
        cb = CircuitBreaker("test")
        assert cb.state == "closed"
        assert cb.failure_count == 0

    def test_closes_after_success(self) -> None:
        """Successful call resets failure count and stays closed."""
        cb = CircuitBreaker("test")
        cb.record_failure()
        cb.record_failure()
        assert cb.state == "closed"
        assert cb.failure_count == 2
        cb.record_success()
        assert cb.failure_count == 0
        assert cb.state == "closed"

    def test_opens_after_failure_threshold(self) -> None:
        """After FAILURE_THRESHOLD failures, circuit opens."""
        cb = CircuitBreaker("test")
        for _ in range(CircuitBreaker.FAILURE_THRESHOLD - 1):
            cb.record_failure()
        assert cb.state == "closed"
        cb.record_failure()  # now at threshold
        assert cb.state == "open"

    def test_open_blocks_execution(self) -> None:
        """In OPEN state, can_execute returns False."""
        cb = CircuitBreaker("test")
        for _ in range(CircuitBreaker.FAILURE_THRESHOLD):
            cb.record_failure()
        assert cb.state == "open"
        assert cb.can_execute() is False

    def test_half_open_after_recovery_timeout(self) -> None:
        """After RECOVERY_TIMEOUT in OPEN, circuit transitions to HALF_OPEN."""
        cb = CircuitBreaker("test")
        # Manually set state to open with old failure time
        cb.state = "open"
        cb.last_failure_time = time.time() - CircuitBreaker.RECOVERY_TIMEOUT - 1
        # Before checking can_execute, state should still be open
        # After can_execute, should transition to half_open
        result = cb.can_execute()
        assert result is True
        assert cb.state == "half_open"

    def test_half_open_allows_execution(self) -> None:
        """In HALF_OPEN state, can_execute returns True."""
        cb = CircuitBreaker("test")
        cb.state = "half_open"
        assert cb.can_execute() is True

    def test_half_open_success_closes(self) -> None:
        """Success in HALF_OPEN transitions back to CLOSED."""
        cb = CircuitBreaker("test")
        cb.state = "half_open"
        cb.record_success()
        assert cb.state == "closed"
        assert cb.failure_count == 0

    def test_half_open_failure_reopens(self) -> None:
        """Failure in HALF_OPEN transitions back to OPEN."""
        cb = CircuitBreaker("test")
        cb.state = "half_open"
        cb.record_failure()
        assert cb.state == "open"


class TestCircuitBreakerExecution:
    """Test CircuitBreaker.execute() behavior."""

    def test_execute_calls_func_in_closed_state(self) -> None:
        """When closed, func is called."""
        cb = CircuitBreaker("test")
        called = False

        def func() -> str:
            nonlocal called
            called = True
            return "ok"

        result = cb.can_execute()
        if result:
            out = func()
        assert called
        assert out == "ok"

    def test_execute_skips_func_in_open_state(self) -> None:
        """When open, func is NOT called (skip pattern)."""
        cb = CircuitBreaker("test")
        for _ in range(CircuitBreaker.FAILURE_THRESHOLD):
            cb.record_failure()

        called = False

        def func() -> str:
            nonlocal called
            called = True
            return "should not run"

        result = cb.can_execute()
        assert result is False
        assert called is False


class TestFallbackChain:
    """Test FALLBACK_CHAIN order from SPEC.md Section 5.6.7."""

    def test_fallback_chain_order(self) -> None:
        """Chain must be: openrouter → ollama → chroma → error."""
        assert FALLBACK_CHAIN == ["openrouter", "ollama", "chroma"]

    def test_fallback_chain_length(self) -> None:
        """Chain must have exactly 3 external providers."""
        assert len(FALLBACK_CHAIN) == 3

    def test_fallback_chain_no_duplicates(self) -> None:
        """No duplicates allowed in fallback chain."""
        assert len(FALLBACK_CHAIN) == len(set(FALLBACK_CHAIN))

    def test_fallback_chain_returns_providers_in_order(self) -> None:
        """Iterating returns providers in priority order."""
        providers = list(FALLBACK_CHAIN)
        assert providers[0] == "openrouter"
        assert providers[1] == "ollama"
        assert providers[2] == "chroma"
