"""Edit decision version helpers shared by cut skills."""

from typing import Any

from .srt_parser import SubtitleSegment


EDIT_DECISION_VERSION_LEGACY = "legacy"
EDIT_DECISION_VERSION_BOUNDARY_AWARE_V1 = "boundary_aware_v1"
ALLOWED_EDIT_DECISION_VERSIONS = {
    EDIT_DECISION_VERSION_LEGACY,
    EDIT_DECISION_VERSION_BOUNDARY_AWARE_V1,
}

CLOSE_BOUNDARY_THRESHOLD_MS = 80
BOUNDARY_REPAIR_NONE = "none"
BOUNDARY_REPAIR_CUT_WITH_RISK = "cut_with_boundary_risk"
BOUNDARY_KEEP_REPAIRS = {
    "keep_with_prev",
    "keep_with_next",
    "keep_with_neighbors",
}
ALLOWED_BOUNDARY_REPAIRS = {
    BOUNDARY_REPAIR_NONE,
    BOUNDARY_REPAIR_CUT_WITH_RISK,
    *BOUNDARY_KEEP_REPAIRS,
}


BOUNDARY_AWARE_PROMPT_SECTION = """## Boundary-aware edit decision rules

Each segment includes the following boundary metadata:

- gap_from_prev_ms: the gap between the previous segment end and the current segment start
- gap_to_next_ms: the gap between the current segment end and the next segment start
- close_to_prev: true when gap_from_prev_ms <= 80
- close_to_next: true when gap_to_next_ms <= 80

A boundary with a gap of 80ms or less is a risky edit boundary. Cutting at that boundary may clip speech, make a sentence feel interrupted, or make the remaining dialogue sound unnaturally stitched together.

Important:
- Do not automatically KEEP a segment just because a boundary gap is 80ms or less.
- Do not automatically CUT a segment just because a boundary gap is 80ms or less.
- Treat close boundary metadata as a warning signal for semantic judgment.
- Judge whether the final video reads naturally when only the remaining KEEP segments are played in order.

When you choose CUT for a segment, you must evaluate its boundaries.

left_cut_ok:
- true if cutting between the previous segment and this segment would sound natural.
- false if this segment is part of the previous sentence, completes the previous thought, or the boundary is so tight that cutting may sound clipped.

right_cut_ok:
- true if cutting between this segment and the next segment would sound natural.
- false if the next segment depends on this segment as a response, pronoun reference, sentence completion, reason, setup, or payoff.

repair:
- none: CUT is safe and no repair is needed.
- keep_with_prev: this segment is a weak CUT candidate, but it is semantically attached to the previous segment, so it should be kept if the previous segment is kept.
- keep_with_next: this segment is a weak CUT candidate, but it is semantically attached to the next segment, so it should be kept if the next segment is kept.
- keep_with_neighbors: this segment is a weak CUT candidate, but removing it would make the surrounding KEEP segments awkward.
- cut_with_boundary_risk: the boundary is risky, but the segment should still be CUT for semantic reasons, such as a clear mistake, retake signal, previous take, production meta comment, or off-topic detour.

Decide repair semantically.
Do not choose keep_with_prev, keep_with_next, or keep_with_neighbors merely because the gap is short.
If there is boundary risk but the segment clearly must be removed, choose cut_with_boundary_risk and explain why in the note."""


def normalize_edit_decision_version(value: Any) -> str:
    """Return a supported edit decision version, defaulting to legacy."""
    return value if value in ALLOWED_EDIT_DECISION_VERSIONS else EDIT_DECISION_VERSION_LEGACY


def is_boundary_aware_version(value: Any) -> bool:
    """Return whether the edit decision version enables boundary-aware behavior."""
    return normalize_edit_decision_version(value) == EDIT_DECISION_VERSION_BOUNDARY_AWARE_V1


