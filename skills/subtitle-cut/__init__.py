"""Subtitle Cut Detector skill for auto-video-edit.

Optimized for single-speaker educational/explanation videos.
Focuses on removing duplicates, incomplete takes, and fillers.
"""

from skills._common import (
    SubtitleSegment,
    parse_srt_file,
    parse_srt,
    AnalysisResult,
    get_video_info,
)
from .models import CutReason, KeepReason
from .claude_analyzer import analyze_with_claude
from .codex_analyzer import analyze_with_codex

__all__ = [
    "SubtitleSegment",
    "parse_srt_file",
    "parse_srt",
    "AnalysisResult",
    "CutReason",
    "KeepReason",
    "analyze_with_claude",
    "analyze_with_codex",
    "get_video_info",
]
