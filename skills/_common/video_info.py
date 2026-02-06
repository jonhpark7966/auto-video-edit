"""Video information extraction using ffprobe."""

import json
import subprocess
from pathlib import Path


def get_video_info(video_path: str) -> dict | None:
    """Get video information using ffprobe.

    Args:
        video_path: Path to video file

    Returns:
        Dict with duration_ms, width, height, fps, sample_rate
        or None if ffprobe fails
    """
    path = Path(video_path)
    if not path.exists():
        return None

    try:
        # Get video stream info
        cmd = [
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            str(path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            return None

        data = json.loads(result.stdout)

        # Extract info
        info = {
            "duration_ms": 0,
            "width": 0,
            "height": 0,
            "fps": 0.0,
            "sample_rate": None,
        }

        # Duration from format
        if "format" in data and "duration" in data["format"]:
            info["duration_ms"] = int(float(data["format"]["duration"]) * 1000)

        # Video stream info
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "video":
                info["width"] = stream.get("width", 0)
                info["height"] = stream.get("height", 0)

                # Parse fps from r_frame_rate (e.g., "24000/1001")
                r_frame_rate = stream.get("r_frame_rate", "0/1")
                if "/" in r_frame_rate:
                    num, den = map(int, r_frame_rate.split("/"))
                    if den > 0:
                        info["fps"] = round(num / den, 3)

            elif stream.get("codec_type") == "audio":
                sample_rate = stream.get("sample_rate")
                if sample_rate:
                    info["sample_rate"] = int(sample_rate)

        return info

    except (subprocess.TimeoutExpired, json.JSONDecodeError, Exception):
        return None
