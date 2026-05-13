"""MindForge memory system -- shared persistent memory.

Exports:
    SharedMemoryStore -- sole interface for all memory read/write
    classify_task_type -- keyword-based task type classification
    sanitize_for_memory -- Layer 1 prompt injection defense
"""

from .episodic import EpisodicMemory, EpisodicMemoryStore
from .sanitizer import ContentSource, classify_injection_risk, sanitize_for_memory
from .semantic import SemanticMemory
from .store import SharedMemoryStore, classify_task_type
from .style import WritingProfileStore

__all__ = [
    "SharedMemoryStore",
    "classify_task_type",
    "sanitize_for_memory",
    "classify_injection_risk",
    "ContentSource",
    "WritingProfileStore",
    "EpisodicMemoryStore",
    "EpisodicMemory",
    "SemanticMemory",
]
