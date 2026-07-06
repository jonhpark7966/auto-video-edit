import asyncio
from fractions import Fraction
from pathlib import Path
from xml.etree import ElementTree as ET

from avid.export.fcpxml import FCPXMLExporter
from avid.models.media import MediaFile, MediaInfo
from avid.models.project import MulticamSettings, Project, Transcription, TranscriptSegment
from avid.models.timeline import EditDecision, EditReason, EditType, TimeRange
from avid.models.track import Track, TrackType


def _video_file(
    file_id: str,
    path: Path,
    original_name: str,
    duration_ms: int,
    width: int,
    height: int,
    fps: float,
    frame_count: int,
) -> MediaFile:
    return MediaFile(
        id=file_id,
        path=path,
        original_name=original_name,
        info=MediaInfo(
            duration_ms=duration_ms,
            width=width,
            height=height,
            fps=fps,
            sample_rate=48000,
            audio_channels=2,
            video_frame_count=frame_count,
        ),
    )


def _project(
    tmp_path: Path,
    cut_from_ms: int | None = None,
    extra_offset_ms: int = 0,
) -> Project:
    source = _video_file(
        "source",
        tmp_path / "source.mp4",
        "source.mp4",
        duration_ms=10000,
        width=1920,
        height=1080,
        fps=60.0,
        frame_count=600,
    )
    extra = _video_file(
        "extra",
        tmp_path / "extra_0.mov",
        "extra_0.mov",
        duration_ms=10010,
        width=3840,
        height=2160,
        fps=29.97,
        frame_count=300,
    )
    project = Project(
        name="fcpxml_probe",
        source_files=[source, extra],
        tracks=[
            Track(id="source_video", source_file_id="source", track_type=TrackType.VIDEO),
            Track(
                id="extra_video",
                source_file_id="extra",
                track_type=TrackType.VIDEO,
                offset_ms=extra_offset_ms,
            ),
        ],
    )
    if cut_from_ms is not None:
        project.edit_decisions.append(
            EditDecision(
                range=TimeRange(start_ms=cut_from_ms, end_ms=10000),
                edit_type=EditType.CUT,
                reason=EditReason.MANUAL,
                active_video_track_id="source_video",
            )
        )
    return project


def _multicam_media(root):
    for media in root.findall("./resources/media"):
        multicam = media.find("multicam")
        if multicam is not None:
            return media, multicam
    raise AssertionError("missing multicam media resource")


def _timeline_mc_clips(root):
    return root.findall("./library/event/project/sequence/spine/mc-clip")


def _asset_format(root, asset_name: str) -> str:
    for asset in root.findall("./resources/asset"):
        if asset.get("name") == asset_name:
            fmt = asset.get("format")
            assert fmt is not None
            return fmt
    raise AssertionError(f"missing asset {asset_name}")


def _asset_duration(root, asset_name: str) -> str:
    for asset in root.findall("./resources/asset"):
        if asset.get("name") == asset_name:
            duration = asset.get("duration")
            assert duration is not None
            return duration
    raise AssertionError(f"missing asset {asset_name}")


def _asset_start(root, asset_name: str) -> str:
    for asset in root.findall("./resources/asset"):
        if asset.get("name") == asset_name:
            start = asset.get("start")
            assert start is not None
            return start
    raise AssertionError(f"missing asset {asset_name}")


def _asset_media_src(root, asset_name: str) -> str:
    for asset in root.findall("./resources/asset"):
        if asset.get("name") == asset_name:
            media_rep = asset.find("media-rep")
            assert media_rep is not None
            src = media_rep.get("src")
            assert src is not None
            return src
    raise AssertionError(f"missing asset {asset_name}")


def _format_frame_duration(root, format_id: str) -> str:
    for fmt in root.findall("./resources/format"):
        if fmt.get("id") == format_id:
            frame_duration = fmt.get("frameDuration")
            assert frame_duration is not None
            return frame_duration
    raise AssertionError(f"missing format {format_id}")


