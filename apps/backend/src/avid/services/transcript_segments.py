"""Load metadata-preserving transcript segments for edit workflows."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_segments_json(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        raw_segments = data.get("segments")
    else:
        raw_segments = data
    if not isinstance(raw_segments, list):
        raise RuntimeError("segments JSON must be a list or an object with 'segments'")

    segments: list[dict[str, Any]] = []
    for position, item in enumerate(raw_segments, start=1):
        if not isinstance(item, dict):
            continue
        start_ms = _coerce_time_ms(item, "start_ms", "start_time", "start")
        end_ms = _coerce_time_ms(item, "end_ms", "end_time", "end")
        if start_ms is None or end_ms is None or end_ms <= start_ms:
            continue
        try:
            index = int(item.get("index", position))
        except (TypeError, ValueError):
            index = position
        segment = {
            "index": index,
            "start_ms": start_ms,
            "end_ms": end_ms,
            "text": str(item.get("text") or "").strip(),
            "speaker": item.get("speaker") or item.get("speaker_id"),
        }
        overlap_protection = item.get("overlap_protection")
        if isinstance(overlap_protection, dict):
            segment["overlap_protection"] = overlap_protection
        segments.append(segment)
    return segments


def _coerce_time_ms(item: dict[str, Any], ms_key: str, seconds_key: str, fallback_key: str) -> int | None:
    value = item.get(ms_key)
    if value is not None:
        try:
            return int(round(float(value)))
        except (TypeError, ValueError):
            return None

    value = item.get(seconds_key, item.get(fallback_key))
    if value is None:
        return None
    try:
        return int(round(float(value) * 1000.0))
    except (TypeError, ValueError):
        return None
