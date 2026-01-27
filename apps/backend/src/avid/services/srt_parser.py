"""SRT subtitle file parser.

Parses standard SRT format into structured TranscriptSegments
and detects gaps between subtitle entries as SilenceRegions.
"""

import re
from pathlib import Path

from avid.errors import SRTParseError
from avid.models.project import TranscriptSegment
from avid.models.silence import SilenceRegion

# SRT timestamp format: HH:MM:SS,mmm --> HH:MM:SS,mmm
_TIMESTAMP_RE = re.compile(
    r"(\d{2}):(\d{2}):(\d{2}),(\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2}),(\d{3})"
)

# HTML tag stripper
_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _timestamp_to_ms(hours: str, minutes: str, seconds: str, millis: str) -> int:
    """Convert SRT timestamp components to milliseconds."""
    return (
        int(hours) * 3_600_000
        + int(minutes) * 60_000
        + int(seconds) * 1_000
        + int(millis)
    )


def _strip_html_tags(text: str) -> str:
    """Remove HTML/SSA tags from subtitle text."""
    return _HTML_TAG_RE.sub("", text)


def _strip_bom(text: str) -> str:
    """Remove UTF-8 BOM if present."""
    if text.startswith("\ufeff"):
        return text[1:]
    return text


class SRTParser:
    """Parser for SRT subtitle files.

    Reads standard SRT format and produces TranscriptSegment objects.
    Can also detect gaps between consecutive subtitles as SilenceRegions.
    """

    def parse(self, srt_path: Path) -> list[TranscriptSegment]:
        """Parse an SRT file into transcript segments.

        Args:
            srt_path: Path to the .srt file

        Returns:
            List of TranscriptSegment ordered by start time

        Raises:
            SRTParseError: If the file cannot be read or contains no valid entries
            FileNotFoundError: If the file does not exist
        """
        srt_path = Path(srt_path)
        if not srt_path.exists():
            raise FileNotFoundError(f"SRT file not found: {srt_path}")

        try:
            content = srt_path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise SRTParseError(f"Failed to decode SRT file as UTF-8: {srt_path}") from exc

        content = _strip_bom(content)
        segments = self._parse_content(content, srt_path)

        if not segments:
            raise SRTParseError(f"No valid subtitle entries found in: {srt_path}")

        # Sort by start time for consistent ordering
        segments.sort(key=lambda s: s.start_ms)
        return segments

    def detect_gaps(
        self,
        srt_path: Path,
        min_gap_ms: int = 500,
    ) -> list[SilenceRegion]:
        """Detect gaps between consecutive subtitle segments.

        A gap is a period where no subtitle is displayed, which often
        corresponds to silence or non-speech audio.

        Args:
            srt_path: Path to the .srt file
            min_gap_ms: Minimum gap duration in ms to report (default: 500)

        Returns:
            List of SilenceRegion for gaps >= min_gap_ms, sorted by start time

        Raises:
            SRTParseError: If the file cannot be parsed
            FileNotFoundError: If the file does not exist
        """
        segments = self.parse(srt_path)

        gaps: list[SilenceRegion] = []
        for i in range(len(segments) - 1):
            current_end = segments[i].end_ms
            next_start = segments[i + 1].start_ms
            gap_ms = next_start - current_end

            if gap_ms >= min_gap_ms:
                gaps.append(
                    SilenceRegion(
                        start_ms=current_end,
                        end_ms=next_start,
                        source="srt",
                        confidence=0.7,
                    )
                )

        return gaps

    def _parse_content(
        self,
        content: str,
        source_path: Path,
    ) -> list[TranscriptSegment]:
        """Parse SRT content string into segments.

        SRT format per entry:
            <index>
            HH:MM:SS,mmm --> HH:MM:SS,mmm
            <text line 1>
            <text line 2 (optional)>
            <blank line>

        Malformed entries are skipped with a warning rather than
        aborting the entire file.
        """
        # Normalize line endings and split into blocks by blank lines
        content = content.replace("\r\n", "\n").replace("\r", "\n")
        blocks = re.split(r"\n\n+", content.strip())

        segments: list[TranscriptSegment] = []

        for block in blocks:
            segment = self._parse_block(block)
            if segment is not None:
                segments.append(segment)

        return segments

    def _parse_block(self, block: str) -> TranscriptSegment | None:
        """Parse a single SRT block into a TranscriptSegment.

        Returns None if the block is malformed or empty.
        """
        lines = block.strip().split("\n")
        if len(lines) < 2:
            return None

        # Find the timestamp line (may or may not have an index line before it)
        timestamp_line_idx: int | None = None
        for i, line in enumerate(lines):
            if _TIMESTAMP_RE.search(line):
                timestamp_line_idx = i
                break

        if timestamp_line_idx is None:
            return None

        match = _TIMESTAMP_RE.search(lines[timestamp_line_idx])
        if match is None:
            return None

        start_ms = _timestamp_to_ms(
            match.group(1), match.group(2), match.group(3), match.group(4)
        )
        end_ms = _timestamp_to_ms(
            match.group(5), match.group(6), match.group(7), match.group(8)
        )

        # Text is everything after the timestamp line
        text_lines = lines[timestamp_line_idx + 1 :]
        raw_text = " ".join(line.strip() for line in text_lines if line.strip())
        text = _strip_html_tags(raw_text).strip()

        # Skip empty-text segments
        if not text:
            return None

        # Guard against invalid ranges
        if end_ms <= start_ms:
            return None

        return TranscriptSegment(
            start_ms=start_ms,
            end_ms=end_ms,
            text=text,
            confidence=1.0,
        )
