"""Unit tests for FCPXML multi-source connected clips."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from avid.export.fcpxml import FCPXMLExporter
from avid.models.media import MediaFile, MediaInfo
from avid.models.project import Project
from avid.models.timeline import EditDecision, EditReason, EditType, TimeRange
from avid.models.track import Track, TrackType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_media_file(
    file_id: str,
    name: str,
    duration_ms: int = 60_000,
    *,
    is_video: bool = True,
    sample_rate: int = 48000,
) -> MediaFile:
    return MediaFile(
        id=file_id,
        path=Path(f"/media/{name}"),
        original_name=name,
        info=MediaInfo(
            duration_ms=duration_ms,
            width=1920 if is_video else None,
            height=1080 if is_video else None,
            fps=30.0 if is_video else None,
            sample_rate=sample_rate,
        ),
    )


def _build_project(
    extra_sources: list[tuple[str, str, int, bool]] | None = None,
    edit_decisions: list[EditDecision] | None = None,
) -> Project:
    """Build a test project with optional extra sources.

    Args:
        extra_sources: List of (file_id, name, offset_ms, is_video) tuples.
        edit_decisions: Optional edit decisions.
    """
    main = _make_media_file("main-id", "main.mp4", duration_ms=60_000)
    project = Project(name="Multi-Source Test")
    project.add_source_file(main)

    # Primary video track is project.get_video_tracks()[0]
    primary_video = project.get_video_tracks()[0]

    if extra_sources:
        for file_id, name, offset_ms, is_video in extra_sources:
            extra = _make_media_file(
                file_id, name, duration_ms=60_000, is_video=is_video,
            )
            created = project.add_source_file(extra)
            for track in created:
                project.set_track_offset(track.id, offset_ms)

    if edit_decisions:
        for ed in edit_decisions:
            ed.active_video_track_id = primary_video.id
            ed.active_audio_track_ids = [f"main-id_audio"]
        project.edit_decisions = edit_decisions

    return project


def _export_and_parse(project: Project) -> ET.Element:
    """Export project to FCPXML and parse back as XML."""
    import asyncio
    import tempfile

    exporter = FCPXMLExporter()

    with tempfile.TemporaryDirectory() as tmpdir:
        output = Path(tmpdir) / "test.fcpxml"
        asyncio.run(exporter.export(project, output))
        tree = ET.parse(output)

    return tree.getroot()


# ---------------------------------------------------------------------------
# Tests: Single source (backward compat)
# ---------------------------------------------------------------------------


class TestSingleSource:
    def test_no_connected_clips_for_single_source(self):
        """Single-source project should produce no connected clips."""
        project = _build_project()
        root = _export_and_parse(project)

        spine = root.find(".//spine")
        assert spine is not None

        # Single asset-clip in spine, no children
        asset_clips = spine.findall("asset-clip")
        assert len(asset_clips) == 1

        # No nested asset-clips inside the primary clip
        nested = asset_clips[0].findall("asset-clip")
        assert len(nested) == 0

    def test_single_source_with_edits(self):
        """Single-source with edits should still have no connected clips."""
        edits = [
            EditDecision(
                range=TimeRange(start_ms=5000, end_ms=10000),
                edit_type=EditType.CUT,
                reason=EditReason.SILENCE,
                confidence=0.95,
            ),
        ]
        project = _build_project(edit_decisions=edits)
        root = _export_and_parse(project)

        spine = root.find(".//spine")
        for clip in spine.findall("asset-clip"):
            nested = clip.findall("asset-clip")
            assert len(nested) == 0


# ---------------------------------------------------------------------------
# Tests: Multi-source connected clips
# ---------------------------------------------------------------------------


class TestMultiSourceNoEdits:
    def test_connected_clips_present(self):
        """Extra sources should appear as connected clips."""
        project = _build_project(
            extra_sources=[("cam2-id", "cam2.mp4", 1500, True)],
        )
        root = _export_and_parse(project)

        spine = root.find(".//spine")
        primary_clips = spine.findall("asset-clip")
        assert len(primary_clips) == 1

        # Should have connected clip as child
        connected = primary_clips[0].findall("asset-clip")
        assert len(connected) == 1
        assert connected[0].get("lane") == "-1"

    def test_connected_clip_attributes(self):
        """Connected clip should have correct lane, duration, start."""
        project = _build_project(
            extra_sources=[("cam2-id", "cam2.mp4", 1500, True)],
        )
        root = _export_and_parse(project)

        spine = root.find(".//spine")
        primary_clip = spine.findall("asset-clip")[0]
        connected = primary_clip.findall("asset-clip")[0]

        assert connected.get("lane") == "-1"
        # Connected clip should reference cam2's asset
        assert connected.get("ref") is not None
        assert connected.get("ref") != primary_clip.get("ref")  # Different asset

    def test_multiple_extra_sources(self):
        """Multiple extra sources should get lane -1, -2, etc."""
        project = _build_project(
            extra_sources=[
                ("cam2-id", "cam2.mp4", 1500, True),
                ("mic-id", "mic.wav", 800, False),
            ],
        )
        root = _export_and_parse(project)

        spine = root.find(".//spine")
        primary_clip = spine.findall("asset-clip")[0]
        connected = primary_clip.findall("asset-clip")

        assert len(connected) == 2
        lanes = {c.get("lane") for c in connected}
        assert "-1" in lanes
        assert "-2" in lanes

    def test_audio_only_extra_source(self):
        """Audio-only extra source should still produce connected clip."""
        project = _build_project(
            extra_sources=[("mic-id", "mic.wav", 800, False)],
        )
        root = _export_and_parse(project)

        spine = root.find(".//spine")
        primary_clip = spine.findall("asset-clip")[0]
        connected = primary_clip.findall("asset-clip")

        assert len(connected) == 1
        assert connected[0].get("lane") == "-1"


class TestMultiSourceWithEdits:
    def test_connected_clips_on_each_segment(self):
        """Each kept segment should have connected clips."""
        edits = [
            EditDecision(
                range=TimeRange(start_ms=10_000, end_ms=20_000),
                edit_type=EditType.CUT,
                reason=EditReason.SILENCE,
                confidence=0.95,
            ),
        ]
        project = _build_project(
            extra_sources=[("cam2-id", "cam2.mp4", 0, True)],
            edit_decisions=edits,
        )
        root = _export_and_parse(project)

        spine = root.find(".//spine")
        # With a 10s-20s cut on 60s source: should get 2 segments (0-10s, 20s-60s)
        primary_clips = spine.findall("asset-clip")
        assert len(primary_clips) == 2

        # Both segments should have connected clips
        for clip in primary_clips:
            connected = clip.findall("asset-clip")
            assert len(connected) >= 1, f"Clip has no connected clips: {clip.attrib}"

    def test_connected_clips_on_muted_segments(self):
        """MUTE (disabled) segments should also get connected clips."""
        edits = [
            EditDecision(
                range=TimeRange(start_ms=10_000, end_ms=20_000),
                edit_type=EditType.MUTE,
                reason=EditReason.BORING,
                confidence=0.8,
            ),
        ]
        project = _build_project(
            extra_sources=[("cam2-id", "cam2.mp4", 0, True)],
            edit_decisions=edits,
        )
        root = _export_and_parse(project)

        spine = root.find(".//spine")
        all_clips = spine.findall("asset-clip")

        # All clips (enabled and disabled) should have connected clips
        for clip in all_clips:
            connected = clip.findall("asset-clip")
            assert len(connected) >= 1


# ---------------------------------------------------------------------------
# Tests: Asset resources
# ---------------------------------------------------------------------------


class TestAssetResources:
    def test_all_sources_have_assets(self):
        """Every source file should get an <asset> resource."""
        project = _build_project(
            extra_sources=[
                ("cam2-id", "cam2.mp4", 1500, True),
                ("mic-id", "mic.wav", 800, False),
            ],
        )
        root = _export_and_parse(project)

        resources = root.find("resources")
        assets = resources.findall("asset")

        # 3 source files → 3 assets
        assert len(assets) == 3

    def test_assets_have_media_rep(self):
        """Each asset should have a media-rep with file path."""
        project = _build_project(
            extra_sources=[("cam2-id", "cam2.mp4", 1500, True)],
        )
        root = _export_and_parse(project)

        resources = root.find("resources")
        for asset in resources.findall("asset"):
            media_rep = asset.find("media-rep")
            assert media_rep is not None
            src = media_rep.get("src", "")
            assert src.startswith("file://")


# ---------------------------------------------------------------------------
# Tests: Offset handling in connected clips
# ---------------------------------------------------------------------------


class TestOffsetHandling:
    def test_positive_offset_shifts_start(self):
        """Positive offset means extra starts later → start should increase."""
        project = _build_project(
            extra_sources=[("cam2-id", "cam2.mp4", 2000, True)],
        )
        root = _export_and_parse(project)

        spine = root.find(".//spine")
        primary_clip = spine.findall("asset-clip")[0]
        connected = primary_clip.findall("asset-clip")[0]

        # With offset 2000ms, the connected clip's start should be 2000ms
        # in the extra source's timeline (0ms main + 2000ms offset)
        start = connected.get("start")
        assert start is not None
        # start should represent ~2000ms (2 seconds at 30fps = 60 frames)
        # Format: "60/30s" or similar
        assert start != "0/30s"  # Should not be 0

    def test_zero_offset(self):
        """Zero offset → connected clip start should match main clip start."""
        project = _build_project(
            extra_sources=[("cam2-id", "cam2.mp4", 0, True)],
        )
        root = _export_and_parse(project)

        spine = root.find(".//spine")
        primary_clip = spine.findall("asset-clip")[0]
        connected = primary_clip.findall("asset-clip")[0]

        # Main clip start is 0, offset is 0 → connected start should be 0
        main_start = primary_clip.get("start")
        connected_start = connected.get("start")
        assert connected_start == main_start


# ---------------------------------------------------------------------------
# Tests: _get_extra_source_tracks
# ---------------------------------------------------------------------------


class TestGetExtraSourceTracks:
    def test_excludes_primary_source(self):
        """Primary source should not appear in extra tracks."""
        project = _build_project(
            extra_sources=[("cam2-id", "cam2.mp4", 0, True)],
        )
        exporter = FCPXMLExporter()
        primary = project.get_video_tracks()[0]

        extras = exporter._get_extra_source_tracks(project, primary)

        source_ids = {track.source_file_id for track, _, _ in extras}
        assert "main-id" not in source_ids
        assert "cam2-id" in source_ids

    def test_one_track_per_source(self):
        """Should return only one track per source_file_id (deduplicated)."""
        project = _build_project(
            extra_sources=[("cam2-id", "cam2.mp4", 0, True)],
        )
        exporter = FCPXMLExporter()
        primary = project.get_video_tracks()[0]

        extras = exporter._get_extra_source_tracks(project, primary)

        # cam2 has both video and audio tracks, but only one should be returned
        assert len(extras) == 1

    def test_lane_numbering(self):
        """Lanes should be -1, -2, -3, ..."""
        project = _build_project(
            extra_sources=[
                ("cam2-id", "cam2.mp4", 0, True),
                ("cam3-id", "cam3.mp4", 0, True),
                ("mic-id", "mic.wav", 0, False),
            ],
        )
        exporter = FCPXMLExporter()
        primary = project.get_video_tracks()[0]

        extras = exporter._get_extra_source_tracks(project, primary)

        lanes = [lane for _, _, lane in extras]
        assert lanes == [-1, -2, -3]

    def test_empty_when_single_source(self):
        """No extra tracks for single-source project."""
        project = _build_project()
        exporter = FCPXMLExporter()
        primary = project.get_video_tracks()[0]

        extras = exporter._get_extra_source_tracks(project, primary)
        assert extras == []
