"""Data models for subtitle-cut skill."""

from dataclasses import dataclass, field
from enum import Enum


class CutReason(str, Enum):
    """Reason for cutting a segment."""
    DUPLICATE = "duplicate"
    INCOMPLETE = "incomplete"
    FILLER = "filler"
    FUMBLE = "fumble"


class KeepReason(str, Enum):
    """Reason for keeping a segment."""
    BEST_TAKE = "best_take"
    UNIQUE = "unique"


@dataclass
class SegmentAnalysis:
    """Analysis result for a single subtitle segment."""
    segment_index: int
    action: str  # "cut" or "keep"
    reason: str
    note: str = ""


@dataclass
class AnalysisResult:
    """Complete analysis result from Claude/Codex."""
    cuts: list[dict] = field(default_factory=list)  # {"segment_index": int, "reason": str, "note": str}
    keeps: list[dict] = field(default_factory=list)  # {"segment_index": int, "is_best_take": bool, "note": str}
    raw_response: str = ""