def test_extra_source_exports_native_multicam_angles(tmp_path: Path) -> None:
    root = FCPXMLExporter()._create_fcpxml_structure(_project(tmp_path))

    media, multicam = _multicam_media(root)
    angles = multicam.findall("mc-angle")
    source_clip = angles[0].find("asset-clip")
    extra_clip = angles[1].find("asset-clip")
    timeline_clips = _timeline_mc_clips(root)
    event_clip = root.find("./library/event/mc-clip")

    assert media.get("name") == "source_multicam"
    assert [angle.get("angleID") for angle in angles] == ["a1", "a2"]
    assert [angle.get("name") for angle in angles] == ["source", "extra_0"]

    # Multicam base = the lowest-fps angle (the 29.97 camera), so the camera
    # angle sits 1:1 and the 60fps source angle is the one conformed.  This
    # mirrors FCP's own "New Multicam Clip" and avoids the in-angle frame-rate
    # conform that previously made the camera drift ~0.1% over the run.
    assert multicam.get("format") == _asset_format(root, "extra_0")

    assert source_clip is not None
    assert source_clip.get("offset") == "0/30000s"
    assert source_clip.get("start") == "0s"
    assert source_clip.get("duration") == "299299/30000s"
    assert source_clip.get("format") == _asset_format(root, "source")
    source_conform = source_clip.find("conform-rate")
    assert source_conform is not None
    assert source_conform.get("srcFrameRate") == "60"

    assert extra_clip is not None
    assert extra_clip.get("offset") == "0/30000s"
    assert extra_clip.get("start") == "0s"
    assert _asset_duration(root, "extra_0") == "300300/30000s"
    # camera angle is 1:1 -> clip duration equals the asset duration, with no
    # timeMap retime and no conform-rate.
    assert extra_clip.get("duration") == "300300/30000s"
    assert extra_clip.get("duration") == _asset_duration(root, "extra_0")
    assert extra_clip.get("format") == _asset_format(root, "extra_0")
    assert extra_clip.find("timeMap") is None
    assert extra_clip.find("conform-rate") is None
    conform = extra_clip.find("adjust-conform")
    assert conform is not None
    assert conform.get("type") == "fit"

    assert len(timeline_clips) == 1
    assert timeline_clips[0].get("ref") == media.get("id")
    assert timeline_clips[0].get("offset") == "0/60s"
    assert timeline_clips[0].get("start") == "0/60s"
    assert timeline_clips[0].get("duration") == "600/60s"
    # multicam(29.97) -> sequence(60) conform happens once, at the spine mc-clip
    timeline_conform = timeline_clips[0].find("conform-rate")
    assert timeline_conform is not None
    assert timeline_conform.get("srcFrameRate") == "29.97"
    assert timeline_clips[0].find("mc-source").get("angleID") == "a1"
    assert root.find("./library/event/project/sequence/spine/asset-clip") is None

    assert event_clip is not None
    assert event_clip.get("ref") == media.get("id")


def test_positive_extra_offset_exports_leading_gap_in_multicam_angle(
    tmp_path: Path,
) -> None:
    root = FCPXMLExporter()._create_fcpxml_structure(
        _project(tmp_path, extra_offset_ms=21104)
    )

    _, multicam = _multicam_media(root)
    angles = multicam.findall("mc-angle")
    source_children = list(angles[0])
    extra_children = list(angles[1])
    event_clip = root.find("./library/event/mc-clip")

    assert [child.tag for child in source_children] == ["asset-clip"]
    assert [child.tag for child in extra_children] == ["gap", "asset-clip"]

    gap = extra_children[0]
    extra_clip = extra_children[1]

    assert gap.get("name") == "Gap"
    assert gap.get("offset") == "0s"
    assert gap.get("start") == "0s"
    # leading gap is expressed in the multicam base (29.97) timebase now
    assert gap.get("duration") == "632632/30000s"
    assert extra_clip.get("offset") == gap.get("duration")
    assert extra_clip.get("start") == "0s"

    assert event_clip is not None
    assert event_clip.get("duration") == "1866/60s"


def test_multicam_clip_duration_uses_sequence_frames_for_edit_boundaries(
    tmp_path: Path,
) -> None:
    root = FCPXMLExporter()._create_fcpxml_structure(_project(tmp_path, cut_from_ms=2135))

    timeline_clips = _timeline_mc_clips(root)

    assert len(timeline_clips) == 1
    assert timeline_clips[0].get("offset") == "0/60s"
    assert timeline_clips[0].get("start") == "0/60s"
    assert timeline_clips[0].get("duration") == "128/60s"
    assert timeline_clips[0].find("asset-clip") is None


