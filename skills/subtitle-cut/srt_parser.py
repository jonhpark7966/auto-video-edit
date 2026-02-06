"""SRT parser module - re-exports from _common for backwards compatibility."""

import sys
from pathlib import Path

# Add skills directory to path for imports
skills_dir = Path(__file__).parent.parent
if str(skills_dir) not in sys.path:
    sys.path.insert(0, str(skills_dir))

from _common.srt_parser import (
    SubtitleSegment,
    parse_srt,
    parse_srt_file,
    parse_timestamp,
    segments_to_srt,
)

__all__ = [
    "SubtitleSegment",
    "parse_srt",
    "parse_srt_file",
    "parse_timestamp",
    "segments_to_srt",
]
