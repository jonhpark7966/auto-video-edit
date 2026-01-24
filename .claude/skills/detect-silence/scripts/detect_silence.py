#!/usr/bin/env python3
"""Silence detection CLI for Claude Code Skill.

Standalone script - no backend dependencies required.
Detects silent sections using FFmpeg and/or SRT transcript gaps.
Supports multiple combination modes: FFmpeg only, SRT only, AND, OR, DIFF.
Supports tempo-based automatic threshold adjustment.
"""

import argparse
import asyncio
import json
import re
import subprocess
import sys
from datetime import timedelta
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field, model_validator


# =============================================================================
# Models (standalone - no backend dependencies)
# =============================================================================


class TimeRange(BaseModel):
    """Time range in milliseconds."""

    start_ms: int = Field(..., ge=0, description="Start time in milliseconds")
    end_ms: int = Field(..., ge=0, description="End time in milliseconds")

    @model_validator(mode="after")
    def validate_range(self) -> "TimeRange":
        """Ensure end is after start."""
        if self.end_ms <= self.start_ms:
            raise ValueError("end_ms must be greater than start_ms")
        return self

    @property
    def duration_ms(self) -> int:
        """Return duration in milliseconds."""
        return self.end_ms - self.start_ms

    def overlaps(self, other: "TimeRange") -> bool:
        """Check if this range overlaps with another."""
        return self.start_ms < other.end_ms and other.start_ms < self.end_ms


class TranscriptSegment(BaseModel):
    """A single segment of transcription with timing."""

    start_ms: int = Field(..., description="Start time in milliseconds")
    end_ms: int = Field(..., description="End time in milliseconds")
    text: str = Field(..., description="Transcribed text")
    confidence: float = Field(
        default=1.0, ge=0.0, le=1.0, description="Transcription confidence"
    )


class SilenceCombineMode(str, Enum):
    """Mode for combining FFmpeg and SRT-based silence detection."""

    FFMPEG_ONLY = "ffmpeg_only"
    SRT_ONLY = "srt_only"
    AND = "and"
    OR = "or"
    DIFF = "diff"


class SilenceDetectionConfig(BaseModel):
    """Configuration for silence detection."""

    min_silence_ms: int = Field(
        default=500, ge=100, description="Minimum silence duration in milliseconds"
    )
    silence_threshold_db: float = Field(
        default=-40.0, le=0.0, description="Volume threshold for silence in dB"
    )
    padding_before_ms: int = Field(
        default=100, ge=0, description="Padding before speech starts in milliseconds"
    )
    padding_after_ms: int = Field(
        default=100, ge=0, description="Padding after speech ends in milliseconds"
    )
    combine_mode: SilenceCombineMode = Field(
        default=SilenceCombineMode.FFMPEG_ONLY,
        description="How to combine FFmpeg and SRT detection results",
    )
    srt_path: str | None = Field(
        default=None, description="Path to SRT file for gap-based detection"
    )


class SilenceRegion(BaseModel):
    """A detected silence region with metadata."""

    range: TimeRange = Field(..., description="Time range of the silence")
    source: str = Field(..., description="Detection source")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Confidence score")
    ffmpeg_detected: bool = Field(default=False, description="FFmpeg detected this region")
    srt_detected: bool = Field(default=False, description="SRT gap detected this region")

    @property
    def duration_ms(self) -> int:
        """Return duration in milliseconds."""
        return self.range.duration_ms


class SilenceDetectionResult(BaseModel):
    """Result of silence detection."""

    config: SilenceDetectionConfig = Field(..., description="Configuration used")
    silence_regions: list[SilenceRegion] = Field(default_factory=list)
    speech_regions: list[TimeRange] = Field(default_factory=list)
    total_duration_ms: int = Field(default=0)
    total_silence_ms: int = Field(default=0)
    total_speech_ms: int = Field(default=0)

    @property
    def silence_percentage(self) -> float:
        if self.total_duration_ms == 0:
            return 0.0
        return (self.total_silence_ms / self.total_duration_ms) * 100

    @property
    def speech_percentage(self) -> float:
        if self.total_duration_ms == 0:
            return 0.0
        return (self.total_speech_ms / self.total_duration_ms) * 100


# =============================================================================
# Services (standalone - no backend dependencies)
# =============================================================================