def test_negative_extra_offset_normalizes_multicam_angle_offsets(tmp_path: Path) -> None:
    root = FCPXMLExporter()._create_fcpxml_structure(
        _project(tmp_path, extra_offset_ms=-500)
    )

    _, multicam = _multicam_media(root)
    angles = multicam.findall("mc-angle")
    source_children = list(angles[0])
    extra_children = list(angles[1])
    source_gap = source_children[0]
    source_clip = source_children[1]
    extra_clip = extra_children[0]
    timeline_clip = _timeline_mc_clips(root)[0]

    assert [child.tag for child in source_children] == ["gap", "asset-clip"]
    assert [child.tag for child in extra_children] == ["asset-clip"]
    assert source_gap.get("offset") == "0s"
    assert source_gap.get("start") == "0s"
    # offsets inside the multicam are in the base (29.97) timebase; 15015/30000s
    # == 30/60s == 0.5s.
    assert source_gap.get("duration") == "15015/30000s"
    assert source_clip.get("offset") == source_gap.get("duration")
    assert extra_clip.get("offset") == "0/30000s"
    assert timeline_clip.get("start") == "30/60s"
    assert timeline_clip.get("duration") == "600/60s"


def _time_fraction(value: str | None) -> Fraction:
    assert value is not None
    raw = value[:-1] if value.endswith("s") else value
    if "/" in raw:
        numerator, denominator = raw.split("/", 1)
        return Fraction(int(numerator), int(denominator))
    return Fraction(raw)


def test_sequence_duration_uses_frame_snapped_review_timeline_plan(
    tmp_path: Path,
) -> None:
    source = _video_file(
        "source",
        tmp_path / "source.mp4",
        "source.mp4",
        duration_ms=1000,
        width=1920,
        height=1080,
        fps=60.0,
        frame_count=60,
    )
    project = Project(
        name="review_rounding_probe",
        source_files=[source],
        tracks=[
            Track(id="source_video", source_file_id="source", track_type=TrackType.VIDEO),
        ],
        transcription=Transcription(
            source_track_id="source_audio",
            segments=[
                TranscriptSegment(index=1, start_ms=0, end_ms=9, text="keep one"),
                TranscriptSegment(index=2, start_ms=9, end_ms=18, text="cut two"),
                TranscriptSegment(index=3, start_ms=18, end_ms=27, text="keep three"),
            ],
        ),
        edit_decisions=[
            EditDecision(
                range=TimeRange(start_ms=9, end_ms=18),
                edit_type=EditType.CUT,
                reason=EditReason.SILENCE,
                active_video_track_id="source_video",
                source_segment_index=2,
            ),
        ],
    )

    root = FCPXMLExporter()._create_fcpxml_structure(project)
    sequence = root.find("./library/event/project/sequence")
    clips = root.findall("./library/event/project/sequence/spine/asset-clip")

    assert sequence is not None
    assert sequence.get("duration") == "2/60s"
    assert [(clip.get("start"), clip.get("duration")) for clip in clips] == [
        ("0/60s", "1/60s"),
        ("1/60s", "1/60s"),
    ]


