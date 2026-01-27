"""Audio analysis service using FFmpeg and SRT gap detection.

Provides silence detection via FFmpeg silencedetect filter,
SRT subtitle gap analysis, and combined detection modes.
"""

import asyncio
import json
import re
import subprocess
from pathlib import Path

from avid.errors import FFmpegError
from avid.models.silence import SilenceDetectionResult, SilenceRegion
from avid.services.srt_parser import SRTParser

# FFmpeg silencedetect output patterns
_SILENCE_START_RE = re.compile(
    r"\[silencedetect\s*@\s*[0-9a-fx]+\]\s*silence_start:\s*([\d.]+)"
)
_SILENCE_END_RE = re.compile(
    r"\[silencedetect\s*@\s*[0-9a-fx]+\]\s*silence_end:\s*([\d.]+)"
)


class AudioAnalyzer:
    """Audio analysis service for silence detection and volume analysis.

    Combines FFmpeg-based audio analysis with SRT subtitle gap detection
    to provide robust silence region identification.

    Implements the IAudioAnalyzer protocol interface and extends it with
    SRT-aware combined detection.
    """

    def __init__(self) -> None:
        self._srt_parser = SRTParser()

    async def detect_silence(
        self,
        audio_path: Path,
        srt_path: Path | None = None,
        min_silence_ms: int = 500,
        silence_threshold_db: float = -40.0,
        padding_ms: int = 100,
        tight_mode: bool = True,
    ) -> SilenceDetectionResult:
        """Detect silence in audio, optionally combining with SRT gap analysis.

        Args:
            audio_path: Path to the audio/video file
            srt_path: Optional path to SRT subtitle file for gap analysis
            min_silence_ms: Minimum silence duration to detect (ms)
            silence_threshold_db: Volume threshold for silence (dB)
            padding_ms: Padding to add around each region boundary (ms)
            tight_mode: If True use intersection (tight), else union (or)

        Returns:
            SilenceDetectionResult with combined and per-source regions

        Raises:
            FFmpegError: If FFmpeg execution fails
            FileNotFoundError: If audio_path does not exist
        """
        audio_path = Path(audio_path)
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        # Run FFmpeg silence detection
        ffmpeg_regions = await self._detect_ffmpeg_silence(
            audio_path, min_silence_ms, silence_threshold_db
        )

        # Apply padding to FFmpeg regions
        if padding_ms > 0:
            ffmpeg_regions = self._apply_padding(ffmpeg_regions, padding_ms)

        # Get total duration
        total_duration_ms = await self._get_duration_ms(audio_path)

        # SRT gap detection (if SRT provided)
        srt_gaps: list[SilenceRegion] = []
        if srt_path is not None:
            srt_path = Path(srt_path)
            srt_gaps = self._srt_parser.detect_gaps(srt_path, min_gap_ms=min_silence_ms)

        # Combine results
        if srt_path is not None and srt_gaps:
            if tight_mode:
                combined = self._combine_tight(ffmpeg_regions, srt_gaps)
            else:
                combined = self._combine_or(ffmpeg_regions, srt_gaps)
        else:
            # No SRT — FFmpeg regions are the final result
            combined = ffmpeg_regions

        return SilenceDetectionResult(
            silence_regions=sorted(combined, key=lambda r: r.start_ms),
            ffmpeg_regions=sorted(ffmpeg_regions, key=lambda r: r.start_ms),
            srt_gaps=sorted(srt_gaps, key=lambda r: r.start_ms),
            total_duration_ms=total_duration_ms,
        )

    async def get_volume_levels(
        self,
        audio_path: Path,
        window_ms: int = 100,
    ) -> list[tuple[int, float]]:
        """Get volume levels over time using FFmpeg astats filter.

        Args:
            audio_path: Path to audio file
            window_ms: Analysis window size in milliseconds

        Returns:
            List of (timestamp_ms, volume_db) tuples

        Raises:
            FFmpegError: If FFmpeg execution fails
            FileNotFoundError: If audio_path does not exist
        """
        audio_path = Path(audio_path)
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        window_sec = window_ms / 1000.0

        cmd = [
            "ffmpeg",
            "-i", str(audio_path),
            "-af", f"astats=metadata=1:reset={window_sec},ametadata=print:key=lavfi.astats.Overall.RMS_level",
            "-f", "null",
            "-",
        ]

        result = await asyncio.to_thread(
            subprocess.run, cmd, capture_output=True, text=True
        )

        if result.returncode != 0:
            raise FFmpegError(f"FFmpeg volume analysis failed: {result.stderr}")

        return self._parse_volume_output(result.stderr, window_ms)

    # ------------------------------------------------------------------
    # Internal: FFmpeg silence detection
    # ------------------------------------------------------------------

    async def _detect_ffmpeg_silence(
        self,
        audio_path: Path,
        min_silence_ms: int,
        silence_threshold_db: float,
    ) -> list[SilenceRegion]:
        """Run FFmpeg silencedetect and parse output.

        Args:
            audio_path: Path to audio file
            min_silence_ms: Minimum silence duration (ms)
            silence_threshold_db: Silence threshold (dB)

        Returns:
            List of SilenceRegion from FFmpeg

        Raises:
            FFmpegError: If FFmpeg fails
        """
        min_silence_sec = min_silence_ms / 1000.0

        cmd = [
            "ffmpeg",
            "-i", str(audio_path),
            "-af", f"silencedetect=noise={silence_threshold_db}dB:d={min_silence_sec}",
            "-f", "null",
            "-",
        ]

        result = await asyncio.to_thread(
            subprocess.run, cmd, capture_output=True, text=True
        )

        if result.returncode != 0:
            raise FFmpegError(f"FFmpeg silencedetect failed: {result.stderr}")

        return self._parse_silencedetect_output(result.stderr)

    def _parse_silencedetect_output(self, stderr: str) -> list[SilenceRegion]:
        """Parse FFmpeg silencedetect stderr output.

        Expected format:
            [silencedetect @ 0x...] silence_start: 1.234
            [silencedetect @ 0x...] silence_end: 2.567 | silence_duration: 1.333

        Handles unpaired silence_start at end of file (silence extends to EOF).
        """
        starts: list[float] = []
        ends: list[float] = []

        for line in stderr.split("\n"):
            start_match = _SILENCE_START_RE.search(line)
            if start_match:
                starts.append(float(start_match.group(1)))
                continue

            end_match = _SILENCE_END_RE.search(line)
            if end_match:
                ends.append(float(end_match.group(1)))

        regions: list[SilenceRegion] = []
        for i, start_sec in enumerate(starts):
            if i < len(ends):
                end_sec = ends[i]
            else:
                # Unpaired start — silence goes to end of file; skip it
                # (we don't know the total duration here, caller handles it)
                continue

            start_ms = int(start_sec * 1000)
            end_ms = int(end_sec * 1000)

            if end_ms > start_ms:
                regions.append(
                    SilenceRegion(
                        start_ms=start_ms,
                        end_ms=end_ms,
                        source="ffmpeg",
                        confidence=1.0,
                    )
                )

        return regions

    # ------------------------------------------------------------------
    # Internal: Volume output parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_volume_output(
        stderr: str,
        window_ms: int,
    ) -> list[tuple[int, float]]:
        """Parse FFmpeg astats metadata output into (timestamp_ms, db) tuples."""
        rms_re = re.compile(
            r"lavfi\.astats\.Overall\.RMS_level=(-?[\d.]+|-inf)"
        )

        levels: list[tuple[int, float]] = []
        timestamp_ms = 0

        for line in stderr.split("\n"):
            match = rms_re.search(line)
            if match:
                value = match.group(1)
                db = -96.0 if value == "-inf" else float(value)
                levels.append((timestamp_ms, db))
                timestamp_ms += window_ms

        return levels

    # ------------------------------------------------------------------
    # Internal: Duration helper
    # ------------------------------------------------------------------

    async def _get_duration_ms(self, audio_path: Path) -> int:
        """Get total duration of a media file in milliseconds via ffprobe."""
        cmd = [
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            str(audio_path),
        ]

        result = await asyncio.to_thread(
            subprocess.run, cmd, capture_output=True, text=True
        )

        if result.returncode != 0:
            raise FFmpegError(f"ffprobe failed: {result.stderr}")

        data = json.loads(result.stdout)
        duration_sec = float(data.get("format", {}).get("duration", 0))
        return int(duration_sec * 1000)

    # ------------------------------------------------------------------
    # Internal: Combining strategies
    # ------------------------------------------------------------------

    @staticmethod
    def _combine_or(
        ffmpeg_regions: list[SilenceRegion],
        srt_gaps: list[SilenceRegion],
    ) -> list[SilenceRegion]:
        """Union of FFmpeg and SRT regions.

        Merges overlapping regions into single combined regions.
        Any region from either source is included.
        """
        all_regions = ffmpeg_regions + srt_gaps
        if not all_regions:
            return []

        # Sort by start time
        sorted_regions = sorted(all_regions, key=lambda r: r.start_ms)

        merged: list[SilenceRegion] = []
        current_start = sorted_regions[0].start_ms
        current_end = sorted_regions[0].end_ms

        for region in sorted_regions[1:]:
            if region.start_ms <= current_end:
                # Overlapping or adjacent — extend
                current_end = max(current_end, region.end_ms)
            else:
                # Gap — emit current and start new
                merged.append(
                    SilenceRegion(
                        start_ms=current_start,
                        end_ms=current_end,
                        source="combined",
                        confidence=0.8,
                    )
                )
                current_start = region.start_ms
                current_end = region.end_ms

        # Emit last region
        merged.append(
            SilenceRegion(
                start_ms=current_start,
                end_ms=current_end,
                source="combined",
                confidence=0.8,
            )
        )

        return merged

    @staticmethod
    def _combine_tight(
        ffmpeg_regions: list[SilenceRegion],
        srt_gaps: list[SilenceRegion],
    ) -> list[SilenceRegion]:
        """Intersection of FFmpeg and SRT regions.

        Only keeps time ranges where both sources agree silence exists.
        This produces higher-confidence results.
        """
        if not ffmpeg_regions or not srt_gaps:
            return []

        intersections: list[SilenceRegion] = []

        for ffmpeg_r in ffmpeg_regions:
            for srt_r in srt_gaps:
                # Compute overlap
                overlap_start = max(ffmpeg_r.start_ms, srt_r.start_ms)
                overlap_end = min(ffmpeg_r.end_ms, srt_r.end_ms)

                if overlap_start < overlap_end:
                    intersections.append(
                        SilenceRegion(
                            start_ms=overlap_start,
                            end_ms=overlap_end,
                            source="combined",
                            confidence=0.95,
                        )
                    )

        return sorted(intersections, key=lambda r: r.start_ms)

    # ------------------------------------------------------------------
    # Internal: Padding
    # ------------------------------------------------------------------

    @staticmethod
    def _apply_padding(
        regions: list[SilenceRegion],
        padding_ms: int,
    ) -> list[SilenceRegion]:
        """Shrink silence regions by padding_ms on each side.

        This preserves a small buffer of audio around detected silence
        boundaries to avoid clipping speech.
        """
        padded: list[SilenceRegion] = []
        for region in regions:
            new_start = region.start_ms + padding_ms
            new_end = region.end_ms - padding_ms

            if new_end > new_start:
                padded.append(
                    SilenceRegion(
                        start_ms=new_start,
                        end_ms=new_end,
                        source=region.source,
                        confidence=region.confidence,
                    )
                )

        return padded