class FFmpegAudioAnalyzer:
    """Audio analysis using FFmpeg silencedetect filter."""

    async def detect_silence(
        self,
        audio_path: Path,
        min_silence_ms: int = 500,
        silence_threshold_db: float = -40.0,
    ) -> list[TimeRange]:
        """Detect silent sections using FFmpeg silencedetect."""
        audio_path = Path(audio_path).resolve()
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        min_silence_sec = min_silence_ms / 1000.0

        cmd = [
            "ffmpeg",
            "-i",
            str(audio_path),
            "-af",
            f"silencedetect=noise={silence_threshold_db}dB:d={min_silence_sec}",
            "-f",
            "null",
            "-",
        ]

        result = await asyncio.to_thread(
            subprocess.run, cmd, capture_output=True, text=True
        )

        return self._parse_silence_output(result.stderr)

    def _parse_silence_output(self, stderr: str) -> list[TimeRange]:
        """Parse FFmpeg silencedetect output."""
        silence_ranges: list[TimeRange] = []

        start_pattern = r"silence_start:\s*([\d.]+)"
        end_pattern = r"silence_end:\s*([\d.]+)"

        starts = re.findall(start_pattern, stderr)
        ends = re.findall(end_pattern, stderr)

        for start_str, end_str in zip(starts, ends):
            try:
                start_ms = int(float(start_str) * 1000)
                end_ms = int(float(end_str) * 1000)

                if end_ms > start_ms:
                    silence_ranges.append(TimeRange(start_ms=start_ms, end_ms=end_ms))
            except ValueError:
                continue

        return silence_ranges

    async def get_audio_duration_ms(self, audio_path: Path) -> int:
        """Get audio duration in milliseconds using ffprobe."""
        audio_path = Path(audio_path).resolve()
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        cmd = [
            "ffprobe",
            "-v",
            "quiet",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(audio_path),
        ]

        result = await asyncio.to_thread(
            subprocess.run, cmd, capture_output=True, text=True
        )

        if result.returncode != 0:
            raise RuntimeError(f"ffprobe failed: {result.stderr}")

        try:
            duration_sec = float(result.stdout.strip())
            return int(duration_sec * 1000)
        except ValueError as e:
            raise RuntimeError(f"Failed to parse duration: {result.stdout}") from e


class SrtParser:
    """Parse SRT files and detect gaps between segments."""

    def parse_srt(self, srt_path: Path) -> list[TranscriptSegment]:
        """Parse SRT file into TranscriptSegment list."""
        srt_path = Path(srt_path).resolve()
        if not srt_path.exists():
            raise FileNotFoundError(f"SRT file not found: {srt_path}")

        content = srt_path.read_text(encoding="utf-8")
        segments: list[TranscriptSegment] = []

        blocks = re.split(r"\n\s*\n", content.strip())

        for block in blocks:
            block = block.strip()
            if not block:
                continue

            lines = block.split("\n")
            if len(lines) < 2:
                continue

            timestamp_line = None
            text_start_idx = 0

            for i, line in enumerate(lines):
                if "-->" in line:
                    timestamp_line = line
                    text_start_idx = i + 1
                    break

            if not timestamp_line:
                continue

            match = re.match(
                r"(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})",
                timestamp_line.strip(),
            )
            if not match:
                continue

            start_str, end_str = match.groups()
            start_ms = self._timestamp_to_ms(start_str)
            end_ms = self._timestamp_to_ms(end_str)

            text = "\n".join(lines[text_start_idx:]).strip()

            if end_ms > start_ms:
                segments.append(
                    TranscriptSegment(
                        start_ms=start_ms,
                        end_ms=end_ms,
                        text=text,
                        confidence=1.0,
                    )
                )

        return sorted(segments, key=lambda s: s.start_ms)

    def _timestamp_to_ms(self, timestamp: str) -> int:
        """Convert SRT timestamp (00:00:00,000) to milliseconds."""
        hours, minutes, seconds_ms = timestamp.split(":")
        seconds, ms = seconds_ms.split(",")

        total_ms = (
            int(hours) * 3600000 + int(minutes) * 60000 + int(seconds) * 1000 + int(ms)
        )
        return total_ms

    def detect_gaps(
        self,
        segments: list[TranscriptSegment],
        min_gap_ms: int = 500,
        total_duration_ms: int | None = None,
    ) -> list[TimeRange]:
        """Detect gaps between transcript segments."""
        if not segments:
            if total_duration_ms and total_duration_ms >= min_gap_ms:
                return [TimeRange(start_ms=0, end_ms=total_duration_ms)]
            return []

        gaps: list[TimeRange] = []
        sorted_segments = sorted(segments, key=lambda s: s.start_ms)

        first_start = sorted_segments[0].start_ms
        if first_start >= min_gap_ms:
            gaps.append(TimeRange(start_ms=0, end_ms=first_start))

        for i in range(len(sorted_segments) - 1):
            current_end = sorted_segments[i].end_ms
            next_start = sorted_segments[i + 1].start_ms

            gap_duration = next_start - current_end
            if gap_duration >= min_gap_ms:
                gaps.append(TimeRange(start_ms=current_end, end_ms=next_start))

        if total_duration_ms:
            last_end = sorted_segments[-1].end_ms
            end_gap = total_duration_ms - last_end
            if end_gap >= min_gap_ms:
                gaps.append(TimeRange(start_ms=last_end, end_ms=total_duration_ms))

        return gaps


