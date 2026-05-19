import asyncio
import xml.etree.ElementTree as ET

from avid.export.fcpxml import FCPXMLExporter
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
    extra_angle = root.findall(".//mc-angle")[1]
    clip = extra_angle.find("./asset-clip")

    assert clip is not None
    assert clip.get("start") == "0/30000s"
    assert clip.get("duration") == "226/60s"
