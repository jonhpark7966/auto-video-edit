"""Unit tests for apply-evaluation CLI command."""

from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

import pytest

from avid.cli import cmd_apply_evaluation
from avid.models.media import MediaFile, MediaInfo
from avid.models.project import Project
from avid.models.timeline import EditDecision, EditReason, EditType, TimeRange


def _build_project() -> Project:
    project = Project(name="apply-evaluation-test")
    media = MediaFile(
        id="main-id",
        path=Path("/media/main.mp4"),
        original_name="main.mp4",
        info=MediaInfo(
            duration_ms=20_000,
            width=1920,
            height=1080,
            fps=30.0,
            sample_rate=48_000,
        ),
    )
    project.add_source_file(media)
    video_track = project.get_video_tracks()[0]
    audio_track = project.get_audio_tracks()[0]
    project.edit_decisions = [
        EditDecision(
            range=TimeRange(start_ms=1_000, end_ms=2_000),
            edit_type=EditType.CUT,
            reason=EditReason.FILLER,
            confidence=0.9,
            active_video_track_id=video_track.id,
            active_audio_track_ids=[audio_track.id],
        ),
        EditDecision(
            range=TimeRange(start_ms=5_000, end_ms=6_000),
            edit_type=EditType.CUT,
            reason=EditReason.DUPLICATE,
            confidence=0.95,
            active_video_track_id=video_track.id,
            active_audio_track_ids=[audio_track.id],
        ),
    ]
    return project


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


class TestApplyEvaluation:
    def test_apply_evaluation_updates_project_and_returns_stats(self, tmp_path: Path):
        project_path = tmp_path / "input.project.avid.json"
        evaluation_path = tmp_path / "evaluation.json"
        output_path = tmp_path / "nested" / "output.project.avid.json"

        _build_project().save(project_path)
        _write_json(
            evaluation_path,
            {
                "segments": [
                    {"start_ms": 1_500, "end_ms": 1_800, "human": {"action": "keep"}},
                    {"start_ms": 7_000, "end_ms": 8_000, "human": {"action": "cut"}},
                ]
            },
        )

        payload = cmd_apply_evaluation(
            Namespace(
                project_json=str(project_path),
                evaluation=str(evaluation_path),
                output_project_json=str(output_path),
                json=True,
                manifest_out=None,
            )
        )

        assert payload["command"] == "apply-evaluation"
        assert payload["artifacts"]["project_json"] == str(output_path)
        assert payload["stats"] == {
            "applied_evaluation_segments": 2,
            "applied_changes": 1,
        }

        updated_project = Project.load(output_path)
        decision_ranges = [
            (decision.range.start_ms, decision.range.end_ms, decision.reason.value)
            for decision in updated_project.edit_decisions
        ]
        assert decision_ranges == [
            (5_000, 6_000, "duplicate"),
            (7_000, 8_000, "manual"),
        ]

    def test_apply_evaluation_accepts_list_payload(self, tmp_path: Path):
        project_path = tmp_path / "input.project.avid.json"
        evaluation_path = tmp_path / "evaluation.json"
        output_path = tmp_path / "output"

        _build_project().save(project_path)
        _write_json(
            evaluation_path,
            [
                {"start_ms": 1_500, "end_ms": 1_800, "human": {"action": "keep"}},
            ],
        )

        payload = cmd_apply_evaluation(
            Namespace(
                project_json=str(project_path),
                evaluation=str(evaluation_path),
                output_project_json=str(output_path),
                json=True,
                manifest_out=None,
            )
        )

        saved_path = Path(payload["artifacts"]["project_json"])
        assert saved_path.name == "output.avid.json"
        updated_project = Project.load(saved_path)
        assert [(decision.range.start_ms, decision.range.end_ms) for decision in updated_project.edit_decisions] == [
            (5_000, 6_000),
        ]

    def test_apply_evaluation_missing_project_exits(self, tmp_path: Path):
        evaluation_path = tmp_path / "evaluation.json"
        _write_json(evaluation_path, [])

        with pytest.raises(SystemExit) as exc_info:
            cmd_apply_evaluation(
                Namespace(
                    project_json=str(tmp_path / "missing.project.avid.json"),
                    evaluation=str(evaluation_path),
                    output_project_json=str(tmp_path / "output.project.avid.json"),
                    json=True,
                    manifest_out=None,
                )
            )

        assert exc_info.value.code == 1
