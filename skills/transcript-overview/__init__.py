"""Transcript Overview skill for auto-video-edit (Pass 1).

Analyzes full transcript to produce storyline overview:
narrative arc, chapters, key moments, dependencies, and pacing notes.

Used as context input for Pass 2 skills (subtitle-cut, podcast-cut).
"""

import sys
from pathlib import Path

# Add skills directory to path for imports
skills_dir = Path(__file__).parent.parent
if str(skills_dir) not in sys.path:
    sys.path.insert(0, str(skills_dir))

from _common import (
    SubtitleSegment,
    parse_srt_file,
    parse_srt,
)
from .models import TranscriptOverview, Chapter, KeyMoment, Dependency, NarrativeArc
from .claude_analyzer import analyze_with_claude

__all__ = [
    "SubtitleSegment",
    "parse_srt_file",
    "parse_srt",
    "TranscriptOverview",
    "Chapter",
    "KeyMoment",
    "Dependency",
    "NarrativeArc",
    "analyze_with_claude",
]
