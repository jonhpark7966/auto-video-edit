import asyncio
import json
import xml.etree.ElementTree as ET

from avid.export.fcpxml import FCPXMLExporter, _TimelineClipPlan
from avid.models.media import MediaFile, MediaInfo
from avid.models.project import Project
from avid.models.timeline import EditDecision, EditReason, EditType, TimeRange
from avid.models.track import Track, TrackType


def _video_source(
    tmp_path,
    source_id: str,
    name: str,
    duration_ms: int = 10_000,
    fps: float = 30.0,
    sample_rate: int | None = 48_000,
    audio_channels: int | None = 2,
    audio_sources: int | None = 1,
    video_frame_count: int | None = None,
    timecode: str | None = None,
    timecode_rate: str | None = None,
    timecode_start_frames: int | None = None,
    timecode_start_seconds: str | None = None,
) -> MediaFile:
    return MediaFile(
        id=source_id,
        path=tmp_path / name,
        original_name=name,
        info=MediaInfo(
            duration_ms=duration_ms,
            width=1920,
            height=1080,
            fps=fps,
            sample_rate=sample_rate,
            audio_channels=audio_channels,
            audio_sources=audio_sources,
            video_frame_count=video_frame_count,
            timecode=timecode,
            timecode_rate=timecode_rate,
            timecode_start_frames=timecode_start_frames,
            timecode_start_seconds=timecode_start_seconds,
        ),
    )


def test_multicam_export_uses_mc_clip_timeline(tmp_path):
    main = _video_source(tmp_path, "main", "main.mov")
    extra = _video_source(tmp_path, "extra", "extra.mov")
    project = Project(
        name="Multicam Test",
        source_files=[main, extra],
        tracks=[
            Track(id="main_video", source_file_id="main", track_type=TrackType.VIDEO),
            Track(id="main_audio", source_file_id="main", track_type=TrackType.AUDIO),
            Track(
                id="extra_video",
                source_file_id="extra",
                track_type=TrackType.VIDEO,
                offset_ms=1_000,
            ),
            Track(
                id="extra_audio",
                source_file_id="extra",
                track_type=TrackType.AUDIO,
                offset_ms=1_000,
            ),
        ],
        edit_decisions=[
            EditDecision(
                range=TimeRange(start_ms=2_000, end_ms=4_000),
                edit_type=EditType.CUT,
                reason=EditReason.SILENCE,
                active_video_track_id="main_video",
            )
        ],
    )

    output_path = tmp_path / "out.fcpxml"
    asyncio.run(FCPXMLExporter().export(project, output_path))

    root = ET.parse(output_path).getroot()
    media = root.find("./resources/media")
    assert media is not None
    assert media.find("./multicam") is not None
    assert len(root.findall(".//mc-angle")) == 2
    assert len(root.findall("./library/event/project/sequence/spine/mc-clip")) == 2
    assert not root.findall("./library/event/project/sequence/spine/asset-clip")

    extra_angle = root.findall(".//mc-angle")[1]
    assert extra_angle.find("./gap") is not None
    assert extra_angle.find("./asset-clip") is not None


def test_single_source_export_keeps_asset_clip_timeline(tmp_path):
    main = _video_source(tmp_path, "main", "main.mov")
    project = Project(
        name="Single Source Test",
        source_files=[main],
        tracks=[
            Track(id="main_video", source_file_id="main", track_type=TrackType.VIDEO),
            Track(id="main_audio", source_file_id="main", track_type=TrackType.AUDIO),
        ],
    )

    output_path = tmp_path / "out.fcpxml"
    asyncio.run(FCPXMLExporter().export(project, output_path))

    root = ET.parse(output_path).getroot()
    assert root.find("./resources/media") is None
    assert not root.findall("./library/event/project/sequence/spine/mc-clip")
    assert len(root.findall("./library/event/project/sequence/spine/asset-clip")) == 1
    asset = root.find("./resources/asset")
    assert asset is not None
    assert asset.get("start") == "0s"


