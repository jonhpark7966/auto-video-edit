"""SRT subtitle file parser."""

import re
from dataclasses import dataclass


@dataclass
class SubtitleSegment:
    """A single subtitle segment with timing and text."""

    index: int
    start_ms: int
    end_ms: int
    text: str

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms


def parse_timestamp(timestamp: str) -> int:
    """Parse SRT timestamp to milliseconds.

    Format: HH:MM:SS,mmm
    """
    match = re.match(r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})", timestamp.strip())
    if not match:
        raise ValueError(f"Invalid timestamp format: {timestamp}")

    hours, minutes, seconds, millis = map(int, match.groups())
    return hours * 3600000 + minutes * 60000 + seconds * 1000 + millis


def parse_srt(content: str) -> list[SubtitleSegment]:
    """Parse SRT content into subtitle segments.

    Args:
        content: Raw SRT file content

    Returns:
        List of SubtitleSegment objects
    """
    segments: list[SubtitleSegment] = []

    # Split by double newlines (segment separators)
    # Handle both \n\n and \r\n\r\n
    blocks = re.split(r"\n\s*\n", content.strip())

    for block in blocks:
        if not block.strip():
            continue

        lines = block.strip().split("\n")
        if len(lines) < 3:
            continue

        # First line: index
        try:
            index = int(lines[0].strip())
        except ValueError:
            continue

        # Second line: timestamps
        time_match = re.match(
            r"(\d{2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,.]\d{3})",
            lines[1].strip(),
        )
        if not time_match:
            continue

        start_ms = parse_timestamp(time_match.group(1))
        end_ms = parse_timestamp(time_match.group(2))

        # Remaining lines: text
        text = " ".join(line.strip() for line in lines[2:] if line.strip())

        segments.append(
            SubtitleSegment(index=index, start_ms=start_ms, end_ms=end_ms, text=text)
        )

    return segments


def parse_srt_file(path: str) -> list[SubtitleSegment]:
    """Parse SRT file from path.

    Args:
        path: Path to SRT file

    Returns:
        List of SubtitleSegment objects
    """
    with open(path, encoding="utf-8") as f:
        return parse_srt(f.read())


def segments_to_srt(segments: list[SubtitleSegment]) -> str:
    """Convert subtitle segments back to SRT format.

    Args:
        segments: List of SubtitleSegment objects

    Returns:
        SRT formatted string
    """
    def ms_to_srt_time(ms: int) -> str:
        hours = ms // 3600000
        minutes = (ms % 3600000) // 60000
        seconds = (ms % 60000) // 1000
        millis = ms % 1000
        return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"

    lines = []
    for i, seg in enumerate(segments, 1):
        lines.append(str(i))
        lines.append(f"{ms_to_srt_time(seg.start_ms)} --> {ms_to_srt_time(seg.end_ms)}")
        lines.append(seg.text)
        lines.append("")

    return "\n".join(lines)
