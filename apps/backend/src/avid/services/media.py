"""Media service implementation using FFmpeg."""

import asyncio
import json
import subprocess
from pathlib import Path

from avid.models.media import MediaFile, MediaInfo


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

        # Extract duration from format
        duration_sec = float(data.get("format", {}).get("duration", 0))
        duration_ms = int(duration_sec * 1000)

        # Find video and audio streams
        width = None
        height = None
        fps = None
        sample_rate = None

        for stream in data.get("streams", []):
            if stream.get("codec_type") == "video":
                width = stream.get("width")
                height = stream.get("height")
                # Parse frame rate (e.g., "30/1" or "30000/1001")
                fps_str = stream.get("r_frame_rate", "0/1")
                if "/" in fps_str:
                    num, den = fps_str.split("/")
                    fps = float(num) / float(den) if float(den) != 0 else None
            elif stream.get("codec_type") == "audio":
                sample_rate = int(stream.get("sample_rate", 0)) or None

        return MediaInfo(
            duration_ms=duration_ms,
            width=width,
            height=height,
            fps=fps,
            sample_rate=sample_rate,
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