def test_timecoded_multicam_source_start_matches_asset_and_angle_clip(tmp_path):
    main = _video_source(
        tmp_path,
        "main",
        "A001_06212101_C002.mov",
        duration_ms=10_000,
        fps=60.0,
        video_frame_count=600,
        timecode="21:01:07:00",
        timecode_rate="60/1",
        timecode_start_frames=4_540_020,
        timecode_start_seconds="4540020/60",
    )
    extra = _video_source(
        tmp_path,
        "extra",
        "A001_06212101_D247.mov",
        duration_ms=10_000,
        fps=60.0,
        video_frame_count=600,
        timecode="21:01:12:00",
        timecode_rate="60/1",
        timecode_start_frames=4_540_320,
        timecode_start_seconds="4540320/60",
    )
    project = Project(
        name="Timecoded Multicam Test",
        source_files=[main, extra],
        tracks=[
            Track(id="main_video", source_file_id="main", track_type=TrackType.VIDEO),
            Track(id="main_audio", source_file_id="main", track_type=TrackType.AUDIO),
            Track(id="extra_video", source_file_id="extra", track_type=TrackType.VIDEO),
            Track(id="extra_audio", source_file_id="extra", track_type=TrackType.AUDIO),
        ],
    )

    output_path = tmp_path / "out.fcpxml"
    asyncio.run(FCPXMLExporter().export(project, output_path))

    root = ET.parse(output_path).getroot()
    assets = {
        asset.get("id"): asset
        for asset in root.findall("./resources/asset")
        if asset.get("id")
    }
    assert assets

    for angle_clip in root.findall(".//mc-angle/asset-clip"):
        asset = assets[angle_clip.get("ref")]
        assert asset.get("start") != "0s"
        assert angle_clip.get("start") == asset.get("start")


def test_asset_audio_metadata_uses_source_values(tmp_path):
    main = _video_source(
        tmp_path,
        "main",
        "surround.mov",
        sample_rate=48_000,
        audio_channels=6,
        audio_sources=1,
    )
    project = Project(
        name="Surround Source Test",
        source_files=[main],
        tracks=[
            Track(id="main_video", source_file_id="main", track_type=TrackType.VIDEO),
            Track(id="main_audio", source_file_id="main", track_type=TrackType.AUDIO),
        ],
    )

    output_path = tmp_path / "out.fcpxml"
    asyncio.run(FCPXMLExporter().export(project, output_path))

    root = ET.parse(output_path).getroot()
    asset = root.find("./resources/asset")

    assert asset is not None
    assert asset.get("hasAudio") == "1"
    assert asset.get("audioRate") == "48000"
    assert asset.get("audioChannels") == "6"
    assert asset.get("audioSources") == "1"


def test_asset_audio_metadata_omits_unknown_counts(tmp_path):
    main = _video_source(
        tmp_path,
        "main",
        "legacy.mov",
        sample_rate=48_000,
        audio_channels=None,
        audio_sources=None,
    )
    project = Project(
        name="Legacy Source Test",
        source_files=[main],
        tracks=[
            Track(id="main_video", source_file_id="main", track_type=TrackType.VIDEO),
            Track(id="main_audio", source_file_id="main", track_type=TrackType.AUDIO),
        ],
    )

    output_path = tmp_path / "out.fcpxml"
    asyncio.run(FCPXMLExporter().export(project, output_path))

    root = ET.parse(output_path).getroot()
    asset = root.find("./resources/asset")

    assert asset is not None
    assert asset.get("hasAudio") == "1"
    assert asset.get("audioRate") == "48000"
    assert "audioChannels" not in asset.attrib
    assert "audioSources" not in asset.attrib


def test_asset_has_audio_when_sample_rate_is_unknown(tmp_path):
    main = _video_source(
        tmp_path,
        "main",
        "unknown-rate.mov",
        sample_rate=None,
        audio_channels=1,
        audio_sources=1,
    )
    project = Project(
        name="Unknown Rate Source Test",
        source_files=[main],
        tracks=[
            Track(id="main_video", source_file_id="main", track_type=TrackType.VIDEO),
            Track(id="main_audio", source_file_id="main", track_type=TrackType.AUDIO),
        ],
    )

    output_path = tmp_path / "out.fcpxml"
    asyncio.run(FCPXMLExporter().export(project, output_path))

    root = ET.parse(output_path).getroot()
    asset = root.find("./resources/asset")

    assert asset is not None
    assert asset.get("hasAudio") == "1"
    assert "audioRate" not in asset.attrib
    assert asset.get("audioChannels") == "1"
    assert asset.get("audioSources") == "1"