class SilenceCombiner:
    """Combine multiple silence detection sources."""

    def combine(
        self,
        ffmpeg_silences: list[TimeRange],
        srt_silences: list[TimeRange],
        config: SilenceDetectionConfig,
        total_duration_ms: int,
    ) -> SilenceDetectionResult:
        """Combine silence regions based on configuration mode."""
        mode = config.combine_mode

        if mode == SilenceCombineMode.FFMPEG_ONLY:
            regions = self._merge_overlapping(
                self._from_timeranges(ffmpeg_silences, "ffmpeg", ffmpeg=True)
            )
        elif mode == SilenceCombineMode.SRT_ONLY:
            regions = self._merge_overlapping(
                self._from_timeranges(srt_silences, "srt", srt=True)
            )
        elif mode == SilenceCombineMode.AND:
            regions = self._combine_and(ffmpeg_silences, srt_silences)
        elif mode == SilenceCombineMode.OR:
            regions = self._combine_or(ffmpeg_silences, srt_silences)
        elif mode == SilenceCombineMode.DIFF:
            regions = self._combine_diff(ffmpeg_silences, srt_silences)
        else:
            regions = []

        padded_regions = self._apply_padding(
            regions,
            config.padding_before_ms,
            config.padding_after_ms,
            total_duration_ms,
        )

        speech_regions = self._invert_regions(padded_regions, total_duration_ms)

        total_silence = sum(r.range.duration_ms for r in padded_regions)
        total_speech = total_duration_ms - total_silence

        return SilenceDetectionResult(
            config=config,
            silence_regions=padded_regions,
            speech_regions=speech_regions,
            total_duration_ms=total_duration_ms,
            total_silence_ms=total_silence,
            total_speech_ms=total_speech,
        )

    def _combine_and(
        self,
        ffmpeg: list[TimeRange],
        srt: list[TimeRange],
    ) -> list[SilenceRegion]:
        """AND mode: Only include if both agree (intersection)."""
        regions: list[SilenceRegion] = []

        for ff_range in ffmpeg:
            for srt_range in srt:
                if ff_range.overlaps(srt_range):
                    intersect_start = max(ff_range.start_ms, srt_range.start_ms)
                    intersect_end = min(ff_range.end_ms, srt_range.end_ms)

                    if intersect_end > intersect_start:
                        regions.append(
                            SilenceRegion(
                                range=TimeRange(
                                    start_ms=intersect_start, end_ms=intersect_end
                                ),
                                source="combined",
                                confidence=1.0,
                                ffmpeg_detected=True,
                                srt_detected=True,
                            )
                        )

        return self._merge_overlapping(regions)

    def _combine_or(
        self,
        ffmpeg: list[TimeRange],
        srt: list[TimeRange],
    ) -> list[SilenceRegion]:
        """OR mode: Include if either detects (union)."""
        regions: list[SilenceRegion] = []

        for ff_range in ffmpeg:
            has_srt_overlap = any(ff_range.overlaps(s) for s in srt)
            regions.append(
                SilenceRegion(
                    range=ff_range,
                    source="ffmpeg" if not has_srt_overlap else "combined",
                    confidence=1.0 if has_srt_overlap else 0.8,
                    ffmpeg_detected=True,
                    srt_detected=has_srt_overlap,
                )
            )

        for srt_range in srt:
            if not any(srt_range.overlaps(ff) for ff in ffmpeg):
                regions.append(
                    SilenceRegion(
                        range=srt_range,
                        source="srt",
                        confidence=0.8,
                        ffmpeg_detected=False,
                        srt_detected=True,
                    )
                )

        return self._merge_overlapping(regions)

    def _combine_diff(
        self,
        ffmpeg: list[TimeRange],
        srt: list[TimeRange],
    ) -> list[SilenceRegion]:
        """DIFF mode: Return regions where methods disagree."""
        regions: list[SilenceRegion] = []

        for ff_range in ffmpeg:
            if not any(ff_range.overlaps(s) for s in srt):
                regions.append(
                    SilenceRegion(
                        range=ff_range,
                        source="ffmpeg_only",
                        confidence=0.5,
                        ffmpeg_detected=True,
                        srt_detected=False,
                    )
                )

        for srt_range in srt:
            if not any(srt_range.overlaps(ff) for ff in ffmpeg):
                regions.append(
                    SilenceRegion(
                        range=srt_range,
                        source="srt_only",
                        confidence=0.5,
                        ffmpeg_detected=False,
                        srt_detected=True,
                    )
                )

        return sorted(regions, key=lambda r: r.range.start_ms)

    def _apply_padding(
        self,
        regions: list[SilenceRegion],
        padding_before: int,
        padding_after: int,
        total_duration: int,
    ) -> list[SilenceRegion]:
        """Apply padding to silence regions (shrink them to keep speech margins)."""
        padded: list[SilenceRegion] = []

        for region in regions:
            new_start = region.range.start_ms + padding_after
            new_end = region.range.end_ms - padding_before

            new_start = max(0, new_start)
            new_end = min(total_duration, new_end)

            if new_end > new_start:
                padded.append(
                    SilenceRegion(
                        range=TimeRange(start_ms=new_start, end_ms=new_end),
                        source=region.source,
                        confidence=region.confidence,
                        ffmpeg_detected=region.ffmpeg_detected,
                        srt_detected=region.srt_detected,
                    )
                )

        return padded

    def _invert_regions(
        self,
        silences: list[SilenceRegion],
        total_duration: int,
    ) -> list[TimeRange]:
        """Calculate speech regions (inverse of silence)."""
        if not silences:
            return [TimeRange(start_ms=0, end_ms=total_duration)]

        speech: list[TimeRange] = []
        sorted_silences = sorted(silences, key=lambda r: r.range.start_ms)

        first_start = sorted_silences[0].range.start_ms
        if first_start > 0:
            speech.append(TimeRange(start_ms=0, end_ms=first_start))

        for i in range(len(sorted_silences) - 1):
            gap_start = sorted_silences[i].range.end_ms
            gap_end = sorted_silences[i + 1].range.start_ms
            if gap_end > gap_start:
                speech.append(TimeRange(start_ms=gap_start, end_ms=gap_end))

        last_end = sorted_silences[-1].range.end_ms
        if last_end < total_duration:
            speech.append(TimeRange(start_ms=last_end, end_ms=total_duration))

        return speech

    def _from_timeranges(
        self,
        ranges: list[TimeRange],
        source: str,
        ffmpeg: bool = False,
        srt: bool = False,
    ) -> list[SilenceRegion]:
        """Convert TimeRanges to SilenceRegions."""
        return [
            SilenceRegion(
                range=r,
                source=source,
                confidence=1.0,
                ffmpeg_detected=ffmpeg,
                srt_detected=srt,
            )
            for r in ranges
        ]

    def _merge_overlapping(
        self,
        regions: list[SilenceRegion],
    ) -> list[SilenceRegion]:
        """Merge overlapping or adjacent regions."""
        if not regions:
            return []

        sorted_regions = sorted(regions, key=lambda r: r.range.start_ms)
        merged: list[SilenceRegion] = [sorted_regions[0]]

        for current in sorted_regions[1:]:
            last = merged[-1]

            if current.range.start_ms <= last.range.end_ms:
                merged[-1] = SilenceRegion(
                    range=TimeRange(
                        start_ms=last.range.start_ms,
                        end_ms=max(last.range.end_ms, current.range.end_ms),
                    ),
                    source="combined",
                    confidence=max(last.confidence, current.confidence),
                    ffmpeg_detected=last.ffmpeg_detected or current.ffmpeg_detected,
                    srt_detected=last.srt_detected or current.srt_detected,
                )
            else:
                merged.append(current)

        return merged


