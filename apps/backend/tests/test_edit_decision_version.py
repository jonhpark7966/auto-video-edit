import json
import sys
from pathlib import Path

from avid.models.project import Project


SKILLS_DIR = Path(__file__).resolve().parents[3] / "skills"
if str(SKILLS_DIR) not in sys.path:
    sys.path.insert(0, str(SKILLS_DIR))

from _common import SubtitleSegment  # noqa: E402
from _common.edit_decision import (  # noqa: E402
    apply_boundary_repair,
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
