"""Unit tests for export-project CLI command."""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from avid.cli import cmd_export_project
from avid.models.media import MediaFile, MediaInfo
from avid.models.project import Project, TranscriptSegment, Transcription
from avid.models.timeline import EditDecision, EditReason, EditType, TimeRange


def _build_project() -> Project:
    project = Project(name="export-project-test")
    media = MediaFile(
        id="main-id",
        path=Path("/media/main.mp4"),
        original_name="main.mp4",
        info=MediaInfo(
            duration_ms=12_000,
            width=1920,
            height=1080,
            fps=30.0,
            sample_rate=48_000,
        ),
    )
    project.add_source_file(media)
    audio_track = project.get_audio_tracks()[0]
    video_track = project.get_video_tracks()[0]
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
            reason=EditReason.SILENCE,
            confidence=1.0,
            active_video_track_id=video_track.id,
            active_audio_track_ids=[audio_track.id],
        ),
        EditDecision(
            range=TimeRange(start_ms=4_000, end_ms=5_000),
            edit_type=EditType.CUT,
            reason=EditReason.FILLER,
            confidence=1.0,
            active_video_track_id=video_track.id,
            active_audio_track_ids=[audio_track.id],
        ),
    ]
    return project


class TestExportProject:
    @pytest.mark.asyncio
    async def test_export_project_writes_fcpxml_and_srt(self, tmp_path: Path):
        project_path = tmp_path / "input.project.avid.json"
        output_dir = tmp_path / "output"
        _build_project().save(project_path)

        payload = await cmd_export_project(
            Namespace(
                project_json=str(project_path),
                output_dir=str(output_dir),
                output=None,
                silence_mode="cut",
                content_mode="disabled",
                json=True,
                manifest_out=None,
            )
        )

        assert payload["command"] == "export-project"
        fcpxml_path = Path(payload["artifacts"]["fcpxml"])
        srt_path = Path(payload["artifacts"]["srt"])
        assert fcpxml_path.exists()
        assert srt_path.exists()
        assert fcpxml_path.name == "main_subtitle_cut.fcpxml"

        root = ET.parse(fcpxml_path).getroot()
        assert root.tag == "fcpxml"
        srt_text = srt_path.read_text(encoding="utf-8")
        assert "00:00:00,000 --> 00:00:00,500" in srt_text
        assert "인트로" in srt_text
        assert "본문" in srt_text

    @pytest.mark.asyncio
    async def test_export_project_respects_output_override(self, tmp_path: Path):
        project_path = tmp_path / "input.project.avid.json"
        output_dir = tmp_path / "output"
        output_path = tmp_path / "custom-name"
        _build_project().save(project_path)

        payload = await cmd_export_project(
            Namespace(
                project_json=str(project_path),
                output_dir=str(output_dir),
                output=str(output_path),
                silence_mode="cut",
                content_mode="cut",
                json=True,
                manifest_out=None,
            )
        )

        fcpxml_path = Path(payload["artifacts"]["fcpxml"])
        assert fcpxml_path.name == "custom-name.fcpxml"
        assert fcpxml_path.exists()

    @pytest.mark.asyncio
    async def test_export_project_missing_project_exits(self, tmp_path: Path):
        with pytest.raises(SystemExit) as exc_info:
            await cmd_export_project(
                Namespace(
                    project_json=str(tmp_path / "missing.project.avid.json"),
                    output_dir=str(tmp_path / "output"),
                    output=None,
                    silence_mode="cut",
                    content_mode="disabled",
                    json=True,
                    manifest_out=None,
                )
            )

        assert exc_info.value.code == 1