def test_timeline_boundaries_use_nearest_primary_frames(tmp_path):
    main = _video_source(tmp_path, "main", "main.mov", duration_ms=5_000, fps=60.0)
    project = Project(
        name="Nearest Frame Test",
        source_files=[main],
        tracks=[
            Track(id="main_video", source_file_id="main", track_type=TrackType.VIDEO),
            Track(id="main_audio", source_file_id="main", track_type=TrackType.AUDIO),
        ],
        edit_decisions=[
            EditDecision(
                range=TimeRange(start_ms=0, end_ms=126),
                edit_type=EditType.CUT,
                reason=EditReason.SILENCE,
                active_video_track_id="main_video",
            )
        ],
    )

    output_path = tmp_path / "out.fcpxml"
    asyncio.run(FCPXMLExporter().export(project, output_path))

    root = ET.parse(output_path).getroot()
    clip = root.find("./library/event/project/sequence/spine/asset-clip")

    assert clip is not None
    assert clip.get("start") == "8/60s"
    assert clip.get("duration") == "292/60s"


def test_timeline_plan_duration_uses_explicit_offsets():
    exporter = FCPXMLExporter()
    timeline_plan = [
        _TimelineClipPlan(
            source_start_ms=0,
            source_end_ms=2_000,
            start_frames=0,
            duration_frames=120,
            timeline_offset_frames=57,
            enabled=True,
        ),
        _TimelineClipPlan(
            source_start_ms=2_000,
            source_end_ms=3_000,
            start_frames=120,
            duration_frames=60,
            timeline_offset_frames=177,
            enabled=True,
        ),
    ]

    assert exporter._timeline_plan_duration_frames(timeline_plan) == 237


def test_connected_clip_duration_uses_primary_frame_boundary_for_mixed_rate(tmp_path):
    exporter = FCPXMLExporter()
    parent = ET.Element("asset-clip", format="r1")
    extra = _video_source(tmp_path, "extra", "facecam.mov", duration_ms=10_000, fps=29.97)
    track = Track(id="extra_video", source_file_id="extra", track_type=TrackType.VIDEO)

    exporter._add_connected_clips(
        parent,
        main_start_ms=0,
        main_end_ms=3_767,
        extra_tracks=[(track, extra, -1)],
        timeline_duration_frames=226,
        asset_map={"extra": "r2"},
        source_format_map={"extra": ("r2", 29.97)},
        primary_fps=60.0,
    )

    clip = parent.find("./asset-clip")

    assert clip is not None
    assert clip.get("offset") == "0/60s"
    assert clip.get("start") == "0/30000s"
    assert clip.get("duration") == "226/60s"


def test_mixed_rate_multicam_angle_uses_primary_frame_boundary(tmp_path):
    main = _video_source(tmp_path, "main", "main.mov", duration_ms=10_000, fps=60.0)
    extra = _video_source(tmp_path, "extra", "facecam.mov", duration_ms=3_767, fps=29.97)
    project = Project(
        name="Mixed Rate Multicam",
        source_files=[main, extra],
        tracks=[
            Track(id="main_video", source_file_id="main", track_type=TrackType.VIDEO),
            Track(id="main_audio", source_file_id="main", track_type=TrackType.AUDIO),
            Track(id="extra_video", source_file_id="extra", track_type=TrackType.VIDEO),
            Track(id="extra_audio", source_file_id="extra", track_type=TrackType.AUDIO),
        ],
    )

    output_path = tmp_path / "out.fcpxml"
    asyncio.run(FCPXMLExporter().export(project, output_path))

    root = ET.parse(output_path).getroot()
    formats = {
        item.get("id"): item
        for item in root.findall("./resources/format")
        if item.get("id")
    }
    multicam = root.find("./resources/media/multicam")
    assert multicam is not None
    base_format = formats[multicam.get("format")]
    assert base_format.get("frameDuration") == "1001/30000s"

    main_angle = root.findall(".//mc-angle")[0]
    extra_angle = root.findall(".//mc-angle")[1]
    main_clip = main_angle.find("./asset-clip")
    clip = extra_angle.find("./asset-clip")

    assert main_clip is not None
    main_conform = main_clip.find("./conform-rate")
    assert main_conform is not None
    assert main_conform.get("srcFrameRate") == "60"
    assert clip is not None
    assert clip.get("start") == "0/30000s"
    assert clip.get("duration") == "226/60s"
    assert clip.find("./conform-rate") is None

    spine_clip = root.find("./library/event/project/sequence/spine/mc-clip")
    assert spine_clip is not None
    spine_conform = spine_clip.find("./conform-rate")
    assert spine_conform is not None
    assert spine_conform.get("srcFrameRate") == "29.97"