def format_segments_with_boundary_metadata(segments: list[SubtitleSegment]) -> str:
    """Format transcript segments with ms timing and close-boundary metadata."""
    lines: list[str] = []
    for i, seg in enumerate(segments):
        prev_seg = segments[i - 1] if i > 0 else None
        next_seg = segments[i + 1] if i + 1 < len(segments) else None
        gap_from_prev = max(0, seg.start_ms - prev_seg.end_ms) if prev_seg else None
        gap_to_next = max(0, next_seg.start_ms - seg.end_ms) if next_seg else None
        close_to_prev = gap_from_prev is not None and gap_from_prev <= CLOSE_BOUNDARY_THRESHOLD_MS
        close_to_next = gap_to_next is not None and gap_to_next <= CLOSE_BOUNDARY_THRESHOLD_MS
        speaker = seg.speaker or "unknown"
        lines.append(
            f"[{seg.index}] {seg.start_ms}ms-{seg.end_ms}ms\n"
            f"speaker={speaker}\n"
            f"gap_from_prev_ms={gap_from_prev if gap_from_prev is not None else 'unknown'}\n"
            f"gap_to_next_ms={gap_to_next if gap_to_next is not None else 'unknown'}\n"
            f"close_to_prev={'true' if close_to_prev else 'false'}\n"
            f"close_to_next={'true' if close_to_next else 'false'}\n"
            f"text: \"{seg.text}\""
        )
    return "\n\n".join(lines)


def boundary_aware_output_instructions(*, include_entertainment_score: bool = False) -> str:
    """Return output schema instructions for boundary-aware cut decisions."""
    score_line = '\n      "entertainment_score": 3,' if include_entertainment_score else ""
    return f"""## Boundary-aware output requirement

For every decision with `"action": "cut"`, include a `boundary` object with:

- left_cut_ok
- right_cut_ok
- repair

Use one of these repair values only: `none`, `keep_with_prev`, `keep_with_next`, `keep_with_neighbors`, `cut_with_boundary_risk`.

Example:

```json
{{
  "analysis": [
    {{
      "segment_index": 13,
      "action": "cut",
      "reason": "retake_signal",{score_line}
      "note": "The left boundary is tight, but this is an explicit retake signal and should be removed.",
      "boundary": {{
        "left_cut_ok": false,
        "right_cut_ok": true,
        "repair": "cut_with_boundary_risk"
      }}
    }}
  ]
}}
```

JSON only."""


def apply_boundary_aware_prompt(
    prompt: str,
    *,
    edit_decision_version: str,
    include_entertainment_score: bool = False,
) -> str:
    """Append boundary-aware instructions only for boundary_aware_v1."""
    if not is_boundary_aware_version(edit_decision_version):
        return prompt
    return (
        prompt
        + "\n\n"
        + BOUNDARY_AWARE_PROMPT_SECTION
        + "\n\n"
        + boundary_aware_output_instructions(
            include_entertainment_score=include_entertainment_score
        )
    )


def _normalize_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lower = value.strip().lower()
        if lower == "true":
            return True
        if lower == "false":
            return False
    return None


def normalize_boundary_metadata(value: Any) -> dict[str, Any] | None:
    """Validate LLM boundary metadata and drop unsupported shape."""
    if not isinstance(value, dict):
        return None

    repair = value.get("repair")
    if repair not in ALLOWED_BOUNDARY_REPAIRS:
        repair = BOUNDARY_REPAIR_NONE

    boundary: dict[str, Any] = {"repair": repair}
    left_cut_ok = _normalize_bool(value.get("left_cut_ok"))
    right_cut_ok = _normalize_bool(value.get("right_cut_ok"))
    if left_cut_ok is not None:
        boundary["left_cut_ok"] = left_cut_ok
    if right_cut_ok is not None:
        boundary["right_cut_ok"] = right_cut_ok
    return boundary


def apply_boundary_repair(
    item: dict[str, Any],
    entry: dict[str, Any],
    action: Any,
    *,
    edit_decision_version: str,
) -> tuple[str, dict[str, Any]]:
    """Validate LLM repair metadata and apply it to the current segment only."""
    if not is_boundary_aware_version(edit_decision_version):
        return action, entry

    normalized_action = str(action or "").lower()
    boundary = normalize_boundary_metadata(item.get("boundary"))
    if boundary is None:
        return normalized_action, entry

    entry["boundary"] = boundary
    if normalized_action != "cut":
        return normalized_action, entry

    repair = boundary.get("repair", BOUNDARY_REPAIR_NONE)
    if repair in BOUNDARY_KEEP_REPAIRS:
        return "keep", entry
    if repair == BOUNDARY_REPAIR_CUT_WITH_RISK:
        note = str(entry.get("note") or "").strip()
        suffix = "Boundary risk accepted by LLM."
        entry["note"] = f"{note} {suffix}".strip() if note else suffix
    return "cut", entry
