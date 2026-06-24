import json
import sys
from pathlib import Path

from avid.models.project import Project


SKILLS_DIR = Path(__file__).resolve().parents[3] / "skills"
if str(SKILLS_DIR) not in sys.path:
    sys.path.insert(0, str(SKILLS_DIR))

from _common import SubtitleSegment  # noqa: E402
from _common.edit_decision import (  # noqa: E402
    apply_junction_coherence_guard,
    apply_boundary_repair,
    resolve_boundary_repairs,
    format_segments_with_boundary_metadata,
)


def test_boundary_aware_segment_formatter_adds_close_boundary_metadata():
    segments = [
        SubtitleSegment(index=1, start_ms=0, end_ms=1000, text="first"),
        SubtitleSegment(index=2, start_ms=1060, end_ms=1800, text="second", speaker="speaker_0"),
        SubtitleSegment(index=3, start_ms=2000, end_ms=2600, text="third"),
    ]

    payload = format_segments_with_boundary_metadata(segments)

    assert "[2] 1060ms-1800ms" in payload
    assert "speaker=speaker_0" in payload
    assert "gap_from_prev_ms=60" in payload
    assert "close_to_prev=true" in payload
    assert "gap_to_next_ms=200" in payload
    assert "close_to_next=false" in payload


def test_boundary_repair_keeps_current_segment_only_when_llm_requests_keep_repair():
    action, entry = apply_boundary_repair(
        {
            "boundary": {
                "left_cut_ok": False,
                "right_cut_ok": True,
                "repair": "keep_with_next",
            }
        },
        {"segment_index": 2, "reason": "filler", "note": "bridge"},
        "cut",
        edit_decision_version="boundary_aware_v1",
    )

    assert action == "keep"
    assert entry["boundary"]["repair"] == "keep_with_next"


def test_boundary_risk_keeps_cut_and_records_note():
    action, entry = apply_boundary_repair(
        {
            "boundary": {
                "left_cut_ok": False,
                "right_cut_ok": True,
                "repair": "cut_with_boundary_risk",
            }
        },
        {"segment_index": 2, "reason": "retake_signal", "note": "retake"},
        "cut",
        edit_decision_version="boundary_aware_v1",
    )

    assert action == "cut"
    assert "Boundary risk accepted by LLM." in entry["note"]


def test_legacy_repair_path_preserves_existing_action_case():
    action, entry = apply_boundary_repair(
        {"boundary": {"repair": "keep_with_prev"}},
        {"segment_index": 2},
        "CUT",
        edit_decision_version="legacy",
    )

    assert action == "CUT"
    assert "boundary" not in entry


def test_project_model_defaults_legacy_and_accepts_optional_boundary(tmp_path):
    project_path = tmp_path / "project.avid.json"
    project_path.write_text(
        json.dumps({
            "name": "legacy",
            "source_files": [],
            "tracks": [],
            "transcription": None,
            "edit_decisions": [],
        }),
        encoding="utf-8",
    )

    loaded = Project.load(project_path)

    assert loaded.edit_decision_version == "legacy"

    project_path.write_text(
        json.dumps({
            "name": "boundary",
            "source_files": [],
            "tracks": [],
            "transcription": None,
            "edit_decision_version": "boundary_aware_v1",
            "edit_decisions": [
                {
                    "range": {"start_ms": 0, "end_ms": 100},
                    "edit_type": "cut",
                    "reason": "filler",
                    "boundary": {
                        "left_cut_ok": True,
                        "right_cut_ok": True,
                        "repair": "none",
                    },
                }
            ],
        }),
        encoding="utf-8",
    )

    loaded = Project.load(project_path)

    assert loaded.edit_decision_version == "boundary_aware_v1"
    assert loaded.edit_decisions[0].boundary["repair"] == "none"


def _boundary_decision(segment_index: int, action: str, repair: str) -> dict:
    return {
        "segment_index": segment_index,
        "action": action,
        "reason": "test",
        "note": f"segment {segment_index}",
        "boundary": {
            "left_cut_ok": False,
            "right_cut_ok": False,
            "repair": repair,
        },
    }


