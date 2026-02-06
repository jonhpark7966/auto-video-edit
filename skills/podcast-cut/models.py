"""Data models for podcast-cut skill.

These are specific to podcast/interview video editing.
The key focus is on "entertainment value" rather than "information efficiency".
"""

from dataclasses import dataclass, field
from enum import Enum


class PodcastCutReason(str, Enum):
    """Reason for cutting a segment in podcast videos.

    These reasons focus on removing segments that reduce entertainment value.
    """
    BORING = "boring"          # Low energy conversation, consecutive short answers
    TANGENT = "tangent"        # Boring tangent (interesting tangents should be kept!)
    REPETITIVE = "repetitive"  # Same story or point repeated
    LONG_PAUSE = "long_pause"  # Silence longer than 3 seconds
    CROSSTALK = "crosstalk"    # Overlapping speech that's hard to understand
    IRRELEVANT = "irrelevant"  # Content not relevant to viewers (TMI, inside jokes)
    FILLER = "filler"          # Filler words, "um", "uh", etc.


class PodcastKeepReason(str, Enum):
    """Reason for keeping a segment in podcast videos.

    These reasons focus on preserving segments with high entertainment value.
    """
    FUNNY = "funny"            # Humor, jokes, laughter
    WITTY = "witty"            # Clever responses, wordplay
    CHEMISTRY = "chemistry"    # Good dynamic between speakers, back-and-forth
    REACTION = "reaction"      # Surprise, laughter, empathy reactions
    CALLBACK = "callback"      # Callback humor, running jokes, references
    CLIMAX = "climax"          # Key point of a story or discussion
    ENGAGING = "engaging"      # Interesting story or topic
    EMOTIONAL = "emotional"    # Emotional moments, vulnerability


@dataclass
class PodcastAnalysisItem:
    """Single analysis item for a podcast segment."""
    segment_index: int
    action: str  # "cut" or "keep"
    reason: str  # One of PodcastCutReason or PodcastKeepReason values
    entertainment_score: int = 5  # 1-10 scale of entertainment value
    note: str = ""


@dataclass
class PodcastAnalysisResult:
    """Complete analysis result for podcast editing.

    Extends the base AnalysisResult with entertainment_score.
    """
    cuts: list[dict] = field(default_factory=list)
    # {"segment_index": int, "reason": str, "entertainment_score": int, "note": str}

    keeps: list[dict] = field(default_factory=list)
    # {"segment_index": int, "reason": str, "entertainment_score": int, "note": str}

    raw_response: str = ""
