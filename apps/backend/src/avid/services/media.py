"""Media service implementation using FFmpeg."""

import asyncio
import json
import re
import subprocess
from fractions import Fraction
from pathlib import Path

from avid.models.media import MediaFile, MediaInfo


def _int_or_none(value: object) -> int | None:
    try:
        return int(value) or None
    except (TypeError, ValueError):
        return None


def _float_or_none(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _rate_to_float(value: object) -> float | None:
    if not isinstance(value, str) or not value:
        return _float_or_none(value)
    if "/" not in value:
        return _float_or_none(value)

    try:
        num, den = value.split("/", 1)
        den_float = float(den)
        if den_float == 0:
            return None
        parsed = float(num) / den_float
    except ValueError:
        return None
    return parsed if parsed > 0 else None


def _rate_to_fraction(value: object) -> Fraction | None:
    if not isinstance(value, str) or not value or "/" not in value:
        return None

    try:
        num, den = value.split("/", 1)
        fraction = Fraction(int(num), int(den))
    except (ValueError, ZeroDivisionError):
        return None
    return fraction if fraction > 0 else None


def _frame_count_from_seconds(value: object, fps: Fraction) -> int | None:
    try:
        duration = Fraction(str(value))
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    if duration <= 0:
        return None
    return round(duration * fps)


def _duration_fraction_from_stream(stream: dict) -> Fraction | None:
    duration_ts = _int_or_none(stream.get("duration_ts"))
    stream_time_base = _rate_to_fraction(stream.get("time_base"))
    if duration_ts is not None and stream_time_base:
        duration = duration_ts * stream_time_base
        if duration > 0:
            return duration

    try:
        duration = Fraction(str(stream.get("duration")))
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    return duration if duration > 0 else None


def _duration_ms(duration: Fraction) -> int:
    return int(duration * 1000)


def _stream_timecode(stream: dict) -> str | None:
    tags = stream.get("tags") if isinstance(stream.get("tags"), dict) else {}
    value = tags.get("timecode") or tags.get("TIMECODE")
    return str(value).strip() if value else None


def _data_stream_kind(stream: dict) -> str | None:
    value = stream.get("codec_tag_string")
    if not value:
        return None
    kind = str(value).strip().lower()
    return kind if kind in {"tmcd", "rtmd"} else None


def _extract_timecode_info(payload: dict) -> tuple[str | None, str | None]:
    streams = payload.get("streams") or []
    for stream in streams:
        if stream.get("codec_type") == "video":
            value = _stream_timecode(stream)
            if value:
                return value, "video"
    for expected_kind in ("tmcd", "rtmd"):
        for stream in streams:
            if stream.get("codec_type") != "data":
                continue
            if _data_stream_kind(stream) != expected_kind:
                continue
            value = _stream_timecode(stream)
            if value:
                return value, expected_kind
    format_tags = payload.get("format", {}).get("tags")
    if isinstance(format_tags, dict):
        value = format_tags.get("timecode") or format_tags.get("TIMECODE")
        if value:
            return str(value).strip(), "format"
    return None, None


def _extract_timecode(payload: dict) -> str | None:
    return _extract_timecode_info(payload)[0]


def _parse_timecode_start(timecode: str, rate: Fraction) -> tuple[int, str] | None:
    match = re.match(r"^(\d+):(\d{2}):(\d{2})[:;](\d{2})$", timecode.strip())
    if not match or rate <= 0:
        return None
    hours, minutes, seconds, frames = (int(part) for part in match.groups())
    nominal_fps = int(round(float(rate)))
    if nominal_fps <= 0 or frames >= nominal_fps:
        return None
    total_frames = ((hours * 3600 + minutes * 60 + seconds) * nominal_fps) + frames
    start_units = total_frames * rate.denominator
    return total_frames, f"{start_units}/{rate.numerator}"


class MediaService:
    """FFmpeg-based media operations service."""

    async def get_media_info(self, path: Path) -> MediaInfo:
        """Extract media information using ffprobe.

        Args:
            path: Path to the media file

        Returns:
            MediaInfo with duration, resolution, fps, etc.
        """
        cmd = [
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-count_frames",
            "-show_format",
            "-show_streams",
            str(path),
        ]

        result = await asyncio.to_thread(
            subprocess.run, cmd, capture_output=True, text=True
        )

        if result.returncode != 0:
            raise RuntimeError(f"ffprobe failed: {result.stderr}")

        data = json.loads(result.stdout)
        streams = data.get("streams", [])

        # Extract duration from format
        format_duration = data.get("format", {}).get("duration")
        duration_sec = _float_or_none(format_duration) or 0
        format_duration_ms = int(duration_sec * 1000)
        video_duration_ms = None

        # Find video and audio streams
        width = None
        height = None
        fps = None
        sample_rate = None
        sample_rates: set[int] = set()
        audio_channels = 0
        audio_sources = 0
        audio_sample_count = None
        video_frame_count = None
        frame_duration = None
        video_duration = None
        start_time = data.get("format", {}).get("start_time")
        time_base = None
        timecode_rate_fraction = None

        for stream in streams:
            if stream.get("codec_type") == "video":
                width = stream.get("width")
                height = stream.get("height")
                # Parse frame rate (e.g., "30/1" or "30000/1001")
                fps_fraction = _rate_to_fraction(
                    stream.get("avg_frame_rate")
                ) or _rate_to_fraction(stream.get("r_frame_rate"))
                fps = float(fps_fraction) if fps_fraction else (
                    _rate_to_float(stream.get("avg_frame_rate"))
                    or _rate_to_float(stream.get("r_frame_rate"))
                )
                timecode_rate_fraction = (
                    _rate_to_fraction(stream.get("r_frame_rate")) or fps_fraction
                )
                if fps_fraction:
                    frame_duration = f"{fps_fraction.denominator}/{fps_fraction.numerator}"
                time_base = stream.get("time_base")
                stream_duration = _duration_fraction_from_stream(stream)
                if stream_duration is not None:
                    video_duration = f"{stream_duration.numerator}/{stream_duration.denominator}"
                    video_duration_ms = _duration_ms(stream_duration)
                video_frame_count = _int_or_none(stream.get("nb_frames")) or _int_or_none(
                    stream.get("nb_read_frames")
                )
                if video_frame_count is None and fps_fraction is not None:
                    duration_ts = _int_or_none(stream.get("duration_ts"))
                    stream_time_base = _rate_to_fraction(stream.get("time_base"))
                    if duration_ts is not None and stream_time_base:
                        video_frame_count = round(
                            duration_ts * stream_time_base * fps_fraction
                        )
                    if video_frame_count is None:
                        video_frame_count = _frame_count_from_seconds(
                            stream.get("duration"), fps_fraction
                        )
                if video_frame_count is not None and fps_fraction is not None:
                    duration = Fraction(video_frame_count, 1) / fps_fraction
                    video_duration = f"{duration.numerator}/{duration.denominator}"
                    video_duration_ms = _duration_ms(duration)
            elif stream.get("codec_type") == "audio":
                audio_sources += 1
                rate = _int_or_none(stream.get("sample_rate"))
                if rate:
                    sample_rates.add(rate)
                audio_channels += _int_or_none(stream.get("channels")) or 0
                duration_ts = _int_or_none(stream.get("duration_ts"))
                if duration_ts is not None:
                    audio_sample_count = duration_ts

        if len(sample_rates) == 1:
            sample_rate = next(iter(sample_rates))

        timecode, timecode_source_kind = _extract_timecode_info(data)
        timecode_rate = (
            f"{timecode_rate_fraction.numerator}/{timecode_rate_fraction.denominator}"
            if timecode_rate_fraction else None
        )
        parsed_timecode = (
            _parse_timecode_start(timecode, timecode_rate_fraction)
            if timecode and timecode_rate_fraction else None
        )
        timecode_start_frames = parsed_timecode[0] if parsed_timecode else None
        timecode_start_seconds = parsed_timecode[1] if parsed_timecode else None
        fcpxml_timecode_start_seconds = (
            timecode_start_seconds
            if timecode_source_kind in {"video", "tmcd"} else None
        )

        return MediaInfo(
            duration_ms=video_duration_ms or format_duration_ms,
            width=width,
            height=height,
            fps=fps,
            sample_rate=sample_rate,
            audio_channels=audio_channels or None,
            audio_sources=audio_sources or None,
            video_frame_count=video_frame_count,
            frame_duration=frame_duration,
            video_duration=video_duration,
            audio_sample_rate=sample_rate,
            audio_sample_count=audio_sample_count,
            start_time=start_time,
            time_base=time_base,
            timecode=timecode,
            timecode_rate=timecode_rate if timecode else None,
            timecode_start_frames=timecode_start_frames,
            timecode_start_seconds=timecode_start_seconds,
            timecode_source_kind=timecode_source_kind,
            fcpxml_timecode_start_seconds=fcpxml_timecode_start_seconds,
        )

    async def create_media_file(self, path: Path) -> MediaFile:
        """Create a MediaFile object from a file path.

        Args:
            path: Path to the media file

        Returns:
            MediaFile with metadata
        """
        path = Path(path).resolve()
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        info = await self.get_media_info(path)

        return MediaFile(
            path=path,
            original_name=path.name,
            info=info,
        )

    async def extract_audio(
        self,
        input_path: Path,
        output_path: Path,
        sample_rate: int = 16000,
    ) -> Path:
        """Extract audio from a video file.

        Args:
            input_path: Path to input video
            output_path: Path for output audio
            sample_rate: Target sample rate

        Returns:
            Path to the extracted audio file
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        cmd = [
            "ffmpeg",
            "-y",  # Overwrite output
            "-i", str(input_path),
            "-vn",  # No video
            "-acodec", "pcm_s16le",
            "-ar", str(sample_rate),
            "-ac", "1",  # Mono
            str(output_path),
        ]

        result = await asyncio.to_thread(
            subprocess.run, cmd, capture_output=True, text=True
        )

        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg failed: {result.stderr}")

        return output_path

    async def trim_media(
        self,
        input_path: Path,
        output_path: Path,
        start_ms: int,
        end_ms: int,
    ) -> Path:
        """Trim media to a specific time range.

        Args:
            input_path: Path to input file
            output_path: Path for output file
            start_ms: Start time in milliseconds
            end_ms: End time in milliseconds

        Returns:
            Path to the trimmed file
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        start_sec = start_ms / 1000.0
        duration_sec = (end_ms - start_ms) / 1000.0

        cmd = [
            "ffmpeg",
            "-y",
            "-ss", str(start_sec),
            "-i", str(input_path),
            "-t", str(duration_sec),
            "-c", "copy",  # Stream copy (fast, no re-encoding)
            str(output_path),
        ]

        result = await asyncio.to_thread(
            subprocess.run, cmd, capture_output=True, text=True
        )

        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg failed: {result.stderr}")

        return output_path