def test_extra_source_drift_does_not_emit_in_angle_retime(
    tmp_path: Path,
) -> None:
    source = _video_file(
        "source",
        tmp_path / "source.mp4",
        "source.mp4",
        duration_ms=3585000,
        width=1920,
        height=1080,
        fps=60.0,
        frame_count=215100,
    )
    extra = _video_file(
        "extra",
        tmp_path / "extra_0.mov",
        "extra_0.mov",
        duration_ms=3591218,
        width=3840,
        height=2160,
        fps=29.96975297356991,
        frame_count=107655,
    )
    extra.info.video_duration = "2154731/600"
    extra.info.audio_sample_count = 172378480
    extra.info.audio_sample_rate = 48000
    project = Project(
        name="fcpxml_probe",
        source_files=[source, extra],
        tracks=[
            Track(id="source_video", source_file_id="source", track_type=TrackType.VIDEO),
            Track(
                id="extra_video",
                source_file_id="extra",
                track_type=TrackType.VIDEO,
                offset_ms=21104,
            ),
        ],
    )

    root = FCPXMLExporter()._create_fcpxml_structure(project)
    _, multicam = _multicam_media(root)
    extra_clip = multicam.findall("mc-angle")[1].find("asset-clip")

    assert extra_clip is not None
    extra_format = _asset_format(root, "extra_0")

    # The camera (extra) is the lowest-fps angle, so it becomes the multicam
    # base and plays 1:1.  We deliberately do NOT emit a drift timeMap inside a
    # multicam angle: FCP mis-applies an in-angle retime and the camera drifts
    # several seconds.  Native multicam aligns by offset only, so we match that.
    assert multicam.get("format") == extra_format
    assert _format_frame_duration(root, extra_format) == "1001/30000s"
    assert _asset_media_src(root, "extra_0") == f"file://{extra.path.absolute()}"

    # 1:1 camera angle: duration == asset duration, no timeMap, no conform-rate.
    assert _asset_duration(root, "extra_0") == "107735628/30000s"
    assert extra_clip.get("duration") == _asset_duration(root, "extra_0")
    assert extra_clip.find("timeMap") is None
    assert extra_clip.find("conform-rate") is None

    conform = extra_clip.find("adjust-conform")
    assert conform is not None
    assert conform.get("type") == "fit"
    assert FCPXMLExporter()._validate_asset_reference_bounds(root) == []


def test_precise_cfr_asset_duration_keeps_counted_last_frame(tmp_path: Path) -> None:
    source = _video_file(
        "source",
        tmp_path / "source.mp4",
        "source.mp4",
        duration_ms=10000,
        width=1920,
        height=1080,
        fps=60.0,
        frame_count=600,
    )
    camera = _video_file(
        "c2793",
        tmp_path / "C2793.MP4",
        "C2793.MP4",
        duration_ms=6512005,
        width=3840,
        height=2160,
        fps=29.97002997002997,
        frame_count=195165,
    )
    camera.info.video_duration = "13024011/2000"
    camera.info.audio_sample_count = 312576264
    camera.info.audio_sample_rate = 48000
    camera.info.timecode = "10:29:41:16"
    camera.info.timecode_rate = "30000/1001"
    camera.info.timecode_start_frames = 1_133_446
    camera.info.timecode_start_seconds = "1134579446/30000"
    camera.info.timecode_source_kind = "rtmd"
    camera.info.fcpxml_timecode_start_seconds = None
    project = Project(
        name="c2793_regression",
        source_files=[source, camera],
        tracks=[
            Track(id="source_video", source_file_id="source", track_type=TrackType.VIDEO),
            Track(id="camera_video", source_file_id="c2793", track_type=TrackType.VIDEO),
        ],
    )

    root = FCPXMLExporter()._create_fcpxml_structure(project)
    _, multicam = _multicam_media(root)
    camera_format = _asset_format(root, "C2793")
    camera_clip = multicam.findall("mc-angle")[1].find("asset-clip")

    assert _format_frame_duration(root, camera_format) == "1001/30000s"
    assert _asset_duration(root, "C2793") == "195360165/30000s"
    assert _asset_start(root, "C2793") == "0s"
    assert camera_clip is not None
    assert camera_clip.get("start") == "0s"
    assert camera_clip.get("duration") == "195360165/30000s"
    assert FCPXMLExporter()._validate_asset_reference_bounds(root) == []


