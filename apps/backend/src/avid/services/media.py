"""Media service implementation using FFmpeg."""

import asyncio
import json
import subprocess
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


def _video_stream_duration_ms(stream: dict, fps: float | None) -> int | None:
    frames = _int_or_none(stream.get("nb_frames")) or _int_or_none(
        stream.get("nb_read_frames")
    )
    if frames is not None and fps:
        return int(frames / fps * 1000)

    duration_ts = _int_or_none(stream.get("duration_ts"))
    time_base = _rate_to_float(stream.get("time_base"))
    if duration_ts is not None and time_base:
        return int(duration_ts * time_base * 1000)

    duration = _float_or_none(stream.get("duration"))
    if duration is not None:
        return int(duration * 1000)

    return None


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

        # Extract duration from format. Video files prefer the video stream
        # length below so audio/container padding does not create FCP relink
        # overruns by a frame.
        duration_sec = float(data.get("format", {}).get("duration", 0))
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

        for stream in data.get("streams", []):
            if stream.get("codec_type") == "video":
                width = stream.get("width")
                height = stream.get("height")
                # Parse frame rate (e.g., "30/1" or "30000/1001")
                fps = (
                    _rate_to_float(stream.get("avg_frame_rate"))
                    or _rate_to_float(stream.get("r_frame_rate"))
                )
                if video_duration_ms is None:
                    video_duration_ms = _video_stream_duration_ms(stream, fps)
            elif stream.get("codec_type") == "audio":
                audio_sources += 1
                rate = _int_or_none(stream.get("sample_rate"))
                if rate:
                    sample_rates.add(rate)
                audio_channels += _int_or_none(stream.get("channels")) or 0

        if len(sample_rates) == 1:
            sample_rate = next(iter(sample_rates))

        return MediaInfo(
            duration_ms=video_duration_ms or format_duration_ms,
            width=width,
            height=height,
            fps=fps,
            sample_rate=sample_rate,
            audio_channels=audio_channels or None,
            audio_sources=audio_sources or None,
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
