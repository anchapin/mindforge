"""MindForge exception taxonomy.

Every exception in MindForge belongs to one of four categories defined in
SPEC.md Section 5.6.9. Tests must assert the correct category for each error type.
"""

from enum import Enum


class ExceptionCategory(str, Enum):
    """Exception handling category.

    RETRY: Safe to retry automatically (RateLimitError, TransientFailure)
    ESCALATE: Requires human intervention (PermissionError, AuthFailure)
    LOG: Record only, do not propagate (HMACTamperError, InvalidTokenError)
    PANIC: Unrecoverable, halt (OutOfMemory, DatabaseCorruption)
    """

    RETRY = "retry"
    ESCALATE = "escalate"
    LOG = "log"
    PANIC = "panic"


# ── Exception category mapping ─────────────────────────────────────────────
# This must be evaluated lazily (inside classify_exception) because the
# concrete exception classes are defined after this dict in the file.
# Using a lazy import avoids NameError at module load time.

def _get_exception_category_map():  # type: ignore[no-redef]
    """Lazily build the exception→category map once all classes are defined."""
    return {
        # RETRY: safe to retry automatically
        RateLimitError: ExceptionCategory.RETRY,
        IntegrationTimeout: ExceptionCategory.RETRY,
        TransientFailure: ExceptionCategory.RETRY,
        # ESCALATE: requires human intervention
        PermissionError: ExceptionCategory.ESCALATE,
        AuthFailure: ExceptionCategory.ESCALATE,
        SafetyViolation: ExceptionCategory.ESCALATE,
        BudgetExceeded: ExceptionCategory.ESCALATE,
        # LOG: record only, do not propagate
        HMACTamperError: ExceptionCategory.LOG,
        InvalidTokenError: ExceptionCategory.LOG,
        ScrubbedDataWarning: ExceptionCategory.LOG,
        # PANIC: unrecoverable, halt
        OutOfMemory: ExceptionCategory.PANIC,
        DatabaseCorruption: ExceptionCategory.PANIC,
        UnrecoverableState: ExceptionCategory.PANIC,
    }


def classify_exception(exc: Exception) -> ExceptionCategory:
    """Classify an exception into its handling category.

    Returns the category for known exceptions. Unknown exceptions default to
    ESCALATE (conservative: requires human attention).
    """
    for exc_type, category in _get_exception_category_map().items():
        if isinstance(exc, exc_type):
            return category
    return ExceptionCategory.ESCALATE


# ── Concrete exceptions ──────────────────────────────────────────────────────


class BudgetExceeded(Exception):
    """Raised when OpenRouter budget guard prevents an LLM call."""

    pass


class HMACTamperError(Exception):
    """Raised when HMAC verification fails on semantic memory read.

    Indicates the memory entry was modified after writing.
    """

    pass


class RateLimitError(Exception):
    """Raised when an integration API returns 429 Too Many Requests."""

    pass


class IntegrationTimeout(Exception):
    """Raised when an integration API call exceeds its timeout."""

    pass


class TransientFailure(Exception):
    """Raised when an integration call fails due to transient conditions.

    Examples: connection reset, DNS lookup failure, 500 from upstream.
    """

    pass


class AuthFailure(Exception):
    """Raised when integration authentication fails.

    Examples: expired OAuth token, invalid API key, revoked permissions.
    """

    pass


class SafetyViolation(Exception):
    """Raised when a proposed action violates safety constraints.

    Examples: approval gate bypass attempt, cross-project data access.
    """

    pass


class InvalidTokenError(Exception):
    """Raised when a token fails decryption or validation.

    Examples: wrong Fernet key, corrupted token ciphertext.
    """

    pass


class ScrubbedDataWarning(Exception):
    """Raised when scrub() encounters unexpectedly sensitive data.

    This is informational — the data was successfully scrubbed.
    """

    pass


class DatabaseCorruption(Exception):
    """Raised when PGLite detects checksum mismatch or corruption."""

    pass


class UnrecoverableState(Exception):
    """Raised when the agent enters a state from which it cannot recover."""

    pass


class OutOfMemory(Exception):
    """Raised when the system runs out of memory.

    Triggers panic handling: task fails, human alert fired.
    """

    pass