def test_extra_source_audio_drift_speed_does_not_emit_retime(tmp_path: Path) -> None:
    source = _video_file(
        "source",
        tmp_path / "source.mp4",
        "source.mp4",
        duration_ms=3585000,
        width=1920,
        height=1080,
        fps=60.0,
        frame_count=215100,
    )
    extra = _video_file(
        "extra",
        tmp_path / "extra_0.mov",
        "extra_0.mov",
        duration_ms=3591218,
        width=3840,
        height=2160,
        fps=29.96975297356991,
        frame_count=107655,
    )
    extra.info.video_duration = "2154731/600"
    audio_drift_speed = 1.0010821497418774
    project = Project(
        name="fcpxml_probe",
        source_files=[source, extra],
        tracks=[
            Track(id="source_video", source_file_id="source", track_type=TrackType.VIDEO),
            Track(
                id="extra_video",
                source_file_id="extra",
                track_type=TrackType.VIDEO,
                offset_ms=21104,
                sync_drift_retime_speed=audio_drift_speed,
            ),
        ],
    )

    root = FCPXMLExporter()._create_fcpxml_structure(project)
    _, multicam = _multicam_media(root)
    extra_clip = multicam.findall("mc-angle")[1].find("asset-clip")

    assert extra_clip is not None
    # Even when an audio-measured drift speed is present on the track, no timeMap
    # retime is emitted: the camera angle stays 1:1 (native multicam behaviour).
    assert extra_clip.find("timeMap") is None
    assert extra_clip.find("conform-rate") is None
    assert extra_clip.get("duration") == _asset_duration(root, "extra_0")
    assert FCPXMLExporter()._validate_asset_reference_bounds(root) == []


def test_asset_reference_validator_reports_overrun() -> None:
    root = ET.fromstring(
        """<fcpxml><resources><asset id=\"r1\" duration=\"1/1s\" /></resources>
        <library><event><project><sequence><spine>
        <asset-clip ref=\"r1\" start=\"3/4s\" duration=\"1/2s\" name=\"too_long.mov\" />
        </spine></sequence></project></event></library></fcpxml>"""
    )

    errors = FCPXMLExporter()._validate_asset_reference_bounds(root)

    assert errors
    assert "too_long.mov" in errors[0]


def test_asset_reference_validator_reports_time_map_overrun() -> None:
    root = ET.fromstring(
        """<fcpxml><resources><asset id=\"r1\" duration=\"1/1s\" /></resources>
        <library><event><project><sequence><spine>
        <asset-clip ref=\"r1\" start=\"0s\" duration=\"1/2s\" name=\"too_long_retime.mov\">
          <timeMap frameSampling=\"floor\">
            <timept time=\"0s\" value=\"0s\" interp=\"linear\" />
            <timept time=\"1/2s\" value=\"3/2s\" interp=\"linear\" />
          </timeMap>
        </asset-clip>
        </spine></sequence></project></event></library></fcpxml>"""
    )

    errors = FCPXMLExporter()._validate_asset_reference_bounds(root)

    assert errors
    assert "too_long_retime.mov" in errors[0]



def _single_source_review_project(tmp_path: Path) -> Project:
    source = _video_file(
        "source",
        tmp_path / "source.mp4",
        "source.mp4",
        duration_ms=5000,
        width=1920,
        height=1080,
        fps=60.0,
        frame_count=300,
    )
    return Project(
        name="review_boundary_probe",
        source_files=[source],
        tracks=[
            Track(id="source_video", source_file_id="source", track_type=TrackType.VIDEO),
        ],
        transcription=Transcription(
            source_track_id="source_audio",
            segments=[
                TranscriptSegment(index=1, start_ms=1000, end_ms=2000, text="keep one"),
                TranscriptSegment(index=2, start_ms=2600, end_ms=3000, text="cut two"),
                TranscriptSegment(index=3, start_ms=3600, end_ms=4200, text="keep three"),
            ],
        ),
        edit_decisions=[
            EditDecision(
                range=TimeRange(start_ms=2000, end_ms=2600),
                edit_type=EditType.CUT,
                reason=EditReason.SILENCE,
                active_video_track_id="source_video",
            ),
            EditDecision(
                range=TimeRange(start_ms=2600, end_ms=3000),
                edit_type=EditType.MUTE,
                reason=EditReason.FILLER,
                active_video_track_id="source_video",
                source_segment_index=2,
            ),
            EditDecision(
                range=TimeRange(start_ms=3000, end_ms=3600),
                edit_type=EditType.CUT,
                reason=EditReason.SILENCE,
                active_video_track_id="source_video",
            ),
        ],
    )


