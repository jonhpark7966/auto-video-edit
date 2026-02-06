"""Podcast Cut skill for auto-video-edit.

Optimized for multi-speaker podcast/interview videos.
Focuses on removing boring segments while preserving entertainment value.

Key difference from subtitle-cut:
- subtitle-cut: Information efficiency (remove duplicates, fillers)
- podcast-cut: Entertainment value (remove boring, keep funny/engaging)
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
    AnalysisResult,
    get_video_info,
)
from .models import PodcastCutReason, PodcastKeepReason
from .claude_analyzer import analyze_with_claude

__all__ = [
    "SubtitleSegment",
    "parse_srt_file",
    "parse_srt",
    "AnalysisResult",
    "PodcastCutReason",
    "PodcastKeepReason",
    "analyze_with_claude",
    "get_video_info",
]