# =============================================================================
# CLI Logic
# =============================================================================

# Tempo presets: factor for dynamic range based threshold
# threshold = mean_volume - dynamic_range * factor
# where dynamic_range = max_volume - mean_volume
TEMPO_PRESETS = {
    "tight": 0.3,    # 공격적: threshold가 mean에 가까움 → 최대한 무음 제거
    "normal": 0.5,   # 기본: 중간
    "relaxed": 0.8,  # 보수적: threshold가 낮음 → 확실한 무음만
}


async def analyze_volume(media_path: Path) -> dict[str, float]:
    """Analyze audio volume using FFmpeg volumedetect."""
    cmd = [
        "ffmpeg", "-i", str(media_path),
        "-af", "volumedetect",
        "-f", "null", "-"
    ]

    result = await asyncio.to_thread(
        subprocess.run, cmd, capture_output=True, text=True
    )

    mean_match = re.search(r"mean_volume:\s*([-\d.]+)\s*dB", result.stderr)
    max_match = re.search(r"max_volume:\s*([-\d.]+)\s*dB", result.stderr)

    return {
        "mean_volume": float(mean_match.group(1)) if mean_match else -40.0,
        "max_volume": float(max_match.group(1)) if max_match else -10.0,
    }


def calculate_threshold(volume_info: dict[str, float], tempo: str | float) -> float:
    """Calculate threshold based on volume analysis and tempo.

    Uses dynamic range (max - mean) to adapt to different audio characteristics:
    - Quiet recording with wide dynamic range → lower threshold
    - Noisy environment with narrow dynamic range → higher threshold

    Formula: threshold = mean_volume - dynamic_range * factor
    """
    mean_vol = volume_info["mean_volume"]
    max_vol = volume_info["max_volume"]
    dynamic_range = max_vol - mean_vol

    # Get factor from preset or use as direct value
    if isinstance(tempo, str) and tempo in TEMPO_PRESETS:
        factor = TEMPO_PRESETS[tempo]
    else:
        try:
            factor = float(tempo)
            # If numeric value looks like old offset format (negative), convert
            if factor < 0:
                # Legacy compatibility: treat negative values as offset from mean
                threshold = mean_vol + factor
                threshold = max(-60.0, min(-20.0, threshold))
                return round(threshold, 1)
        except (ValueError, TypeError):
            factor = TEMPO_PRESETS["normal"]

    # Calculate threshold using dynamic range
    threshold = mean_vol - (dynamic_range * factor)

    # Clamp to reasonable bounds
    threshold = max(-60.0, min(-20.0, threshold))

    return round(threshold, 1)


