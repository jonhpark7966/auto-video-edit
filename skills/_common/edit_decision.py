"""Edit decision version helpers shared by cut skills."""

from typing import Any
import re

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


def _entry_segment_index(entry: dict[str, Any]) -> int | None:
    value = entry.get("segment_index")
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _append_boundary_risk_note(entry: dict[str, Any]) -> None:
    note = str(entry.get("note") or "").strip()
    suffix = "Boundary risk accepted by LLM."
    if suffix in note:
        return
    entry["note"] = f"{note} {suffix}".strip() if note else suffix


def _neighbor_index(
    index: int | None,
    *,
    offset: int,
    position_by_index: dict[int, int],
    segment_indices: list[int],
) -> int | None:
    if index is None or index not in position_by_index:
        return None
    position = position_by_index[index] + offset
    if position < 0 or position >= len(segment_indices):
        return None
    return segment_indices[position]


def resolve_boundary_repairs(
    items: list[dict[str, Any]],
    entries: list[dict[str, Any]],
    actions: list[Any],
    *,
    segment_indices: list[int],
    edit_decision_version: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Resolve boundary repair decisions after seeing neighboring actions.

    `apply_boundary_repair` is intentionally kept for older call sites that apply
    a single decision immediately. This batch resolver is for analyzers that can
    inspect the whole chunk before deciding whether a weak CUT should be promoted
    because an adjacent segment is also kept.
    """
    decisions: list[dict[str, Any]] = []
    position_by_index = {
        index: position
        for position, index in enumerate(segment_indices)
    }

    for item, entry, action in zip(items, entries, actions):
        current_entry = dict(entry)
        normalized_action = str(action or "").lower()

        if is_boundary_aware_version(edit_decision_version):
            boundary = normalize_boundary_metadata(item.get("boundary"))
            if boundary is not None:
                current_entry["boundary"] = boundary

        decisions.append(
            {
                "entry": current_entry,
                "action": normalized_action,
                "segment_index": _entry_segment_index(current_entry),
            }
        )

    if not is_boundary_aware_version(edit_decision_version):
        cuts = [decision["entry"] for decision in decisions if decision["action"] == "cut"]
        keeps = [decision["entry"] for decision in decisions if decision["action"] != "cut"]
        return cuts, keeps

    resolved_actions: dict[int, str] = {}
    for decision in decisions:
        index = decision["segment_index"]
        if index is not None:
            resolved_actions[index] = "cut" if decision["action"] == "cut" else "keep"

    changed = True
    while changed:
        changed = False
        for decision in decisions:
            index = decision["segment_index"]
            if index is None or resolved_actions.get(index) != "cut":
                continue
            if decision["action"] != "cut":
                continue

            boundary = decision["entry"].get("boundary")
            if not isinstance(boundary, dict):
                continue

            repair = boundary.get("repair", BOUNDARY_REPAIR_NONE)
            prev_index = _neighbor_index(
                index,
                offset=-1,
                position_by_index=position_by_index,
                segment_indices=segment_indices,
            )
            next_index = _neighbor_index(
                index,
                offset=1,
                position_by_index=position_by_index,
                segment_indices=segment_indices,
            )

            should_keep = False
            if repair == "keep_with_prev":
                should_keep = resolved_actions.get(prev_index) == "keep"
            elif repair == "keep_with_next":
                should_keep = resolved_actions.get(next_index) == "keep"
            elif repair == "keep_with_neighbors":
                should_keep = (
                    resolved_actions.get(prev_index) == "keep"
                    and resolved_actions.get(next_index) == "keep"
                )

            if should_keep:
                resolved_actions[index] = "keep"
                changed = True

    cuts: list[dict[str, Any]] = []
    keeps: list[dict[str, Any]] = []
    for decision in decisions:
        entry = decision["entry"]
        index = decision["segment_index"]
        action = resolved_actions.get(
            index,
            "cut" if decision["action"] == "cut" else "keep",
        )
        boundary = entry.get("boundary")

        if action == "cut" and isinstance(boundary, dict):
            if boundary.get("repair") == BOUNDARY_REPAIR_CUT_WITH_RISK:
                _append_boundary_risk_note(entry)

        if action == "cut":
            cuts.append(entry)
        else:
            keeps.append(entry)

    return cuts, keeps


def _entry_by_index(items: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    indexed: dict[int, dict[str, Any]] = {}
    for item in items:
        index = _entry_segment_index(item)
        if index is not None:
            indexed[index] = item
    return indexed


def _clean_tail(text: str) -> str:
    return re.sub(r"[\s\"'“”‘’.,!?…。]+$", "", str(text or "").strip())


def _normalized_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip())


def _duration_ms(segment: SubtitleSegment) -> int:
    return max(0, int(segment.end_ms) - int(segment.start_ms))


def _gap_ms(left: SubtitleSegment, right: SubtitleSegment) -> int:
    return max(0, int(right.start_ms) - int(left.end_ms))


_DANGLING_TAILS = (
    "얘기를",
    "이야기를",
    "말을",
    "설명을",
    "생각을",
    "부분을",
    "것을",
    "거를",
    "걸",
    "수",
    "좀",
    "이제",
    "왜냐하면",
    "때문에",
    "라서",
    "이라서",
    "해서",
    "하고",
    "하고서",
    "고",
    "면",
    "는데",
    "하는",
    "되면",
)


_COMPLETION_STARTS = (
    "하겠습니다",
    "해보겠습니다",
    "해 보겠습니다",
    "해보도록",
    "해 보도록",
    "하죠",
    "할게요",
    "해요",
    "합니다",
    "됩니다",
    "되죠",
    "되는",
    "같아요",
    "거죠",
    "겁니다",
    "드릴게요",
    "가겠습니다",
    "보겠습니다",
)


def _has_dangling_tail(text: str) -> bool:
    tail = _clean_tail(text)
    if not tail:
        return False
    if tail.endswith(_DANGLING_TAILS):
        return True
    return bool(re.search(r"(을|를|이|가|은|는|도|만|까지|부터|처럼|라고|다고|면서|는데|니까)$", tail))


def _starts_with_completion(text: str) -> bool:
    value = _normalized_text(text)
    if not value:
        return False
    if value.startswith(_COMPLETION_STARTS):
        return True
    return bool(re.search(r"(하겠습니다|해보도록 하겠습니다|해보겠습니다|합니다|해요|됩니다|거죠|같아요)", value[:40]))


def _looks_like_context_dependent_payoff(text: str) -> bool:
    value = _normalized_text(text)
    if len(value) > 40:
        return False
    patterns = (
        r"^제가 .*(죠|잖아요|거든요)[.!?。]?$",
        r"^저 .*(죠|잖아요|거든요)[.!?。]?$",
        r"^그거죠[.!?。]?$",
        r"^그렇죠[.!?。]?$",
        r"^맞죠[.!?。]?$",
        r"^정확합니다[.!?。]?$",
    )
    return any(re.search(pattern, value) for pattern in patterns)


def _repair_payload(
    *,
    repair_type: str,
    original_entry: dict[str, Any],
    repaired_to: str,
    linked_segment_indices: list[int],
    reason: str,
) -> dict[str, Any]:
    original_action = str(original_entry.get("action") or "cut").lower()
    return {
        "applied": True,
        "type": repair_type,
        "original_action": original_action,
        "repaired_from": original_action,
        "repaired_to": repaired_to,
        "original_reason": original_entry.get("reason"),
        "original_note": original_entry.get("note"),
        "linked_segment_indices": linked_segment_indices,
        "reason": reason,
        "user_apply_junction_repair": True,
    }


def _mark_repaired(
    entry: dict[str, Any],
    *,
    repair_type: str,
    repaired_to: str,
    linked_segment_indices: list[int],
    reason: str,
) -> dict[str, Any]:
    original = dict(entry)
    repaired = dict(entry)
    repaired["action"] = repaired_to
    repaired["decision_source"] = "junction_guard"
    repaired["junction_repair"] = _repair_payload(
        repair_type=repair_type,
        original_entry={**original, "action": original.get("action") or ("cut" if repaired_to == "keep" else "keep")},
        repaired_to=repaired_to,
        linked_segment_indices=linked_segment_indices,
        reason=reason,
    )
    if repaired_to == "keep":
        repaired["reason"] = repair_type
    note = str(original.get("note") or "").strip()
    suffix = f"Junction guard repair: {reason}"
    repaired["note"] = f"{suffix} Original note: {note}".strip() if note else suffix
    return repaired


def apply_junction_coherence_guard(
    segments: list[SubtitleSegment],
    cuts: list[dict[str, Any]],
    keeps: list[dict[str, Any]],
    *,
    max_sentence_gap_ms: int = 1500,
    max_completion_duration_ms: int = 2500,
    max_setup_segments: int = 2,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Repair narrow KEEP/CUT junctions that would leave incoherent final audio.

    The guard is intentionally conservative. It only changes decisions when a
    neighboring CUT clearly completes a kept sentence, or when a short payoff
    KEEP would be orphaned by immediately preceding CUT setup segments.
    """
    cut_by_index = _entry_by_index(cuts)
    keep_by_index = _entry_by_index(keeps)
    action_by_index: dict[int, str] = {}
    entry_by_index: dict[int, dict[str, Any]] = {}
    for seg in segments:
        action_by_index[seg.index] = "keep"
    for index, entry in keep_by_index.items():
        action_by_index[index] = "keep"
        entry_by_index[index] = {**entry, "action": "keep"}
    for index, entry in cut_by_index.items():
        action_by_index[index] = "cut"
        entry_by_index[index] = {**entry, "action": "cut"}

    segment_by_index = {seg.index: seg for seg in segments}
    repaired_entries: dict[int, dict[str, Any]] = {}
    ordered_indices = [seg.index for seg in segments]

    for left, right in zip(segments, segments[1:]):
        if action_by_index.get(left.index) != "keep" or action_by_index.get(right.index) != "cut":
            continue
        if _gap_ms(left, right) > max_sentence_gap_ms:
            continue
        if _duration_ms(right) > max_completion_duration_ms:
            continue
        if not _has_dangling_tail(left.text) or not _starts_with_completion(right.text):
            continue
        original = entry_by_index.get(right.index)
        if not original or isinstance(original.get("junction_repair"), dict):
            continue
        repaired_entries[right.index] = _mark_repaired(
            original,
            repair_type="sentence_completion",
            repaired_to="keep",
            linked_segment_indices=[left.index, right.index],
            reason="previous_keep_sentence_was_incomplete",
        )
        action_by_index[right.index] = "keep"

    for position, current in enumerate(segments):
        if action_by_index.get(current.index) != "keep":
            continue
        if not _looks_like_context_dependent_payoff(current.text):
            continue
        if _duration_ms(current) > 2200:
            continue

        linked = [current.index]
        promoted: list[int] = []
        cursor = position - 1
        while cursor >= 0 and len(promoted) < max_setup_segments:
            previous = segments[cursor]
            if action_by_index.get(previous.index) != "cut":
                break
            next_segment = segment_by_index[linked[0]]
            if _gap_ms(previous, next_segment) > max_sentence_gap_ms:
                break
            original = entry_by_index.get(previous.index)
            if original and not isinstance(original.get("junction_repair"), dict):
                promoted.append(previous.index)
                linked.insert(0, previous.index)
            cursor -= 1

        if not promoted:
            continue
        for index in promoted:
            original = entry_by_index.get(index)
            if not original:
                continue
            repaired_entries[index] = _mark_repaired(
                original,
                repair_type="setup_payoff",
                repaired_to="keep",
                linked_segment_indices=linked,
                reason="kept_payoff_depends_on_cut_setup",
            )
            action_by_index[index] = "keep"

    if not repaired_entries:
        return cuts, keeps

    repaired_cuts: list[dict[str, Any]] = []
    repaired_keeps_by_index = _entry_by_index(keeps)
    for cut in cuts:
        index = _entry_segment_index(cut)
        if index is not None and index in repaired_entries:
            repaired_keeps_by_index[index] = repaired_entries[index]
        else:
            repaired_cuts.append(cut)

    repaired_keeps: list[dict[str, Any]] = []
    for index in ordered_indices:
        entry = repaired_keeps_by_index.get(index)
        if entry is not None:
            repaired_keeps.append(entry)
    return repaired_cuts, repaired_keeps
