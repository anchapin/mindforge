"""Prompt injection defense for semantic memory.

Implements three-layer defense from SPEC.md §3b.8:
  Layer 1 — Input classification at write time
  Layer 2 — Instruction filtering at read time (in prompts.py)
  Layer 3 — Approval gate amplification for memory-sourced tasks

Only Layer 1 lives here. Layers 2 and 3 are in backend/llm/prompts.py.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

# ---------------------------------------------------------------------------------------
# Content source classification
# ---------------------------------------------------------------------------------------

class ContentSource(str, Enum):
    """Trust level of the content origin."""
    HUMAN = "human"               # Direct user input — always trusted
    INTEGRATION = "integration"   # Email, scrape, calendar — untrusted
    SKILL_OUTPUT = "skill_output" # Agent-generated — low trust


# ---------------------------------------------------------------------------------------
# Injection pattern definitions
# ---------------------------------------------------------------------------------------

# Hard patterns — any match is an automatic flag
INJECTION_PATTERNS: list[re.Pattern] = [
    # Directive overrides
    re.compile(r"ignore\s+(all\s+)?(previous|above|prior)\s+(instructions?|orders?|rules?)", re.I),
    re.compile(r"disregard\s+(your|the)\s+(instructions?|rules?|constraints?)", re.I),
    re.compile(r"(instead|rather)\s+than\s+(what|doing)", re.I),
    re.compile(r"forget\s+(everything|all)\s+(above|previous)", re.I),
    # LLM delimiter injection
    re.compile(r"<\|system\|>", re.I),
    re.compile(r"<\|assistant\|>", re.I),
    re.compile(r"<\|user\|>", re.I),
    re.compile(r"^\s*##?\s*System\s*Instructions?", re.I),
    re.compile(r"##\s*System", re.I),
    # Role-play / persona injection
    re.compile(r"you\s+are\s+now\s+(a\s+)?(instructed\s+to\s+)?act\s+as", re.I),
    re.compile(r"pretend\s+you\s+are\s+", re.I),
    re.compile(r"as\s+an?\s+(AI|LLM|language model)", re.I),
    # Base64 / obfuscation — common in evasion
    re.compile(r"^[A-Za-z0-9+/]{64,}={0,2}$"),   # Long base64 strings
    re.compile(r"\\x[0-9a-f]{2}", re.I),          # Hex-encoded shell
]

# Soft patterns — weighted, threshold-based
INJECTION_WEIGHT_PATTERNS: list[tuple[re.Pattern, float]] = [
    (re.compile(r"(reminder|note|instruction|important):", re.I), 0.6),
    (re.compile(r"please\s+(also\s+)?(ignore|disregard)", re.I), 0.8),
    (re.compile(r"additional(ly)?\s+inst(ructions?)?", re.I), 0.7),
    (re.compile(r"you\s+should\s+also", re.I), 0.4),
    (re.compile(r"don'?t\s+(reveal|tell|copy)", re.I), 0.5),
    (re.compile(r"hidden\s+(text|content|instructions?)", re.I), 0.9),
]


# ---------------------------------------------------------------------------------------
# Risk classification
# ---------------------------------------------------------------------------------------

@dataclass
class InjectionCheckResult:
    is_suspect: bool
    risk_score: float          # 0.0 (safe) → 1.0 (clear injection)
    matched_patterns: list[str]
    source: ContentSource

    def __repr__(self) -> str:
        return (
            f"InjectionCheckResult(suspect={self.is_suspect}, "
            f"risk={self.risk_score:.2f}, matches={len(self.matched_patterns)})"
        )


def classify_injection_risk(text: str, source: ContentSource) -> InjectionCheckResult:
    """Classify prompt injection risk of text from a given source.

    Returns (is_suspect, risk_score, matched_patterns).
    HUMAN source is always trusted — returns safe result immediately.
    """
    if source == ContentSource.HUMAN:
        return InjectionCheckResult(is_suspect=False, risk_score=0.0, matched_patterns=[], source=source)

    matched: list[str] = []

    # Hard patterns — any match adds 0.9 to risk
    for pattern in INJECTION_PATTERNS:
        if pattern.search(text):
            matched.append(pattern.pattern)

    # Weighted soft patterns
    risk = sum(weight for pattern, weight in INJECTION_WEIGHT_PATTERNS if pattern.search(text))

    # Hard matches cap at 0.9; allow soft patterns to push to 1.0
    if matched:
        risk = max(risk, 0.9)

    # Cap at 1.0
    risk = min(risk, 1.0)

    # Threshold: flag if risk > 0.6 OR any hard pattern matched
    is_suspect = risk > 0.6 or len(matched) > 0

    return InjectionCheckResult(
        is_suspect=is_suspect,
        risk_score=risk,
        matched_patterns=matched,
        source=source,
    )


# ---------------------------------------------------------------------------------------
# Sanitization
# ---------------------------------------------------------------------------------------

@dataclass
class SanitizationResult:
    text: str
    was_sanitized: bool
    risk_score: float
    flags: list[str]

    def as_metadata(self) -> dict:
        return {
            "risk_score": self.risk_score,
            "was_sanitized": self.was_sanitized,
            "flags": self.flags,
        }


def sanitize_for_memory(
    text: str,
    source: ContentSource,
    project_id: str | None = None,
) -> SanitizationResult:
    """Sanitize text before embedding into ChromaDB.

    This is Layer 1 of the three-layer injection defense (§3b.8).
    Must be called for all INTEGRATION and SKILL_OUTPUT content before
    embed_texts() is called.

    HUMAN source text passes through unchanged.

    Args:
        text: Raw text from an external source.
        source: Trust level of the content origin.
        project_id: Project scope for metadata tracking.

    Returns:
        SanitizationResult with sanitized text and metadata flags.
    """
    if source == ContentSource.HUMAN:
        return SanitizationResult(
            text=text,
            was_sanitized=False,
            risk_score=0.0,
            flags=[],
        )

    check = classify_injection_risk(text, source)

    sanitized = text
    if check.is_suspect:
        # Replace detected patterns with a neutral placeholder
        for pattern in INJECTION_PATTERNS:
            sanitized = pattern.sub("[instruction removed]", sanitized)
        for pattern, _ in INJECTION_WEIGHT_PATTERNS:
            sanitized = pattern.sub("[instruction removed]", sanitized)

    flags = ["injection_suspect"] if check.is_suspect else []

    return SanitizationResult(
        text=sanitized,
        was_sanitized=check.is_suspect,
        risk_score=check.risk_score,
        flags=flags,
    )
