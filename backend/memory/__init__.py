"""MindForge memory system -- shared persistent memory.

Exports:
    SharedMemoryStore -- sole interface for all memory read/write
    classify_task_type -- keyword-based task type classification
    sanitize_for_memory -- Layer 1 prompt injection defense
"""

from .store import SharedMemoryStore, classify_task_type
from .sanitizer import sanitize_for_memory, classify_injection_risk, ContentSource
from .style import WritingProfileStore
from .episodic import EpisodicMemoryStore, EpisodicMemory
from .semantic import SemanticMemory

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