def _resolve_boundary_decisions(
    *items: dict,
    segment_indices: list[int],
) -> tuple[list[dict], list[dict]]:
    entries = [
        {
            "segment_index": item["segment_index"],
            "reason": item["reason"],
            "note": item["note"],
        }
        for item in items
    ]
    return resolve_boundary_repairs(
        list(items),
        entries,
        [item["action"] for item in items],
        segment_indices=segment_indices,
        edit_decision_version="boundary_aware_v1",
    )


def test_batch_boundary_keep_with_next_promotes_only_when_next_is_keep():
    cuts, keeps = _resolve_boundary_decisions(
        _boundary_decision(1, "cut", "keep_with_next"),
        _boundary_decision(2, "keep", "none"),
        segment_indices=[1, 2],
    )

    assert cuts == []
    assert [item["segment_index"] for item in keeps] == [1, 2]


def test_batch_boundary_keep_with_next_stays_cut_when_next_is_cut():
    cuts, keeps = _resolve_boundary_decisions(
        _boundary_decision(1, "cut", "keep_with_next"),
        _boundary_decision(2, "cut", "none"),
        segment_indices=[1, 2],
    )

    assert [item["segment_index"] for item in cuts] == [1, 2]
    assert keeps == []


def test_batch_boundary_keep_with_prev_promotes_when_prev_is_keep():
    cuts, keeps = _resolve_boundary_decisions(
        _boundary_decision(1, "keep", "none"),
        _boundary_decision(2, "cut", "keep_with_prev"),
        segment_indices=[1, 2],
    )

    assert cuts == []
    assert [item["segment_index"] for item in keeps] == [1, 2]


def test_batch_boundary_keep_with_neighbors_requires_both_neighbors():
    cuts, keeps = _resolve_boundary_decisions(
        _boundary_decision(1, "keep", "none"),
        _boundary_decision(2, "cut", "keep_with_neighbors"),
        _boundary_decision(3, "cut", "none"),
        segment_indices=[1, 2, 3],
    )

    assert [item["segment_index"] for item in cuts] == [2, 3]
    assert [item["segment_index"] for item in keeps] == [1]

    cuts, keeps = _resolve_boundary_decisions(
        _boundary_decision(1, "keep", "none"),
        _boundary_decision(2, "cut", "keep_with_neighbors"),
        _boundary_decision(3, "keep", "none"),
        segment_indices=[1, 2, 3],
    )

    assert cuts == []
    assert [item["segment_index"] for item in keeps] == [1, 2, 3]


def test_junction_guard_keeps_completion_segment_with_metadata():
    segments = [
        SubtitleSegment(index=473, start_ms=1_197_064, end_ms=1_204_784, text="조금 더 섞어서 얘기를"),
        SubtitleSegment(index=474, start_ms=1_206_014, end_ms=1_207_224, text="해보도록 하겠습니다."),
    ]
    cuts = [
        {
            "segment_index": 474,
            "reason": "filler",
            "entertainment_score": 2,
            "note": "formulaic closing",
        }
    ]
    keeps = [
        {
            "segment_index": 473,
            "reason": "engaging",
            "entertainment_score": 7,
            "note": "foreshadowing",
        }
    ]

    repaired_cuts, repaired_keeps = apply_junction_coherence_guard(segments, cuts, keeps)

    assert repaired_cuts == []
    repaired = {item["segment_index"]: item for item in repaired_keeps}[474]
    assert repaired["action"] == "keep"
    assert repaired["decision_source"] == "junction_guard"
    assert repaired["junction_repair"]["original_action"] == "cut"
    assert repaired["junction_repair"]["repaired_to"] == "keep"
    assert repaired["junction_repair"]["linked_segment_indices"] == [473, 474]


def test_batch_boundary_cut_with_risk_stays_cut_and_records_note():
    cuts, keeps = _resolve_boundary_decisions(
        _boundary_decision(1, "cut", "cut_with_boundary_risk"),
        segment_indices=[1],
    )

    assert keeps == []
    assert [item["segment_index"] for item in cuts] == [1]
    assert "Boundary risk accepted by LLM." in cuts[0]["note"]
