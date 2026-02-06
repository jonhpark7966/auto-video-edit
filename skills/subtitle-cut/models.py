"""Data models for subtitle-cut skill.

These are specific to lecture/explanation video editing.
"""

from enum import Enum


class CutReason(str, Enum):
    """Reason for cutting a segment in lecture/explanation videos."""
    DUPLICATE = "duplicate"   # Same content repeated, keeping best take
    INCOMPLETE = "incomplete" # Sentence cut off or incomplete
    FILLER = "filler"         # Meaningless filler words, hesitation
    FUMBLE = "fumble"         # Stumbling, mispronunciation


class KeepReason(str, Enum):
    """Reason for keeping a segment in lecture/explanation videos."""
    BEST_TAKE = "best_take"   # Best version among duplicates
    UNIQUE = "unique"         # Unique content, no alternatives
