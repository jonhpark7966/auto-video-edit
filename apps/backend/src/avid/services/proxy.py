"""Relink-safe proxy generation helpers."""

from __future__ import annotations

import json
import shutil
import subprocess
from fractions import Fraction
from pathlib import Path
from typing import Any, Literal


ProxyMode = Literal["zero-timecode-proxy", "preserve-timecode-proxy"]


def build_proxy_command(
    input_path: Path,
    output_path: Path,
    *,
    mode: ProxyMode,
    height: int = 360,
    encoder: str = "auto",
) -> list[str]:
    resolved_encoder = _resolve_encoder(encoder)
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(input_path),
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-vf",
        f"scale=-2:{height}",
    ]
    if mode == "zero-timecode-proxy":
        cmd.extend(["-map_metadata", "-1", "-write_tmcd", "0"])
    elif mode == "preserve-timecode-proxy":
        cmd.extend(["-map_metadata", "0"])
        timecode = probe_timecode(input_path)
        if timecode:
            cmd.extend(["-metadata:s:v:0", f"timecode={timecode}", "-write_tmcd", "1"])
    else:
        raise ValueError(f"Unknown proxy mode: {mode}")

    cmd.extend([
        "-c:v",
        resolved_encoder,
        "-pix_fmt",
        "yuv420p",
    ])
    if resolved_encoder == "libx264":
        cmd.extend(["-preset", "veryfast", "-crf", "23"])
    cmd.extend(["-c:a", "aac", str(output_path)])
    return cmd


def create_proxy(
    input_path: Path,
    output_path: Path,
    *,
    mode: ProxyMode,
    height: int = 360,
    encoder: str = "auto",
) -> dict[str, Any]:
    input_path = Path(input_path).resolve()
    output_path = Path(output_path).resolve()
    if not input_path.exists():
        raise FileNotFoundError(f"input media not found: {input_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = build_proxy_command(
        input_path,
        output_path,
        mode=mode,
        height=height,
        encoder=encoder,
    )
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg proxy generation failed:\n{result.stderr[-2000:]}")

    return validate_proxy(input_path, output_path, mode=mode)


def validate_proxy(input_path: Path, output_path: Path, *, mode: ProxyMode) -> dict[str, Any]:
    input_probe = probe_media(input_path)
    output_probe = probe_media(output_path)
    input_fps = probe_fps(input_probe)
    output_fps = probe_fps(output_probe)
    input_channels = probe_audio_channels(input_probe)
    output_channels = probe_audio_channels(output_probe)
    input_timecode = _extract_timecode(input_probe)
    output_timecode = _extract_timecode(output_probe)
    output_has_timecode = probe_has_timecode(output_probe)
    output_has_tmcd = probe_has_tmcd(output_probe)
    output_tmcd_timecode = probe_tmcd_timecode(output_probe)
    errors: list[str] = []

    if input_fps and output_fps and input_fps != output_fps:
        errors.append(f"fps mismatch: input={input_fps} output={output_fps}")
    if input_channels != output_channels:
        errors.append(
            f"audio channel mismatch: input={input_channels} output={output_channels}"
        )
    if mode == "zero-timecode-proxy" and output_has_timecode:
        errors.append("zero-timecode proxy still contains timecode metadata or data streams")
    if mode == "preserve-timecode-proxy" and input_timecode:
        if output_timecode != input_timecode:
            errors.append(
                f"timecode mismatch: input={input_timecode} output={output_timecode}"
            )
        if not output_has_tmcd:
            errors.append("preserve-timecode proxy is missing a tmcd data stream")
        elif output_tmcd_timecode != input_timecode:
            errors.append(
                f"tmcd timecode mismatch: input={input_timecode} output={output_tmcd_timecode}"
            )

    if errors:
        raise RuntimeError("; ".join(errors))

    return {
        "input": str(Path(input_path).resolve()),
        "output": str(Path(output_path).resolve()),
        "mode": mode,
        "input_fps": _fraction_to_rate(input_fps),
        "output_fps": _fraction_to_rate(output_fps),
        "input_audio_channels": input_channels,
        "output_audio_channels": output_channels,
        "input_timecode": input_timecode,
        "output_timecode": output_timecode,
        "output_has_timecode": output_has_timecode,
        "output_has_tmcd": output_has_tmcd,
        "output_tmcd_timecode": output_tmcd_timecode,
    }


def probe_media(path: Path) -> dict[str, Any]:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed for {path}: {result.stderr[-1000:]}")
    return json.loads(result.stdout)


def probe_timecode(path: Path) -> str | None:
    return _extract_timecode(probe_media(path))


def probe_fps(payload: dict[str, Any]) -> Fraction | None:
    video = _first_stream(payload, "video")
    if not video:
        return None
    return _rate_to_fraction(video.get("r_frame_rate")) or _rate_to_fraction(
        video.get("avg_frame_rate")
    )


def probe_audio_channels(payload: dict[str, Any]) -> int:
    return sum(
        _int_or_none(stream.get("channels")) or 0
        for stream in payload.get("streams", [])
        if stream.get("codec_type") == "audio"
    )


def probe_has_timecode(payload: dict[str, Any]) -> bool:
    if _extract_timecode(payload):
        return True
    for stream in payload.get("streams", []):
        if stream.get("codec_type") == "data":
            return True
    return False


def probe_has_tmcd(payload: dict[str, Any]) -> bool:
    for stream in payload.get("streams", []):
        if stream.get("codec_type") != "data":
            continue
        tag = stream.get("codec_tag_string")
        if isinstance(tag, str) and tag.lower() == "tmcd":
            return True
    return False


def probe_tmcd_timecode(payload: dict[str, Any]) -> str | None:
    for stream in payload.get("streams", []):
        if stream.get("codec_type") != "data":
            continue
        tag = stream.get("codec_tag_string")
        if isinstance(tag, str) and tag.lower() == "tmcd":
            return _tag_timecode(stream.get("tags"))
    return None


def _resolve_encoder(encoder: str) -> str:
    if encoder != "auto":
        return encoder
    return "h264_nvenc" if shutil.which("nvidia-smi") else "libx264"


def _first_stream(payload: dict[str, Any], codec_type: str) -> dict[str, Any] | None:
    return next(
        (
            stream
            for stream in payload.get("streams", [])
            if stream.get("codec_type") == codec_type
        ),
        None,
    )


def _extract_timecode(payload: dict[str, Any]) -> str | None:
    streams = payload.get("streams", [])
    for codec_type in ("video", "data"):
        for stream in streams:
            if stream.get("codec_type") != codec_type:
                continue
            value = _tag_timecode(stream.get("tags"))
            if value:
                return value
    format_tags = (payload.get("format") or {}).get("tags")
    return _tag_timecode(format_tags)


def _tag_timecode(tags: object) -> str | None:
    if not isinstance(tags, dict):
        return None
    value = tags.get("timecode") or tags.get("TIMECODE")
    return str(value).strip() if value else None


def _rate_to_fraction(value: object) -> Fraction | None:
    if not isinstance(value, str) or not value or "/" not in value:
        return None
    try:
        numerator, denominator = value.split("/", 1)
        fraction = Fraction(int(numerator), int(denominator))
    except (ValueError, ZeroDivisionError):
        return None
    return fraction if fraction > 0 else None


def _fraction_to_rate(value: Fraction | None) -> str | None:
    if value is None:
        return None
    return f"{value.numerator}/{value.denominator}"


def _int_or_none(value: object) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None
