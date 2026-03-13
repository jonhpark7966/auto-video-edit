"""Unit tests for deprecated reexport wrapper behavior."""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path

import pytest

from avid.cli import cmd_reexport
from avid.models.media import MediaFile, MediaInfo
from avid.models.project import Project, TranscriptSegment, Transcription
from avid.models.timeline import EditDecision, EditReason, EditType, TimeRange
from avid.services.audio_sync import SyncResult


def _media_file(file_id: str, path: Path) -> MediaFile:
    return MediaFile(
        id=file_id,
        path=path,
        original_name=path.name,
        info=MediaInfo(
            duration_ms=20_000,
            width=1920,
            height=1080,
            fps=30.0,
            sample_rate=48_000,
        ),
    )


def _build_project(main_path: Path, old_extra_path: Path | None = None) -> Project:
    project = Project(name="reexport-test")
    project.add_source_file(_media_file("main-id", main_path))
    audio_track = project.get_audio_tracks()[0]
    video_track = project.get_video_tracks()[0]
    if old_extra_path is not None:
        old_extra = _media_file("old-extra-id", old_extra_path)
        created_tracks = project.add_source_file(old_extra)
        for track in created_tracks:
            project.set_track_offset(track.id, 700)
    project.transcription = Transcription(
        source_track_id=audio_track.id,
        language="ko",
        segments=[
            TranscriptSegment(start_ms=0, end_ms=1_000, text="인트로"),
            TranscriptSegment(start_ms=2_000, end_ms=3_000, text="본문"),
        ],
    )
    project.edit_decisions = [
        EditDecision(
            range=TimeRange(start_ms=500, end_ms=1_500),
            edit_type=EditType.CUT,
            reason=EditReason.FILLER,
            confidence=1.0,
            active_video_track_id=video_track.id,
            active_audio_track_ids=[audio_track.id],
        )
    ]
    return project


class TestReexportLogic:
    @pytest.mark.asyncio
    async def test_reexport_warns_and_composes_steps(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ):
        main_path = tmp_path / "main.mp4"
        old_extra_path = tmp_path / "old-extra.mp4"
        new_extra_path = tmp_path / "new-extra.mp4"
        for path in (main_path, old_extra_path, new_extra_path):
            path.write_bytes(b"stub")

        project_path = tmp_path / "input.project.avid.json"
        output_dir = tmp_path / "output"
        evaluation_path = tmp_path / "evaluation.json"
        _build_project(main_path, old_extra_path).save(project_path)
        evaluation_path.write_text(
            (
                '[{"start_ms": 500, "end_ms": 1500, "human": {"action": "keep"}}, '
                '{"start_ms": 4000, "end_ms": 5000, "human": {"action": "cut"}}]'
            ),
            encoding="utf-8",
        )

        async def fake_add_extra_sources(self, project, source_path, extra_sources, manual_offsets=None):
            assert source_path == main_path.resolve()
            assert [path.resolve() for path in extra_sources] == [new_extra_path.resolve()]
            assert manual_offsets == {new_extra_path.name: 1200}
            extra_media = _media_file("new-extra-id", new_extra_path.resolve())
            created_tracks = project.add_source_file(extra_media)
            for track in created_tracks:
                project.set_track_offset(track.id, 1200)
            return [SyncResult(offset_ms=1200, confidence=1.0, method="manual", standard_score=0.0)]

        monkeypatch.setattr(
            "avid.services.audio_sync.AudioSyncService.add_extra_sources",
            fake_add_extra_sources,
        )

        payload = await cmd_reexport(
            Namespace(
                project_json=str(project_path),
                output_dir=str(output_dir),
                source=str(main_path),
                evaluation=str(evaluation_path),
                extra_source=[str(new_extra_path)],
                offset=["1200"],
                output=None,
                silence_mode="cut",
                content_mode="cut",
                json=True,
                manifest_out=None,
            )
        )

        captured = capsys.readouterr()
        assert "deprecated" in captured.err
        assert payload["command"] == "reexport"
        assert Path(payload["artifacts"]["project_json"]).exists()
        assert Path(payload["artifacts"]["fcpxml"]).exists()
        assert payload["stats"] == {
            "applied_evaluation_segments": 2,
            "applied_changes": 1,
            "extra_sources": 1,
            "stripped_extra_sources": 1,
        }

    @pytest.mark.asyncio
    async def test_reexport_keeps_legacy_strip_only_behavior(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
        main_path = tmp_path / "main.mp4"
        old_extra_path = tmp_path / "old-extra.mp4"
        for path in (main_path, old_extra_path):
            path.write_bytes(b"stub")

        project_path = tmp_path / "input.project.avid.json"
        output_dir = tmp_path / "output"
        _build_project(main_path, old_extra_path).save(project_path)

        payload = await cmd_reexport(
            Namespace(
                project_json=str(project_path),
                output_dir=str(output_dir),
                source=None,
                evaluation=None,
                extra_source=[],
                offset=[],
                output=None,
                silence_mode="cut",
                content_mode="disabled",
                json=True,
                manifest_out=None,
            )
        )

        captured = capsys.readouterr()
        assert "deprecated" in captured.err
        assert payload["stats"]["extra_sources"] == 0
        assert payload["stats"]["stripped_extra_sources"] == 1

        updated_project = Project.load(Path(payload["artifacts"]["project_json"]))
        assert [source.original_name for source in updated_project.source_files] == ["main.mp4"]
