"""Unit tests for rebuild-multicam CLI command."""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path

import pytest

from avid.cli import cmd_rebuild_multicam
from avid.models.media import MediaFile, MediaInfo
from avid.models.project import Project
from avid.services.audio_sync import SyncResult


def _media_file(file_id: str, path: Path) -> MediaFile:
    return MediaFile(
        id=file_id,
        path=path,
        original_name=path.name,
        info=MediaInfo(
            duration_ms=20_000,
            width=1920 if path.suffix != ".wav" else None,
            height=1080 if path.suffix != ".wav" else None,
            fps=30.0 if path.suffix != ".wav" else None,
            sample_rate=48_000,
        ),
    )


def _build_project_with_old_extra(main_path: Path, old_extra_path: Path) -> Project:
    project = Project(name="rebuild-multicam-test")
    project.add_source_file(_media_file("main-id", main_path))
    old_extra = _media_file("old-extra-id", old_extra_path)
    created_tracks = project.add_source_file(old_extra)
    for track in created_tracks:
        project.set_track_offset(track.id, 900)
    return project


class TestRebuildMulticam:
    @pytest.mark.asyncio
    async def test_rebuild_multicam_strips_and_replaces_extra_sources(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        main_path = tmp_path / "main.mp4"
        old_extra_path = tmp_path / "old-cam.mp4"
        new_extra_path = tmp_path / "new-cam.mp4"
        for path in (main_path, old_extra_path, new_extra_path):
            path.write_bytes(b"stub")

        project_path = tmp_path / "input.project.avid.json"
        output_path = tmp_path / "output.project.avid.json"
        _build_project_with_old_extra(main_path, old_extra_path).save(project_path)

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

        payload = await cmd_rebuild_multicam(
            Namespace(
                project_json=str(project_path),
                source=str(main_path),
                extra_source=[str(new_extra_path)],
                offset=["1200"],
                output_project_json=str(output_path),
                json=True,
                manifest_out=None,
            )
        )

        assert payload["command"] == "rebuild-multicam"
        assert payload["artifacts"]["project_json"] == str(output_path)
        assert payload["stats"] == {
            "extra_sources": 1,
            "stripped_extra_sources": 1,
        }

        rebuilt = Project.load(output_path)
        assert [source.original_name for source in rebuilt.source_files] == ["main.mp4", "new-cam.mp4"]
        new_tracks = [track for track in rebuilt.tracks if track.source_file_id == "new-extra-id"]
        assert len(new_tracks) == 2
        assert {track.offset_ms for track in new_tracks} == {1200}

    @pytest.mark.asyncio
    async def test_rebuild_multicam_requires_extra_source(self, tmp_path: Path):
        main_path = tmp_path / "main.mp4"
        main_path.write_bytes(b"stub")
        project_path = tmp_path / "input.project.avid.json"
        _build_project_with_old_extra(main_path, tmp_path / "old-cam.mp4").save(project_path)

        with pytest.raises(SystemExit) as exc_info:
            await cmd_rebuild_multicam(
                Namespace(
                    project_json=str(project_path),
                    source=str(main_path),
                    extra_source=[],
                    offset=[],
                    output_project_json=str(tmp_path / "output.project.avid.json"),
                    json=True,
                    manifest_out=None,
                )
            )

        assert exc_info.value.code == 1