def ms_to_timestamp(ms: int) -> str:
    """Convert milliseconds to HH:MM:SS.mmm format."""
    td = timedelta(milliseconds=ms)
    total_seconds = int(td.total_seconds())
    milliseconds = ms % 1000
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}"


def mode_to_enum(mode: str) -> SilenceCombineMode:
    """Convert mode string to enum."""
    mapping = {
        "ffmpeg": SilenceCombineMode.FFMPEG_ONLY,
        "srt": SilenceCombineMode.SRT_ONLY,
        "and": SilenceCombineMode.AND,
        "or": SilenceCombineMode.OR,
        "diff": SilenceCombineMode.DIFF,
    }
    return mapping.get(mode.lower(), SilenceCombineMode.FFMPEG_ONLY)


async def detect_silence(
    media_file: str,
    srt_file: str | None = None,
    threshold_db: float | None = None,
    min_duration_ms: int = 500,
    padding_ms: int = 100,
    mode: str = "ffmpeg",
    output_file: str = "silence_result.json",
    tempo: str | None = None,
) -> dict:
    """Run silence detection with specified parameters."""
    media_path = Path(media_file).resolve()

    if not media_path.exists():
        print(f"ERROR: File not found: {media_path}", file=sys.stderr)
        sys.exit(1)

    # Initialize services
    analyzer = FFmpegAudioAnalyzer()
    parser = SrtParser()
    combiner = SilenceCombiner()

    # Analyze volume if tempo is specified or threshold is not set
    volume_info = None
    if tempo or threshold_db is None:
        print("Analyzing volume levels...")
        volume_info = await analyze_volume(media_path)
        dynamic_range = volume_info["max_volume"] - volume_info["mean_volume"]
        volume_info["dynamic_range"] = dynamic_range

        print(f"  Mean:          {volume_info['mean_volume']:.1f} dB")
        print(f"  Max:           {volume_info['max_volume']:.1f} dB")
        print(f"  Dynamic Range: {dynamic_range:.1f} dB")

        if tempo:
            threshold_db = calculate_threshold(volume_info, tempo)
            if isinstance(tempo, str) and tempo in TEMPO_PRESETS:
                factor = TEMPO_PRESETS[tempo]
                print(f"  Tempo '{tempo}' (factor={factor}) → Threshold: {threshold_db} dB")
            else:
                print(f"  Custom factor {tempo} → Threshold: {threshold_db} dB")
        elif threshold_db is None:
            threshold_db = -40.0  # fallback

    # Print config
    print("=" * 60)
    print("SILENCE DETECTION")
    print("=" * 60)
    print(f"File:         {media_path.name}")
    print(f"Mode:         {mode.upper()}")
    if tempo:
        print(f"Tempo:        {tempo}")
    print(f"Threshold:    {threshold_db} dB")
    print(f"Min Duration: {min_duration_ms} ms")
    print(f"Padding:      {padding_ms} ms")
    if srt_file:
        print(f"SRT File:     {srt_file}")
    print("-" * 60)

    # Get media duration
    try:
        duration_ms = await analyzer.get_audio_duration_ms(media_path)
        print(f"Duration:     {ms_to_timestamp(duration_ms)}")
    except Exception as e:
        print(f"ERROR: Failed to get duration: {e}", file=sys.stderr)
        sys.exit(1)

    # Step 1: FFmpeg detection
    print("\n[1/3] Running FFmpeg silence detection...")
    try:
        ffmpeg_silences = await analyzer.detect_silence(
            media_path,
            min_silence_ms=min_duration_ms,
            silence_threshold_db=threshold_db,
        )
        print(f"      Found {len(ffmpeg_silences)} regions")
    except Exception as e:
        print(f"ERROR: FFmpeg detection failed: {e}", file=sys.stderr)
        sys.exit(1)

    # Step 2: SRT gap detection (if provided)
    srt_silences = []
    if srt_file:
        srt_path = Path(srt_file).resolve()
        if not srt_path.exists():
            print(f"WARNING: SRT file not found: {srt_path}", file=sys.stderr)
        else:
            print("\n[2/3] Analyzing SRT gaps...")
            try:
                segments = parser.parse_srt(srt_path)
                srt_silences = parser.detect_gaps(
                    segments,
                    min_gap_ms=min_duration_ms,
                    total_duration_ms=duration_ms,
                )
                print(f"      Found {len(srt_silences)} gaps")
            except Exception as e:
                print(f"WARNING: SRT parsing failed: {e}", file=sys.stderr)
    else:
        print("\n[2/3] Skipping SRT analysis (no file provided)")

    # Step 3: Combine results
    print("\n[3/3] Combining results...")
    config = SilenceDetectionConfig(
        min_silence_ms=min_duration_ms,
        silence_threshold_db=threshold_db,
        padding_before_ms=padding_ms,
        padding_after_ms=padding_ms,
        combine_mode=mode_to_enum(mode),
        srt_path=srt_file,
    )

    result = combiner.combine(
        ffmpeg_silences,
        srt_silences,
        config,
        duration_ms,
    )

    # Prepare output data
    output_data = {
        "input_file": str(media_path),
        "srt_file": srt_file,
        "duration_ms": duration_ms,
        "volume_analysis": volume_info,
        "config": {
            "tempo": tempo,
            "threshold_db": threshold_db,
            "min_duration_ms": min_duration_ms,
            "padding_ms": padding_ms,
            "mode": mode,
        },
        "detection_sources": {
            "ffmpeg_regions": len(ffmpeg_silences),
            "srt_regions": len(srt_silences),
        },
        "silence_regions": [
            {
                "start_ms": r.range.start_ms,
                "end_ms": r.range.end_ms,
                "duration_ms": r.range.duration_ms,
                "source": r.source,
                "confidence": r.confidence,
                "ffmpeg_detected": r.ffmpeg_detected,
                "srt_detected": r.srt_detected,
            }
            for r in result.silence_regions
        ],
        "speech_regions": [
            {
                "start_ms": r.start_ms,
                "end_ms": r.end_ms,
                "duration_ms": r.duration_ms,
            }
            for r in result.speech_regions
        ],
        "statistics": {
            "silence_count": len(result.silence_regions),
            "silence_ms": result.total_silence_ms,
            "silence_percent": round(result.silence_percentage, 2),
            "speech_ms": result.total_speech_ms,
            "speech_percent": round(result.speech_percentage, 2),
        },
    }

    # Save JSON
    output_path = Path(output_file)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)

    # Print summary
    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)
    print(f"Silence Regions: {len(result.silence_regions)}")
    print(
        f"Total Silence:   {ms_to_timestamp(result.total_silence_ms)} "
        f"({result.silence_percentage:.1f}%)"
    )
    print(
        f"Total Speech:    {ms_to_timestamp(result.total_speech_ms)} "
        f"({result.speech_percentage:.1f}%)"
    )
    print("-" * 60)

    if result.silence_regions:
        print("\nSILENCE REGIONS (after padding):")
        for i, r in enumerate(result.silence_regions[:15], 1):
            source_info = ""
            if mode in ("and", "or", "diff"):
                flags = []
                if r.ffmpeg_detected:
                    flags.append("FFmpeg")
                if r.srt_detected:
                    flags.append("SRT")
                source_info = f" [{'+'.join(flags)}]"
            print(
                f"  {i:2d}. {ms_to_timestamp(r.range.start_ms)} -> "
                f"{ms_to_timestamp(r.range.end_ms)} "
                f"({r.range.duration_ms:5d}ms){source_info}"
            )
        if len(result.silence_regions) > 15:
            print(f"  ... and {len(result.silence_regions) - 15} more")

    print(f"\nOutput saved: {output_path.absolute()}")
    print("=" * 60)

    return output_data


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Detect silent sections in audio/video files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s video.mp4
  %(prog)s video.mp4 --srt subtitles.srt --mode and
  %(prog)s audio.wav --threshold -35 --min-duration 300
  %(prog)s interview.mp4 --srt transcript.srt --mode diff
        """,
    )
    parser.add_argument("media_file", help="Path to audio or video file")
    parser.add_argument(
        "--srt",
        type=str,
        default=None,
        help="SRT file for gap-based detection",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=None,
        help="Silence threshold in dB (default: auto or -40)",
    )
    parser.add_argument(
        "--tempo",
        type=str,
        default=None,
        help="Tempo preset: relaxed (보수적), normal (기본), tight (공격적), or numeric offset",
    )
    parser.add_argument(
        "--min-duration",
        type=int,
        default=500,
        help="Minimum silence duration in ms (default: 500)",
    )
    parser.add_argument(
        "--padding",
        type=int,
        default=100,
        help="Padding before/after speech in ms (default: 100)",
    )
    parser.add_argument(
        "--mode",
        type=str,
        default="ffmpeg",
        choices=["ffmpeg", "srt", "and", "or", "diff"],
        help="Detection mode (default: ffmpeg)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="silence_result.json",
        help="Output JSON filename (default: silence_result.json)",
    )

    args = parser.parse_args()

    # Validate mode
    if args.mode in ("srt", "and", "or", "diff") and not args.srt:
        parser.error(f"--srt is required for mode '{args.mode}'")

    # Run detection
    asyncio.run(
        detect_silence(
            media_file=args.media_file,
            srt_file=args.srt,
            threshold_db=args.threshold,
            min_duration_ms=args.min_duration,
            padding_ms=args.padding,
            mode=args.mode,
            output_file=args.output,
            tempo=args.tempo,
        )
    )


if __name__ == "__main__":
    main()