def test_final_export_uses_review_segment_boundaries(tmp_path: Path) -> None:
    output_path, _ = asyncio.run(
        FCPXMLExporter().export(
            _single_source_review_project(tmp_path),
            tmp_path / "review_boundary.fcpxml",
            silence_mode="cut",
            content_mode="cut",
        )
    )

    root = ET.parse(output_path).getroot()
    clips = root.findall("./library/event/project/sequence/spine/asset-clip")

    assert [(clip.get("start"), clip.get("duration")) for clip in clips] == [
        ("60/60s", "78/60s"),
        ("198/60s", "54/60s"),
    ]


def test_multicam_follow_speaker_switches_video_angle_and_keeps_primary_audio(tmp_path: Path) -> None:
    project = _project(tmp_path)
    project.transcription = Transcription(
        source_track_id="source_audio",
        segments=[
            TranscriptSegment(index=1, start_ms=0, end_ms=2000, text="one", speaker="speaker_0"),
            TranscriptSegment(index=2, start_ms=2000, end_ms=4000, text="two", speaker="speaker_1"),
            TranscriptSegment(index=3, start_ms=4000, end_ms=6000, text="three", speaker="speaker_0"),
        ],
    )
    project.multicam_settings = MulticamSettings(
        switching="follow_speaker",
        speaker_source_map={"speaker_0": "primary", "speaker_1": "extra:0"},
        audio_source_key="primary",
    )

    root = FCPXMLExporter()._create_fcpxml_structure(project)
    timeline_clips = _timeline_mc_clips(root)

    assert [clip.get("start") for clip in timeline_clips] == ["0/60s", "120/60s", "240/60s"]
    assert [clip.get("duration") for clip in timeline_clips] == ["120/60s", "120/60s", "120/60s"]
    assert [
        [(source.get("angleID"), source.get("srcEnable")) for source in clip.findall("mc-source")]
        for clip in timeline_clips
    ] == [
        [("a1", "all")],
        [("a2", "video"), ("a1", "audio")],
        [("a1", "all")],
    ]


def test_multicam_conservative_follow_speaker_ignores_short_backchannel(tmp_path: Path) -> None:
    project = _project(tmp_path)
    project.transcription = Transcription(
        source_track_id="source_audio",
        segments=[
            TranscriptSegment(index=1, start_ms=0, end_ms=3000, text="main", speaker="speaker_0"),
            TranscriptSegment(index=2, start_ms=3000, end_ms=3400, text="yes", speaker="speaker_1"),
            TranscriptSegment(index=3, start_ms=3400, end_ms=7000, text="main again", speaker="speaker_0"),
        ],
    )
    project.multicam_settings = MulticamSettings(
        switching="conservative_follow_speaker",
        speaker_source_map={"speaker_0": "primary", "speaker_1": "extra:0"},
        audio_source_key="primary",
    )

    root = FCPXMLExporter()._create_fcpxml_structure(project)
    timeline_clips = _timeline_mc_clips(root)

    assert len(timeline_clips) == 1
    assert timeline_clips[0].get("duration") == "420/60s"
    assert [(source.get("angleID"), source.get("srcEnable")) for source in timeline_clips[0].findall("mc-source")] == [("a1", "all")]


def test_multicam_conservative_follow_speaker_keeps_previous_angle_for_short_final_shot(tmp_path: Path) -> None:
    project = _project(tmp_path)
    project.transcription = Transcription(
        source_track_id="source_audio",
        segments=[
            TranscriptSegment(index=1, start_ms=0, end_ms=3000, text="main", speaker="speaker_0"),
            TranscriptSegment(index=2, start_ms=3000, end_ms=3800, text="brief", speaker="speaker_1"),
        ],
    )
    project.multicam_settings = MulticamSettings(
        switching="conservative_follow_speaker",
        speaker_source_map={"speaker_0": "primary", "speaker_1": "extra:0"},
        audio_source_key="primary",
    )

    root = FCPXMLExporter()._create_fcpxml_structure(project)
    timeline_clips = _timeline_mc_clips(root)

    assert len(timeline_clips) == 1
    assert timeline_clips[0].get("duration") == "228/60s"
    assert [(source.get("angleID"), source.get("srcEnable")) for source in timeline_clips[0].findall("mc-source")] == [("a1", "all")]