def test_refresh_primary_source_media_updates_info_without_changing_id(tmp_path, monkeypatch):
    from avid import cli

    main = _video_source(
        tmp_path,
        "main",
        "source.mp4",
        duration_ms=305_017,
        fps=60.0,
        sample_rate=44_100,
    )
    project = Project(
        name="Refresh Source Test",
        source_files=[main],
        tracks=[
            Track(id="main_video", source_file_id="main", track_type=TrackType.VIDEO),
            Track(id="main_audio", source_file_id="main", track_type=TrackType.AUDIO),
        ],
    )
    refreshed_path = tmp_path / "source.mp4"
    refreshed_info = MediaInfo(
        duration_ms=305_000,
        width=1920,
        height=1080,
        fps=60.0,
        sample_rate=44_100,
        audio_channels=2,
        audio_sources=1,
    )

    async def fake_create_media_file(self, path):
        return MediaFile(
            id="new-main-id",
            path=path,
            original_name=path.name,
            info=refreshed_info,
        )

    monkeypatch.setattr(
        "avid.services.media.MediaService.create_media_file",
        fake_create_media_file,
    )

    asyncio.run(cli._refresh_primary_source_media(project, refreshed_path))

    assert project.source_files[0].id == "main"
    assert project.source_files[0].path == refreshed_path
    assert project.source_files[0].original_name == "source.mp4"
    assert project.source_files[0].info.duration_ms == 305_000
    assert [track.source_file_id for track in project.tracks] == ["main", "main"]


def test_rebuild_multicam_from_manifest_uses_metadata_without_source_files(tmp_path, monkeypatch):
    from avid import cli

    project = Project(
        name="Manifest Multicam Test",
        source_files=[
            _video_source(tmp_path, "main", "old_source.mp4", duration_ms=10_000),
        ],
        tracks=[
            Track(id="main_video", source_file_id="main", track_type=TrackType.VIDEO),
            Track(id="main_audio", source_file_id="main", track_type=TrackType.AUDIO),
        ],
    )

    primary_info = tmp_path / "primary_media_info.json"
    extra_info = tmp_path / "extra_media_info.json"
    media_info = {
        "duration_ms": 10_000,
        "width": 1920,
        "height": 1080,
        "fps": 30.0,
        "sample_rate": 48_000,
        "audio_channels": 2,
        "audio_sources": 1,
    }
    primary_info.write_text(json.dumps({"media_info": media_info}), encoding="utf-8")
    extra_info.write_text(json.dumps({"media_info": media_info}), encoding="utf-8")
    manifest = tmp_path / "multicam_sources.json"
    manifest.write_text(
        json.dumps({
            "schema_version": "avid.multicam_sources.v1",
            "primary": {
                "original_name": "primary.mp4",
                "path_hint": str(tmp_path / "missing_primary.mp4"),
                "media_info_path": str(primary_info),
                "audio_proxy_path": str(tmp_path / "primary.flac"),
            },
            "extras": [
                {
                    "original_name": "extra.mov",
                    "path_hint": str(tmp_path / "missing_extra.mov"),
                    "media_info_path": str(extra_info),
                    "audio_proxy_path": str(tmp_path / "extra.flac"),
                    "offset_ms": 1234,
                }
            ],
        }),
        encoding="utf-8",
    )

    async def fake_estimate_drift(self, main_path, extra_path, initial_offset_ms):
        return None

    monkeypatch.setattr(
        "avid.services.audio_sync.AudioSyncService.estimate_drift",
        fake_estimate_drift,
    )

    sync_results = asyncio.run(cli._rebuild_multicam_from_manifest_in_place(project, manifest))

    assert len(sync_results) == 1
    assert sync_results[0].offset_ms == 1234
    assert project.source_files[0].original_name == "primary.mp4"
    assert project.source_files[1].original_name == "extra.mov"
    assert project.source_files[1].path == tmp_path / "missing_extra.mov"
    extra_offsets = [
        track.offset_ms
        for track in project.tracks
        if track.source_file_id == project.source_files[1].id
    ]
    assert extra_offsets == [1234, 1234]
