"""SRT subtitle file parser."""

import re
from dataclasses import dataclass

# Speaker label patterns in SRT text:
#   [Speaker 1] text  or  [화자1] text
#   Speaker 1: text   or  화자1: text
#   SPEAKER_01: text
_SPEAKER_BRACKET_RE = re.compile(r"^\[([^\]]+)\]\s*")
_SPEAKER_COLON_RE = re.compile(r"^([\w\s]+?):\s+")


@dataclass
class SubtitleSegment:
    """A single subtitle segment with timing and text."""

    index: int
    start_ms: int
    end_ms: int
    text: str
    speaker: str | None = None

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms


def extract_speaker(text: str) -> tuple[str | None, str]:
    """Extract speaker label from subtitle text if present.

    Supports formats:
        [Speaker 1] text
        Speaker 1: text

    Returns:
        (speaker, clean_text) — speaker is None if not found.
    """
    m = _SPEAKER_BRACKET_RE.match(text)
    if m:
        return m.group(1).strip(), text[m.end():].strip()

    m = _SPEAKER_COLON_RE.match(text)
    if m:
        candidate = m.group(1).strip()
        # Avoid false positives: only accept short labels (≤20 chars)
        if len(candidate) <= 20:
            return candidate, text[m.end():].strip()

    return None, text


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

        # Extract speaker label if present
        speaker, clean_text = extract_speaker(text)

        segments.append(
            SubtitleSegment(
                index=index, start_ms=start_ms, end_ms=end_ms,
                text=clean_text, speaker=speaker,
            )
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
        text = f"[{seg.speaker}] {seg.text}" if seg.speaker else seg.text
        lines.append(text)
        lines.append("")

    return "\n".join(lines)
