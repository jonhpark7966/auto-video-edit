from avid.cli import _apply_evaluation_index_patch, _build_review_segments_payload
from avid.models.project import Project, TranscriptSegment, Transcription
from avid.models.timeline import EditDecision, EditOriginKind, EditReason, EditType, TimeRange
from avid.models.track import Track, TrackType


def _project_with_segments() -> Project:
    return Project(
        name="Review Boundary Test",
        tracks=[
            Track(id="main_video", source_file_id="main", track_type=TrackType.VIDEO),
            Track(id="main_audio", source_file_id="main", track_type=TrackType.AUDIO),
        ],
        transcription=Transcription(
            source_track_id="main_audio",
            segments=[
                TranscriptSegment(index=1, start_ms=0, end_ms=2_000, text="one"),
                TranscriptSegment(index=2, start_ms=4_000, end_ms=6_000, text="two"),
                TranscriptSegment(index=3, start_ms=9_000, end_ms=12_000, text="three"),
            ],
        ),
        edit_decisions=[
            EditDecision(
                range=TimeRange(start_ms=4_000, end_ms=6_000),
                edit_type=EditType.CUT,
                reason=EditReason.FILLER,
                active_video_track_id="main_video",
                active_audio_track_ids=["main_audio"],
                origin_kind=EditOriginKind.CONTENT_SEGMENT,
                source_segment_index=2,
            ),
            EditDecision(
                range=TimeRange(start_ms=2_000, end_ms=4_000),
                edit_type=EditType.CUT,
                reason=EditReason.SILENCE,
                active_video_track_id="main_video",
                active_audio_track_ids=["main_audio"],
                origin_kind=EditOriginKind.SILENCE_GAP,
            ),
            EditDecision(
                range=TimeRange(start_ms=6_000, end_ms=9_000),
                edit_type=EditType.CUT,
                reason=EditReason.SILENCE,
                active_video_track_id="main_video",
                active_audio_track_ids=["main_audio"],
                origin_kind=EditOriginKind.SILENCE_GAP,
            ),
        ],
    )


def test_review_segments_split_gaps_at_midpoints(tmp_path):
    payload = _build_review_segments_payload(tmp_path / "project.avid.json", _project_with_segments())

    assert [(s["start_ms"], s["end_ms"]) for s in payload["segments"]] == [
        (0, 3_000),
        (3_000, 7_500),
        (7_500, 12_000),
    ]
    assert [(s["raw_start_ms"], s["raw_end_ms"]) for s in payload["segments"]] == [
        (0, 2_000),
        (4_000, 6_000),
        (9_000, 12_000),
    ]
    assert payload["segments"][1]["ai"]["action"] == "cut"


def test_apply_evaluation_uses_adjusted_boundaries_and_removes_overlapping_silence(tmp_path):
    project = _project_with_segments()
    payload = _build_review_segments_payload(tmp_path / "project.avid.json", project)

    applied_count, changes, join_strategy = _apply_evaluation_index_patch(project, payload["segments"])

    assert applied_count == 0
    assert changes > 0
    assert join_strategy == "source_segment_index"

    content_cuts = [
        decision
        for decision in project.edit_decisions
        if decision.source_segment_index == 2 and decision.reason != EditReason.SILENCE
    ]
    assert len(content_cuts) == 1
    assert content_cuts[0].range.start_ms == 3_000
    assert content_cuts[0].range.end_ms == 7_500
    assert content_cuts[0].reason == EditReason.FILLER

    silence_cuts = [
        decision
        for decision in project.edit_decisions
        if decision.reason == EditReason.SILENCE
    ]
    assert silence_cuts == []
