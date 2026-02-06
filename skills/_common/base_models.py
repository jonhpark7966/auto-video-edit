"""Base data models shared between video editing skills."""

from dataclasses import dataclass, field


@dataclass
class AnalysisResult:
    """Complete analysis result from AI analyzer.

    This is the common result format returned by both Claude and Codex analyzers.
    Each skill can have its own specific reason types, but this structure remains common.
    """
    cuts: list[dict] = field(default_factory=list)
    # {"segment_index": int, "reason": str, "note": str, ...}

    keeps: list[dict] = field(default_factory=list)
    # {"segment_index": int, "is_best_take": bool, "note": str, ...}

    raw_response: str = ""
