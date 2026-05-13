"""Layer 2 & 3 prompt injection defense — filtering and approval gates.

From SPEC.md §3b.8:
  Layer 2 — Instruction filtering at read / prompt-build time.
    Before injecting retrieved memories into a prompt, strip any text that
    matches injection patterns detected by sanitize_for_memory().
  Layer 3 — Approval gate amplification for memory-sourced high-stakes tasks.
    When memory is the primary context for a high-stakes action
    (email send, GitHub push, Stripe refund), force a draft-approval cycle.

Only Layer 2 lives here. Layer 3 is in agents/supervisor.py.
"""

from __future__ import annotations

import re
import structlog
from dataclasses import dataclass

from ..memory.sanitizer import (
    INJECTION_PATTERNS,
    INJECTION_WEIGHT_PATTERNS,
)

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------------------
# Layer 2 — Instruction filtering at prompt build
# ---------------------------------------------------------------------------------------

# Patterns that indicate a memory record may be trying to override system instructions.
# These are stripped from retrieved memories before prompt injection.
MEMORY_INSTRUCTION_PATTERNS: list[re.Pattern] = [
    # Prompt injection delimiters (should never appear in legitimate memory)
    re.compile(r"<\|system\|>", re.I),
    re.compile(r"<\|assistant\|>", re.I),
    re.compile(r"<\|user\|>", re.I),
    re.compile(r"<\|vision\|>", re.I),
    re.compile(r"{{system}}", re.I),
    re.compile(r"{{SYSTEM}}", re.I),
    # Override directives
    re.compile(r"ignore\s+(all\s+)?(previous|prior|above)\s+(instructions?|rules?)", re.I),
    re.compile(r"disregard\s+(your\s+)?(instructions?|rules?|constraints?)", re.I),
    re.compile(r"(instead|rather)\s+than\s+(what\s+)?(you\s+are|doing)", re.I),
    re.compile(r"forget\s+(everything|all)\s+(above|previous|you\s+know)", re.I),
    re.compile(r"new\s+instructions?:", re.I),
    re.compile(r"system\s+prompt:", re.I),
    # Role-play overrides
    re.compile(r"you\s+are\s+now\s+(a\s+)?(instructed\s+to\s+)?act\s+as", re.I),
    re.compile(r"pretend\s+you\s+are\s+", re.I),
    re.compile(r"as\s+an?\s+(AI|LLM|language model),?\s+you\s+should", re.I),
    # Hidden text markers (legitimate memory should be transparent)
    re.compile(r"\[hidden\]", re.I),
    re.compile(r"\[redacted\]", re.I),
    re.compile(r"<\s*hidden\s+text\s*>", re.I),
    # Our own sanitization placeholder (indicates previously stripped content)
    re.compile(r"\[\s*instruction\s+removed\s*\]", re.I),
]


@dataclass
class MemoryFilterResult:
    """Result of filtering a single memory record."""

    original_text: str
    filtered_text: str
    was_filtered: bool
    stripped_patterns: list[str]


def filter_memory_for_prompt(text: str) -> MemoryFilterResult:
    """Strip instruction-injection patterns from a retrieved memory record.

    Layer 2 defense (§3b.8). Called on each retrieved memory before it is
    injected into any prompt context.

    Returns a MemoryFilterResult with the (possibly) stripped text and a list
    of the patterns that were matched.

    Args:
        text: Raw text from semantic memory retrieval.

    Returns:
        MemoryFilterResult with original/filtered text and matched patterns.
    """
    original = text
    stripped: list[str] = []

    for pattern in MEMORY_INSTRUCTION_PATTERNS:
        if pattern.search(text):
            stripped.append(pattern.pattern)
            text = pattern.sub("[instruction removed]", text)

    # Also run the soft weighted patterns — strip if cumulative risk would be high
    soft_risk = sum(
        weight
        for p, weight in INJECTION_WEIGHT_PATTERNS
        if p.search(text)
    )
    if soft_risk > 0.6:
        # Strip the soft patterns too
        for pattern, _ in INJECTION_WEIGHT_PATTERNS:
            stripped_pattern = pattern.sub("[instruction removed]", text)
            # Avoid infinite loop if the soft pattern matches our own placeholder
            if stripped_pattern != text and "[instruction removed]" not in stripped_pattern:
                text = stripped_pattern
                stripped.append(pattern.pattern)

    was_filtered = len(stripped) > 0

    if was_filtered:
        logger.debug(
            "Filtered %d instruction patterns from memory before prompt injection",
            len(stripped),
        )

    return MemoryFilterResult(
        original_text=original,
        filtered_text=text,
        was_filtered=was_filtered,
        stripped_patterns=stripped,
    )


def filter_memories_for_prompt(
    records: list[dict],
    text_key: str = "text",
) -> list[dict]:
    """Filter a list of retrieved memory records before prompt injection.

    Layer 2 defense (§3b.8). Applies filter_memory_for_prompt() to each record
    and returns the filtered list, dropping records that are entirely stripped.

    Args:
        records: List of memory record dicts with a text field.
        text_key: Key name for the text field in each record.

    Returns:
        Filtered list of records. Each record gets an extra '_filtered' key
        indicating whether it was modified.
    """
    filtered: list[dict] = []

    for record in records:
        raw_text = record.get(text_key, "")
        if not raw_text:
            continue

        result = filter_memory_for_prompt(raw_text)

        if result.was_filtered:
            # Log but keep the record (with stripped text)
            logger.warning(
                "Memory record %s had instruction injection patterns stripped: %s",
                record.get("id", "?"),
                result.stripped_patterns,
            )

        # If the entire text was stripped to nothing, drop the record
        if not result.filtered_text.strip():
            logger.warning(
                "Dropping memory record %s — entirely stripped",
                record.get("id", "?"),
            )
            continue

        filtered_record = dict(record)
        filtered_record[text_key] = result.filtered_text
        filtered_record["_filtered"] = result.was_filtered
        filtered_record["_stripped_patterns"] = result.stripped_patterns
        filtered.append(filtered_record)

    return filtered


# ---------------------------------------------------------------------------------------
# High-stakes action classification (Layer 3 helper)
# ---------------------------------------------------------------------------------------

# Actions that always require approval when memory is the primary context.
HIGH_STAKES_ACTIONS: set[str] = {
    "send_email",
    "send_email_draft",
    "github_push",
    "github_create_pr",
    "github_merge_pr",
    "stripe_refund",
    "stripe_cancel_subscription",
    "delete_memory",
    "delete_episodic",
    "delete_task",
}


def is_high_stakes_action(action: str) -> bool:
    """Return True if this action requires forced approval when memory-sourced."""
    return action in HIGH_STAKES_ACTIONS


def requires_memory_approval_gate(
    action: str,
    memory_context_ratio: float = 0.0,
) -> bool:
    """Determine if a given action requires a forced approval gate.

    Layer 3 of §3b.8 — approval gate amplification for memory-sourced tasks.

    When a high-stakes action is triggered AND memory constitutes more than
    50% of the context driving that decision, force the draft-approval cycle.

    Args:
        action: The tool/action name being considered.
        memory_context_ratio: Fraction of the task context that came from memory
            retrieval (0.0 = no memory, 1.0 = entirely from memory).
    """
    if not is_high_stakes_action(action):
        return False
    # Memory is the primary context when it dominates the prompt (> 50%)
    return memory_context_ratio > 0.5
