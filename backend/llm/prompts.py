"""Layer 2 & 3 prompt injection defense — filtering and approval gates.

From SPEC.md §3b.8:
  Layer 2 — Instruction filtering at read / prompt-build time.
    Before injecting retrieved memories into a prompt, strip any text that
    matches injection patterns detected by sanitize_for_memory().
  Layer 3 — Approval gate amplification for memory-sourced high-stakes tasks.
    When memory is the primary context for a high-stakes action
    (email send, GitHub PR, Stripe refund), force a draft-approval cycle.

Layer 2b (GLiGuard integration):
  Optional learned-safety classifier (fastino/gliguard-LLMGuardrails-300M) that
  runs after the regex filter to catch novel injection patterns that patterns miss.
  Enabled when GLIGUARD_ENABLED=true and gliner2 is installed.

Only Layer 2 and Layer 3 logic lives here. Layer 1 is in memory/sanitizer.py.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from gliner2 import GLiNER2  # noqa: F401

from ..memory.sanitizer import (
    INJECTION_WEIGHT_PATTERNS,
)

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------------------
# Layer 2a — Instruction filtering at prompt build (regex-based)
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
# Layer 2b — GLiGuard learned safety classifier
# ---------------------------------------------------------------------------------------

# Whether GLiGuard is enabled (set by environment or defaults to auto-detect).
GLIGUARD_ENABLED = os.getenv("GLIGUARD_ENABLED", "").lower() in ("1", "true", "yes")
GLIGUARD_THRESHOLD = float(os.getenv("GLIGUARD_THRESHOLD", "0.5"))

# GLiGuard task schemas — label sets passed to classify_text().
# These are used at inference time (schema-conditioned, no fine-tuning needed).
SAFETY_LABELS = ["safe", "unsafe"]

# Jailbreak detection: multi-label (can return multiple strategy labels).
JAILBREAK_TASK: dict[str, list[str]] = {
    "jailbreak_detection": [
        "ignore_previous",
        "role_play",
        "hijack_context",
        "sqli",
        "xss",
        "prompt_injection",
        "other",
    ],
}

# Toxicity categorization: multi-label.
TOXICITY_TASK: dict[str, list[str]] = {
    "prompt_toxicity": [
        "hate_speech",
        "harassment",
        "violence",
        "self_harm",
        "sexual",
        "child_safety",
        "privacy_violation",
        "misinformation",
        "other",
    ],
}


@dataclass
class GliguardResult:
    """Result from GLiGuard classification."""

    is_safe: bool
    confidence: float
    jailbreak_labels: list[str] = field(default_factory=list)
    toxicity_labels: list[str] = field(default_factory=list)
    model_version: str = ""
    error: str | None = None


# Lazy-loaded singleton GLiGuard model instance.
_gliguard_model: GLiNER2 | None = None
_gliguard_load_error: str | None = None


def _get_gliguard_model() -> GLiNER2 | None:
    """Lazy-load GLiGuard model. Returns None if not available or disabled."""
    global _gliguard_model, _gliguard_load_error

    if not GLIGUARD_ENABLED:
        return None

    if _gliguard_model is not None or _gliguard_load_error is not None:
        return _gliguard_model

    try:
        from gliner2 import GLiNER2  # type: ignore[import-not-found]

        logger.info("Loading GLiGuard model (fastino/gliguard-LLMGuardrails-300M)...")
        _gliguard_model = GLiNER2.from_pretrained("fastino/gliguard-LLMGuardrails-300M")
        # CPU-first design — run on CPU unless GPU is explicitly preferred
        device = os.getenv("GLIGUARD_DEVICE", "cpu")
        _gliguard_model.to(device)  # type: ignore[union-attr]
        logger.info("GLiGuard model loaded on device=%s", device)
        return _gliguard_model

    except ImportError:
        _gliguard_load_error = "gliner2 not installed — install with: pip install 'gliner2[local]'"
        logger.warning("GLiGuard disabled: %s", _gliguard_load_error)
        return None
    except Exception as exc:  # noqa: BLE001
        _gliguard_load_error = str(exc)
        logger.warning("GLiGuard failed to load: %s — disabling", exc)
        return None


def check_with_gliguard(text: str, threshold: float | None = None) -> GliguardResult:
    """Classify a memory record for safety using GLiGuard.

    Layer 2b defense — learned safety classifier that catches novel injection
    patterns regex patterns miss. Optional: enabled when GLIGUARD_ENABLED=true.

    Args:
        text: The memory text to classify (already regex-filtered by Layer 2a).
        threshold: Override the default GLIGUARD_THRESHOLD for this call.

    Returns:
        GliguardResult with safety classification and confidence.
        On error or when GLiGuard is disabled, returns GliguardResult(is_safe=True)
        so the pipeline continues without blocking.
    """
    if threshold is None:
        threshold = GLIGUARD_THRESHOLD

    model = _get_gliguard_model()

    # GLiGuard unavailable — degrade gracefully
    if model is None:
        return GliguardResult(
            is_safe=True,
            confidence=1.0,
            error=_gliguard_load_error or "GLiGuard not enabled",
        )

    try:
        result = model.classify_text(
            text,
            {
                "prompt_safety": SAFETY_LABELS,
                **JAILBREAK_TASK,
                **TOXICITY_TASK,
            },
            threshold=threshold,
        )

        prompt_safety = result.get("prompt_safety", "safe")
        is_safe = prompt_safety == "safe"

        # Extract multi-label outputs
        jailbreak_labels: list[str] = []
        toxicity_labels: list[str] = []

        jb = result.get("jailbreak_detection", [])
        if isinstance(jb, list):
            jailbreak_labels = jb

        tox = result.get("prompt_toxicity", [])
        if isinstance(tox, list):
            toxicity_labels = tox

        # Confidence: use 1.0 - distance from threshold proxy
        # If unsafe, assume moderate confidence; if safe, high confidence
        confidence = 0.95 if is_safe else 0.75

        logger.debug(
            "GLiGuard: is_safe=%s jailbreak=%s toxicity=%s",
            is_safe,
            jailbreak_labels,
            toxicity_labels,
        )

        return GliguardResult(
            is_safe=is_safe,
            confidence=confidence,
            jailbreak_labels=jailbreak_labels,
            toxicity_labels=toxicity_labels,
            model_version="gliguard-LLMGuardrails-300M",
        )

    except Exception as exc:  # noqa: BLE001
        logger.warning("GLiGuard classification failed: %s — allowing text through", exc)
        return GliguardResult(is_safe=True, confidence=0.0, error=str(exc))


def filter_memories_with_gliguard(
    records: list[dict],
    text_key: str = "text",
) -> tuple[list[dict], list[GliguardResult]]:
    """Filter memory records through Layer 2a (regex) then Layer 2b (GLiGuard).

    This is the full Layer 2 pipeline:
      1. filter_memory_for_prompt() — regex stripping (always runs)
      2. check_with_gliguard() — learned safety classifier (if GLIGUARD_ENABLED)

    Returns:
        Tuple of (filtered_records, gliguard_results) aligned by index.
        Records flagged as unsafe by GLiGuard are kept with _gliguard_suspicious=True
        and the action is logged — they are NOT silently dropped (Layer 2b is advisory).

    Args:
        records: List of memory record dicts.
        text_key: Key name for the text field.
    """
    filtered = filter_memories_for_prompt(records, text_key)
    gliguard_results: list[GliguardResult] = []

    for record in filtered:
        gl_result = check_with_gliguard(record.get(text_key, ""))
        gliguard_results.append(gl_result)

        if not gl_result.is_safe:
            logger.warning(
                "GLiGuard flagged memory record %s as unsafe: "
                "jailbreak=%s toxicity=%s",
                record.get("id", "?"),
                gl_result.jailbreak_labels,
                gl_result.toxicity_labels,
            )
            record["_gliguard_suspicious"] = True
            record["_gliguard_jailbreak"] = gl_result.jailbreak_labels
            record["_gliguard_toxicity"] = gl_result.toxicity_labels
        else:
            record["_gliguard_suspicious"] = False

    return filtered, gliguard_results


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
