"""Unit tests for clear-extra-sources CLI command."""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path

import pytest

from avid.cli import cmd_clear_extra_sources
from avid.models.media import MediaFile, MediaInfo
from avid.models.project import Project


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


def _build_project(extra_count: int) -> Project:
    project = Project(name="clear-extra-sources-test")
    project.add_source_file(_media_file("main-id", Path("/media/main.mp4")))
    for index in range(extra_count):
        extra_media = _media_file(f"extra-{index}", Path(f"/media/extra-{index}.mp4"))
        created_tracks = project.add_source_file(extra_media)
        for track in created_tracks:
            project.set_track_offset(track.id, 500 + index)
    return project


class TestClearExtraSources:
    def test_clear_extra_sources_strips_all_non_primary_sources(self, tmp_path: Path):
        project_path = tmp_path / "input.project.avid.json"
        output_path = tmp_path / "output.project.avid.json"
        _build_project(extra_count=2).save(project_path)

        payload = cmd_clear_extra_sources(
            Namespace(
                project_json=str(project_path),
                output_project_json=str(output_path),
                json=True,
                manifest_out=None,
            )
        )

        assert payload["command"] == "clear-extra-sources"
        assert payload["artifacts"]["project_json"] == str(output_path)
        assert payload["stats"] == {"stripped_extra_sources": 2}

        cleared = Project.load(output_path)
        assert [source.original_name for source in cleared.source_files] == ["main.mp4"]
        assert all(track.source_file_id == "main-id" for track in cleared.tracks)

    def test_clear_extra_sources_is_noop_for_single_source(self, tmp_path: Path):
        project_path = tmp_path / "input.project.avid.json"
        output_path = tmp_path / "output"
        _build_project(extra_count=0).save(project_path)

        payload = cmd_clear_extra_sources(
            Namespace(
                project_json=str(project_path),
                output_project_json=str(output_path),
                json=True,
                manifest_out=None,
            )
        )

        assert payload["stats"] == {"stripped_extra_sources": 0}
        saved_path = Path(payload["artifacts"]["project_json"])
        assert saved_path.name == "output.avid.json"

    def test_clear_extra_sources_missing_project_exits(self, tmp_path: Path):
        with pytest.raises(SystemExit) as exc_info:
            cmd_clear_extra_sources(
                Namespace(
                    project_json=str(tmp_path / "missing.project.avid.json"),
                    output_project_json=str(tmp_path / "output.project.avid.json"),
                    json=True,
                    manifest_out=None,
                )
            )

        assert exc_info.value.code == 1
