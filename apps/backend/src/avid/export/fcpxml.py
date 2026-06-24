"""Final Cut Pro XML exporter."""

import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass, replace
from fractions import Fraction
from pathlib import Path

from avid.export.base import ProjectExporter
from avid.models.project import MulticamSettings, Project, TranscriptSegment
from avid.models.timeline import EditDecision, EditReason, EditType, TimeRange
from avid.models.media import MediaFile
from avid.models.track import Track, TrackType


MAX_REVIEW_GAP_PADDING_MS = 500
MIN_MULTICAM_RETIME_DRIFT = Fraction(1, 20)
MAX_MULTICAM_RETIME_SPEED_DELTA = Fraction(1, 200)
CONSERVATIVE_BACKCHANNEL_MAX_MS = 800
CONSERVATIVE_MIN_SHOT_MS = 1500


@dataclass(frozen=True)
class _MulticamContext:
    media_id: str
    name: str
    primary_angle_id: str
    source_key_to_angle_id: dict[str, str]
    primary_offset_frames: int
    duration_frames: int
    # srcFrameRate string for the spine mc-clip <conform-rate>, set when the
    # multicam base rate differs from the sequence rate; None means no conform.
    conform_src_rate: str | None = None


@dataclass(frozen=True)
class _RetimeCorrection:
    speed: Fraction
    nominal_duration: Fraction
    actual_duration: Fraction
    drift: Fraction


@dataclass(frozen=True)
class _TimelineClipPlan:
    source_start_ms: int
    source_end_ms: int
    start_frames: int
    duration_frames: int
    timeline_offset_frames: int
    enabled: bool
    video_angle_id: str | None = None
    audio_angle_id: str | None = None
    speaker: str | None = None


class FCPXMLExporter(ProjectExporter):
    """Export project to Final Cut Pro XML format (.fcpxml)."""

    @property
    def format_name(self) -> str:
        return "Final Cut Pro"

    @property
    def file_extension(self) -> str:
        return ".fcpxml"

    async def export(
        self,
        project: Project,
        output_path: Path,
        show_disabled_cuts: bool = False,
        silence_mode: str = "cut",
        content_mode: str = "disabled",
        merge_short_gaps_ms: int = 500,
    ) -> tuple[Path, Path | None]:
        """Export project to FCPXML format with adjusted SRT.

        Args:
            project: Project to export
            output_path: Path for the output file
            show_disabled_cuts: If True, CUT segments are included but disabled
                               in the timeline (visible but won't play).
                               If False, CUT segments are completely removed.
            silence_mode: How to handle SILENCE edits - "cut" (remove) or "disabled"
            content_mode: How to handle DUPLICATE/FILLER edits - "cut" or "disabled"
            merge_short_gaps_ms: Short enabled segments (< this duration) between
                                disabled segments will also be disabled. Set to 0 to disable.

        Returns:
            Tuple of (fcpxml_path, srt_path or None if no transcription)

        Modes:
        1. CUT mode: Segments are removed from timeline
        2. DISABLED mode: Segments are present but disabled (for review in FCP)

        The silence_mode and content_mode parameters allow different treatment:
        - silence_mode="cut", content_mode="disabled" (default):
          Silence is automatically cut, but content edits are shown as disabled for review.
        """
        # Apply mode-based filtering to edit decisions
        processed_project = self._apply_edit_modes(project, silence_mode, content_mode)
        processed_project = self._align_to_review_segment_boundaries(processed_project)

        # Compute final removed ranges (including absorbed short gaps) once,
        # so both FCPXML timeline and SRT use the same cut list.
        final_removed_ranges = self._compute_removed_ranges(
            processed_project, merge_short_gaps_ms
        )

        root = self._create_fcpxml_structure(
            processed_project, show_disabled_cuts, merge_short_gaps_ms
        )
        if silence_mode == "cut" and content_mode == "cut":
            disabled_errors = self._validate_no_disabled_clips(root)
            if disabled_errors:
                sample = "; ".join(disabled_errors[:5])
                raise RuntimeError(f"FCPXML delivery export contains disabled clips: {sample}")
        tree = ET.ElementTree(root)

        # Ensure output path has correct extension
        if not output_path.suffix == self.file_extension:
            output_path = output_path.with_suffix(self.file_extension)

        # Write with XML declaration and DOCTYPE
        with open(output_path, "w", encoding="utf-8") as f:
            f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
            f.write('<!DOCTYPE fcpxml>\n\n')
            tree.write(f, encoding="unicode")

        # Generate adjusted SRT if transcription exists
        srt_path = None
        if project.transcription and project.transcription.segments:
            srt_path = output_path.with_suffix(".srt")
            self._export_adjusted_srt(
                processed_project, srt_path, show_disabled_cuts,
                removed_ranges=final_removed_ranges,
            )

        return output_path, srt_path

    # Content reasons that should be affected by content_mode
    CONTENT_REASONS = {
        # Lecture reasons
        EditReason.DUPLICATE,
        EditReason.FILLER,
        EditReason.INCOMPLETE,
        EditReason.FUMBLE,
        # Podcast cut reasons
        EditReason.BORING,
        EditReason.TANGENT,
        EditReason.REPETITIVE,
        EditReason.LONG_PAUSE,
        EditReason.CROSSTALK,
        EditReason.IRRELEVANT,
        EditReason.DRAGGING,
        EditReason.META_COMMENT,
    }

    def _apply_edit_modes(
        self,
        project: Project,
        silence_mode: str,
        content_mode: str,
    ) -> Project:
        """Apply edit mode settings to filter/modify edit decisions.

        Args:
            project: Original project
            silence_mode: "cut" or "disabled" for SILENCE edits
            content_mode: "cut" or "disabled" for content edits (filler, boring, etc.)

        Returns:
            Project with modified edit decisions
        """
        # Create a copy with modified edit decisions
        new_decisions = []

        for decision in project.edit_decisions:
            # In delivery mode (content_mode="cut"), any MUTE decision is a
            # cut candidate and must be removed regardless of reason.
            if decision.reason == EditReason.SILENCE:
                mode = silence_mode
            elif decision.edit_type == EditType.MUTE:
                mode = content_mode
            elif decision.reason in self.CONTENT_REASONS:
                mode = content_mode
            else:
                # MANUAL or keep reasons - keep as-is
                new_decisions.append(decision)
                continue

            # Determine target edit_type based on mode
            target_edit_type = EditType.CUT if mode == "cut" else EditType.MUTE

            # Only create new decision if edit_type needs to change
            if decision.edit_type != target_edit_type:
                new_decision = EditDecision(
                    range=decision.range,
                    edit_type=target_edit_type,
                    reason=decision.reason,
                    confidence=decision.confidence,
                    note=decision.note,
                    active_video_track_id=decision.active_video_track_id,
                    active_audio_track_ids=decision.active_audio_track_ids,
                    speed_factor=decision.speed_factor,
                    origin_kind=decision.origin_kind,
                    source_segment_index=decision.source_segment_index,
                    boundary=decision.boundary,
                    junction_repair=decision.junction_repair,
                )
                new_decisions.append(new_decision)
            else:
                new_decisions.append(decision)

        # Create a new project with modified decisions
        # We use model_copy to avoid modifying the original
        new_project = project.model_copy(deep=True)
        new_project.edit_decisions = new_decisions

        return new_project

    def _segment_identity(self, segment: TranscriptSegment, position: int) -> int:
        return int(segment.index) if segment.index is not None else position + 1

    def _review_segment_ranges(self, project: Project) -> list[tuple[int, int, int]]:
        """Return review-segments/v1 padded boundaries.

        The output items are ``(segment_index, start_ms, end_ms)`` in transcript
        order. This mirrors avid-cli review-segments so FCPXML export can use the
        same segment boundaries as the review UI.
        """
        if not project.transcription or not project.transcription.segments:
            return []

        valid: list[tuple[int, int, int, int]] = []
        for position, segment in enumerate(project.transcription.segments):
            start_ms = int(segment.start_ms)
            end_ms = int(segment.end_ms)
            if end_ms <= start_ms:
                continue
            valid.append((
                position,
                self._segment_identity(segment, position),
                start_ms,
                end_ms,
            ))

        if not valid:
            return []

        if project.segmentation_boundary_rule != "word_boundary":
            return [
                (segment_index, start_ms, end_ms)
                for _, segment_index, start_ms, end_ms in valid
            ]

        starts = {position: start_ms for position, _, start_ms, _ in valid}
        ends = {position: end_ms for position, _, _, end_ms in valid}

        for current, following in zip(valid, valid[1:]):
            current_position, _, _, current_end = current
            next_position, _, next_start, _ = following
            boundary = (current_end + next_start) // 2
            ends[current_position] = boundary
            starts[next_position] = boundary

        ranges: list[tuple[int, int, int]] = []
        for position, segment_index, raw_start, raw_end in valid:
            start_ms = starts[position]
            end_ms = ends[position]
            if end_ms <= start_ms:
                start_ms = raw_start
                end_ms = raw_end
            ranges.append((segment_index, start_ms, end_ms))
        return ranges

    def _subtract_ranges(
        self,
        start_ms: int,
        end_ms: int,
        protected_ranges: list[tuple[int, int]],
    ) -> list[tuple[int, int]]:
        pieces: list[tuple[int, int]] = []
        cursor = start_ms
        for protected_start, protected_end in protected_ranges:
            if protected_end <= cursor:
                continue
            if protected_start >= end_ms:
                break
            if protected_start > cursor:
                pieces.append((cursor, min(protected_start, end_ms)))
            cursor = max(cursor, protected_end)
            if cursor >= end_ms:
                break
        if cursor < end_ms:
            pieces.append((cursor, end_ms))
        return pieces

    def _invert_ranges(
        self,
        kept_ranges: list[tuple[int, int]],
        total_duration_ms: int,
    ) -> list[tuple[int, int]]:
        removed: list[tuple[int, int]] = []
        cursor = 0
        for start_ms, end_ms in self._merge_overlapping_ranges(kept_ranges):
            start_ms = max(0, min(start_ms, total_duration_ms))
            end_ms = max(0, min(end_ms, total_duration_ms))
            if end_ms <= start_ms:
                continue
            if start_ms > cursor:
                removed.append((cursor, start_ms))
            cursor = max(cursor, end_ms)
        if cursor < total_duration_ms:
            removed.append((cursor, total_duration_ms))
        return removed

    def _align_to_review_segment_boundaries(self, project: Project) -> Project:
        """Make export decisions use the same boundaries as review-segments."""
        review_ranges = self._review_segment_ranges(project)
        if not review_ranges:
            return project

        ranges_by_index = {
            segment_index: (start_ms, end_ms)
            for segment_index, start_ms, end_ms in review_ranges
        }
        protected_ranges = self._merge_overlapping_ranges(
            [(start_ms, end_ms) for _, start_ms, end_ms in review_ranges]
        )

        aligned = project.model_copy(deep=True)
        aligned_decisions: list[EditDecision] = []
        for decision in aligned.edit_decisions:
            if decision.reason == EditReason.SILENCE:
                for start_ms, end_ms in self._subtract_ranges(
                    decision.range.start_ms,
                    decision.range.end_ms,
                    protected_ranges,
                ):
                    aligned_decisions.append(decision.model_copy(update={
                        "range": TimeRange(start_ms=start_ms, end_ms=end_ms),
                    }))
                continue

            segment_index = decision.source_segment_index
            if segment_index is None:
                aligned_decisions.append(decision)
                continue

            review_range = ranges_by_index.get(int(segment_index))
            if review_range is None:
                aligned_decisions.append(decision)
                continue

            start_ms, end_ms = review_range
            aligned_decisions.append(decision.model_copy(update={
                "range": TimeRange(start_ms=start_ms, end_ms=end_ms),
            }))

        aligned_decisions.sort(key=lambda item: item.range.start_ms)
        aligned.edit_decisions = aligned_decisions
        return aligned

    def _merge_adjacent_enabled_review_segments(
        self,
        project: Project,
        segments: list[tuple[int, int, int, str]],
        max_gap_ms: int = 500,
    ) -> list[tuple[int, int, str]]:
        """Merge adjacent enabled review segments when the same speaker continues."""
        if not segments:
            return []

        speaker_by_index = {
            int(segment.index): segment.speaker
            for segment in (project.transcription.segments if project.transcription else [])
            if segment.index is not None and segment.speaker
        }

        merged: list[tuple[int, int, int, str]] = []
        for segment_index, start_ms, end_ms, state in segments:
            if not merged:
                merged.append((segment_index, start_ms, end_ms, state))
                continue

            prev_index, prev_start, prev_end, prev_state = merged[-1]
            prev_speaker = speaker_by_index.get(int(prev_index))
            speaker = speaker_by_index.get(int(segment_index))
            gap_ms = max(0, start_ms - prev_end)

            if (
                prev_state == state == "enabled"
                and prev_speaker is not None
                and prev_speaker == speaker
                and gap_ms < max_gap_ms
            ):
                merged[-1] = (prev_index, prev_start, end_ms, prev_state)
                continue

            merged.append((segment_index, start_ms, end_ms, state))

        return [(start_ms, end_ms, state) for _, start_ms, end_ms, state in merged]


    def _review_timeline_segments(
        self,
        project: Project,
        primary_track: Track,
    ) -> list[tuple[int, int, str]]:
        review_ranges = self._review_segment_ranges(project)
        if not review_ranges:
            return []

        cut_ranges = self._merge_overlapping_ranges([
            (d.range.start_ms, d.range.end_ms)
            for d in project.edit_decisions
            if d.edit_type == EditType.CUT
            and d.active_video_track_id == primary_track.id
        ])
        mute_ranges = self._merge_overlapping_ranges([
            (d.range.start_ms, d.range.end_ms)
            for d in project.edit_decisions
            if d.edit_type == EditType.MUTE
            and d.active_video_track_id == primary_track.id
        ])

        segments: list[tuple[int, int, int, str]] = []
        for segment_index, start_ms, end_ms in review_ranges:
            is_cut = any(
                cut_start < end_ms and start_ms < cut_end
                for cut_start, cut_end in cut_ranges
            )
            is_mute = any(
                mute_start < end_ms and start_ms < mute_end
                for mute_start, mute_end in mute_ranges
            )
            if is_cut:
                state = "removed"
            elif is_mute:
                state = "disabled"
            else:
                state = "enabled"
            segments.append((segment_index, start_ms, end_ms, state))
        return self._merge_adjacent_enabled_review_segments(project, segments)

    def _compute_removed_ranges(
        self,
        project: Project,
        merge_short_gaps_ms: int = 500,
    ) -> list[tuple[int, int]]:
        """Compute the final list of removed time ranges.

        This includes both explicit CUT ranges and short enabled gaps
        between CUT regions that are absorbed (< merge_short_gaps_ms).
        Both the FCPXML timeline and SRT export use this to stay in sync.
        """
        video_tracks = project.get_video_tracks()
        if not video_tracks:
            return []

        primary_track = video_tracks[0]
        source = project.get_source_file(primary_track.source_file_id)
        if not source:
            return []

        total_duration_ms = source.info.duration_ms
        review_segments = self._review_timeline_segments(project, primary_track)
        if review_segments:
            kept_ranges = [
                (start_ms, end_ms)
                for start_ms, end_ms, state in review_segments
                if state != "removed"
            ]
            return self._invert_ranges(kept_ranges, total_duration_ms)

        cut_decisions = [
            d for d in project.edit_decisions
            if d.edit_type == EditType.CUT
            and d.active_video_track_id == primary_track.id
        ]
        mute_decisions = [
            d for d in project.edit_decisions
            if d.edit_type == EditType.MUTE
            and d.active_video_track_id == primary_track.id
        ]

        merged_cuts = self._merge_overlapping_ranges(
            [(d.range.start_ms, d.range.end_ms) for d in cut_decisions]
        )
        merged_mutes = self._merge_overlapping_ranges(
            [(d.range.start_ms, d.range.end_ms) for d in mute_decisions]
        )

        # Build segments with states
        boundary_points = {0, total_duration_ms}
        for s, e in merged_cuts:
            boundary_points.add(s)
            boundary_points.add(e)
        for s, e in merged_mutes:
            boundary_points.add(s)
            boundary_points.add(e)

        sorted_boundaries = sorted(boundary_points)
        segments: list[tuple[int, int, str]] = []

        for i in range(len(sorted_boundaries) - 1):
            range_start = sorted_boundaries[i]
            range_end = sorted_boundaries[i + 1]
            if range_start >= range_end:
                continue

            is_cut = any(
                cs <= range_start and range_end <= ce
                for cs, ce in merged_cuts
            )
            is_mute = any(
                ms <= range_start and range_end <= me
                for ms, me in merged_mutes
            )

            if is_cut:
                state = 'removed'
            elif is_mute:
                state = 'disabled'
            else:
                state = 'enabled'
            segments.append((range_start, range_end, state))

        # Absorb short enabled gaps between removed segments
        if merge_short_gaps_ms > 0:
            for i in range(1, len(segments) - 1):
                s, e, state = segments[i]
                if state == 'enabled' and (e - s) < merge_short_gaps_ms:
                    if segments[i - 1][2] == 'removed' and segments[i + 1][2] == 'removed':
                        segments[i] = (s, e, 'removed')

        # Collect and merge all removed ranges
        removed = [(s, e) for s, e, st in segments if st == 'removed']
        return self._merge_overlapping_ranges(removed)

    def _export_adjusted_srt(
        self,
        project: Project,
        output_path: Path,
        show_disabled_cuts: bool = False,
        removed_ranges: list[tuple[int, int]] | None = None,
    ) -> None:
        """Export SRT with timestamps adjusted for cuts.

        Args:
            project: Project with transcription and edit decisions
            output_path: Path for the SRT file
            show_disabled_cuts: If True, keep original timestamps
            removed_ranges: Pre-computed removed ranges (including absorbed
                short gaps). If None, falls back to CUT decisions only.
        """
        if not project.transcription:
            return

        video_tracks = project.get_video_tracks()
        if not video_tracks:
            return

        primary_track = video_tracks[0]

        if removed_ranges is not None:
            cuts_to_apply = removed_ranges
        else:
            # Fallback: use CUT decisions only (no short gap absorption)
            cut_decisions = [
                d
                for d in project.edit_decisions
                if d.edit_type == EditType.CUT
                and d.active_video_track_id == primary_track.id
            ]
            cuts_to_apply = self._merge_overlapping_ranges(
                [(d.range.start_ms, d.range.end_ms) for d in cut_decisions]
            )

        def adjust_time(original_ms: int) -> int:
            """Adjust timestamp by subtracting all cuts that come before it."""
            adjusted = original_ms
            for cut_start, cut_end in cuts_to_apply:
                if cut_end <= original_ms:
                    # Cut is entirely before this timestamp
                    adjusted -= (cut_end - cut_start)
                elif cut_start < original_ms < cut_end:
                    # Timestamp is inside a cut (shouldn't happen for kept segments)
                    adjusted -= (original_ms - cut_start)
            return max(0, adjusted)

        def is_segment_kept(start_ms: int, end_ms: int) -> bool:
            """Check if a segment is kept (not entirely within a cut)."""
            for cut_start, cut_end in cuts_to_apply:
                if cut_start <= start_ms and end_ms <= cut_end:
                    return False
            return True

        def ms_to_srt_time(ms: int) -> str:
            """Convert milliseconds to SRT time format."""
            hours = ms // 3600000
            minutes = (ms % 3600000) // 60000
            seconds = (ms % 60000) // 1000
            millis = ms % 1000
            return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"

        # Generate adjusted SRT
        srt_lines = []
        segment_num = 1

        for seg in project.transcription.segments:
            # Skip segments that fall entirely within cuts
            if not is_segment_kept(seg.start_ms, seg.end_ms):
                continue

            # Adjust timestamps
            new_start = adjust_time(seg.start_ms)
            new_end = adjust_time(seg.end_ms)

            if new_end > new_start:
                srt_lines.append(f"{segment_num}")
                srt_lines.append(f"{ms_to_srt_time(new_start)} --> {ms_to_srt_time(new_end)}")
                srt_lines.append(seg.text)
                srt_lines.append("")
                segment_num += 1

        # Write SRT file
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\n".join(srt_lines))

    def _create_fcpxml_structure(
        self,
        project: Project,
        show_disabled_cuts: bool = False,
        merge_short_gaps_ms: int = 500,
    ) -> ET.Element:
        """Create the FCPXML document structure."""
        # Root element
        fcpxml = ET.Element("fcpxml", version="1.13")

        # Resources
        resources = ET.SubElement(fcpxml, "resources")

        # Get primary video track for format info
        video_tracks = project.get_video_tracks()
        primary_video_track = video_tracks[0] if video_tracks else None

        # Determine format from primary video
        fps = 30.0
        width = 1920
        height = 1080

        if primary_video_track:
            source = project.get_source_file(primary_video_track.source_file_id)
            if source and source.info:
                fps = source.info.fps or 30.0
                width = source.info.width or 1920
                height = source.info.height or 1080

        # Build per-source format resources.
        # Each unique (width, height, frameDuration) gets one <format> element.
        # source_format_map: source_file_id → (format_id, fps)
        primary_format_id = "r1"
        primary_frame_duration = (
            self._source_frame_duration_time(source, fps)
            if source and source.info else self._fps_to_frame_duration(fps)
        )
        primary_spec = (width, height, primary_frame_duration)
        spec_to_format: dict[tuple[int, int, str], tuple[str, float]] = {
            primary_spec: (primary_format_id, fps),
        }
        source_format_map: dict[str, tuple[str, float]] = {}
        next_resource_id = 2

        # Assign formats to each source file
        for source_file in project.source_files:
            src_fps = 30.0
            src_w = width  # fallback to primary dimensions
            src_h = height
            if source_file.info:
                src_fps = source_file.info.fps or fps
                src_w = source_file.info.width or width
                src_h = source_file.info.height or height

            src_frame_duration = self._source_frame_duration_time(source_file, src_fps)
            spec = (src_w, src_h, src_frame_duration)
            if spec not in spec_to_format:
                fmt_id = f"r{next_resource_id}"
                next_resource_id += 1
                spec_to_format[spec] = (fmt_id, src_fps)
            source_format_map[source_file.id] = (
                spec_to_format[spec][0],
                src_fps,
            )

        # Create <format> elements for each unique spec
        for (fmt_w, fmt_h, fmt_frame_duration), (fmt_id, fmt_fps) in spec_to_format.items():
            ET.SubElement(
                resources,
                "format",
                id=fmt_id,
                name=self._get_format_name(fmt_w, fmt_h, fmt_fps),
                frameDuration=fmt_frame_duration,
                width=str(fmt_w),
                height=str(fmt_h),
                colorSpace="1-1-1 (Rec. 709)",
            )

        extra_tracks = (
            self._get_extra_source_tracks(project, primary_video_track)
            if primary_video_track else []
        )

        # Asset resources for each source file
        asset_map: dict[str, str] = {}  # source_file_id -> asset_id
        for source_file in project.source_files:
            asset_id = f"r{next_resource_id}"
            next_resource_id += 1
            asset_map[source_file.id] = asset_id

            src_format_id, src_fps = source_format_map[source_file.id]

            # Build asset attributes matching FCP's export format
            # Note: uid is omitted. Arbitrary values can crash FCP.
            has_audio = bool(source_file.info and source_file.info.has_audio)
            asset_attrs = {
                "id": asset_id,
                "name": source_file.original_name.rsplit(".", 1)[0],  # Name without extension
                "start": self._source_start_time(source_file),
                "hasVideo": "1" if source_file.is_video else "0",
                "format": src_format_id,
                "hasAudio": "1" if has_audio else "0",
            }

            if source_file.info and source_file.info.duration_ms:
                asset_attrs["duration"] = self._source_duration_time(source_file, src_fps)

            # Add audio info if available
            if source_file.info:
                if source_file.info.sample_rate:
                    asset_attrs["audioRate"] = str(source_file.info.sample_rate)
                if source_file.info.audio_channels:
                    asset_attrs["audioChannels"] = str(source_file.info.audio_channels)
                if source_file.is_video:
                    asset_attrs["videoSources"] = "1"
                    if source_file.info.audio_sources is not None:
                        asset_attrs["audioSources"] = str(source_file.info.audio_sources)

            asset = ET.SubElement(resources, "asset", **asset_attrs)
            ET.SubElement(
                asset,
                "media-rep",
                kind="original-media",
                src=f"file://{source_file.path.absolute()}",
            )

        multicam_context = None
        if primary_video_track and extra_tracks:
            primary_source = project.get_source_file(primary_video_track.source_file_id)
            if primary_source:
                media_id = f"r{next_resource_id}"
                next_resource_id += 1
                multicam_context = self._add_multicam_media(
                    resources, primary_video_track, primary_source,
                    extra_tracks, media_id, asset_map, source_format_map,
                    primary_format_id, fps, width, height,
                )

        timeline_plan = (
            self._build_primary_timeline_plan(
                project,
                primary_video_track,
                fps,
                merge_short_gaps_ms,
            )
            if primary_video_track else []
        )
        if multicam_context:
            timeline_plan = self._apply_multicam_switching(
                project,
                timeline_plan,
                multicam_context,
                fps,
            )
        sequence_duration_frames = self._timeline_plan_duration_frames(timeline_plan)

        # Library and Event
        library = ET.SubElement(fcpxml, "library")
        event = ET.SubElement(library, "event", name=project.name)
        if multicam_context:
            event_mc_clip = ET.SubElement(
                event,
                "mc-clip",
                ref=multicam_context.media_id,
                name=multicam_context.name,
                duration=self._frames_to_time(multicam_context.duration_frames, fps),
            )
            if multicam_context.conform_src_rate:
                ET.SubElement(
                    event_mc_clip,
                    "conform-rate",
                    srcFrameRate=multicam_context.conform_src_rate,
                )
            ET.SubElement(
                event_mc_clip,
                "mc-source",
                angleID=multicam_context.primary_angle_id,
                srcEnable="all",
            )

        # Project
        fcp_project = ET.SubElement(event, "project", name=project.name)

        sequence = ET.SubElement(
            fcp_project,
            "sequence",
            format=primary_format_id,
            duration=self._frames_to_time(sequence_duration_frames, fps),
        )

        # Spine (main video track)
        spine = ET.SubElement(sequence, "spine")

        # Build timeline (video clips only, no embedded captions)
        self._build_video_timeline(
            spine, project, asset_map, primary_format_id, fps,
            show_disabled_cuts, merge_short_gaps_ms, source_format_map, width, height,
            multicam_context, timeline_plan,
        )

        timeline_errors = self._validate_sequence_spine_duration(fcpxml)
        if timeline_errors:
            sample = "; ".join(timeline_errors[:5])
            raise RuntimeError(f"FCPXML sequence duration mismatch: {sample}")

        reference_errors = self._validate_asset_reference_bounds(fcpxml)
        if reference_errors:
            sample = "; ".join(reference_errors[:5])
            raise RuntimeError(f"FCPXML references media beyond asset duration: {sample}")

        return fcpxml

    def _timeline_plan_duration_frames(
        self,
        timeline_plan: list[_TimelineClipPlan],
    ) -> int:
        if not timeline_plan:
            return 0
        return max(
            clip.timeline_offset_frames + clip.duration_frames
            for clip in timeline_plan
            if clip.duration_frames > 0
        )

    def _segments_to_timeline_plan(
        self,
        segments: list[tuple[int, int, bool]],
        source_duration_frames: int,
        fps: float,
    ) -> list[_TimelineClipPlan]:
        """Convert source-ms segments to one continuous sequence-frame plan."""
        if not segments:
            return []

        boundary_points_ms = {0}
        for start_ms, end_ms, _enabled in segments:
            boundary_points_ms.add(start_ms)
            boundary_points_ms.add(end_ms)

        ms_to_frames_map: dict[int, int] = {}
        for ms in sorted(boundary_points_ms):
            ms_to_frames_map[ms] = self._clamp_frame(
                self._ms_to_frames_nearest(ms, fps),
                source_duration_frames,
            )

        timeline_plan: list[_TimelineClipPlan] = []
        timeline_cursor_frames = 0
        for source_start_ms, source_end_ms, enabled in segments:
            start_frames = ms_to_frames_map[source_start_ms]
            end_frames = ms_to_frames_map[source_end_ms]
            duration_frames = end_frames - start_frames
            if duration_frames <= 0:
                continue

            timeline_plan.append(_TimelineClipPlan(
                source_start_ms=source_start_ms,
                source_end_ms=source_end_ms,
                start_frames=start_frames,
                duration_frames=duration_frames,
                timeline_offset_frames=timeline_cursor_frames,
                enabled=enabled,
            ))
            timeline_cursor_frames += duration_frames

        return timeline_plan

    def _build_primary_timeline_plan(
        self,
        project: Project,
        primary_track: Track,
        fps: float,
        merge_short_gaps_ms: int = 500,
    ) -> list[_TimelineClipPlan]:
        source = project.get_source_file(primary_track.source_file_id)
        if not source:
            return []

        total_duration_ms = source.info.duration_ms if source.info else 0
        source_duration_frames = self._source_duration_frames(source, fps)

        review_segments = self._review_timeline_segments(project, primary_track)
        if review_segments:
            final_segments = [
                (start_ms, end_ms, state == "enabled")
                for start_ms, end_ms, state in review_segments
                if state != "removed"
            ]
            return self._segments_to_timeline_plan(
                final_segments,
                source_duration_frames,
                fps,
            )

        if not project.edit_decisions:
            if source_duration_frames <= 0:
                return []
            return [_TimelineClipPlan(
                source_start_ms=0,
                source_end_ms=total_duration_ms,
                start_frames=0,
                duration_frames=source_duration_frames,
                timeline_offset_frames=0,
                enabled=True,
            )]

        cut_decisions = [
            d
            for d in project.edit_decisions
            if d.edit_type == EditType.CUT
            and d.active_video_track_id == primary_track.id
        ]
        mute_decisions = [
            d
            for d in project.edit_decisions
            if d.edit_type == EditType.MUTE
            and d.active_video_track_id == primary_track.id
        ]

        merged_cuts = self._merge_overlapping_ranges(
            [(d.range.start_ms, d.range.end_ms) for d in cut_decisions]
        )
        merged_mutes = self._merge_overlapping_ranges(
            [(d.range.start_ms, d.range.end_ms) for d in mute_decisions]
        )

        boundary_points = {0, total_duration_ms}
        for start, end in merged_cuts:
            boundary_points.add(start)
            boundary_points.add(end)
        for start, end in merged_mutes:
            boundary_points.add(start)
            boundary_points.add(end)

        sorted_boundaries = sorted(boundary_points)
        segments: list[tuple[int, int, str]] = []
        for i in range(len(sorted_boundaries) - 1):
            range_start = sorted_boundaries[i]
            range_end = sorted_boundaries[i + 1]
            if range_start >= range_end:
                continue

            is_cut = any(
                cut_start <= range_start and range_end <= cut_end
                for cut_start, cut_end in merged_cuts
            )
            is_mute = any(
                mute_start <= range_start and range_end <= mute_end
                for mute_start, mute_end in merged_mutes
            )

            if is_cut:
                state = "removed"
            elif is_mute:
                state = "disabled"
            else:
                state = "enabled"
            segments.append((range_start, range_end, state))

        if merge_short_gaps_ms > 0:
            for i in range(1, len(segments) - 1):
                seg_start, seg_end, state = segments[i]
                if state == "enabled" and (seg_end - seg_start) < merge_short_gaps_ms:
                    prev_state = segments[i - 1][2]
                    next_state = segments[i + 1][2]
                    if prev_state == "removed" and next_state == "removed":
                        segments[i] = (seg_start, seg_end, "removed")

        final_segments = [
            (start, end, state == "enabled")
            for start, end, state in segments
            if state != "removed"
        ]
        if merge_short_gaps_ms > 0:
            final_segments = self._merge_short_gaps(final_segments, merge_short_gaps_ms)

        return self._segments_to_timeline_plan(
            final_segments,
            source_duration_frames,
            fps,
        )


    def _resolve_multicam_settings(self, project: Project) -> MulticamSettings:
        return project.multicam_settings or MulticamSettings()

    def _speaker_ranges(self, project: Project) -> list[tuple[int, int, str]]:
        if not project.transcription or not project.transcription.segments:
            return []

        ranges: list[tuple[int, int, str]] = []
        for segment in project.transcription.segments:
            speaker = segment.speaker
            if not speaker:
                continue
            start_ms = int(segment.start_ms)
            end_ms = int(segment.end_ms)
            if end_ms <= start_ms:
                continue
            ranges.append((start_ms, end_ms, speaker))
        return sorted(ranges, key=lambda item: item[0])

    def _speaker_for_range(
        self,
        start_ms: int,
        end_ms: int,
        speaker_ranges: list[tuple[int, int, str]],
    ) -> str | None:
        best_speaker = None
        best_overlap = 0
        for speaker_start, speaker_end, speaker in speaker_ranges:
            if speaker_end <= start_ms:
                continue
            if speaker_start >= end_ms:
                break
            overlap = min(end_ms, speaker_end) - max(start_ms, speaker_start)
            if overlap > best_overlap:
                best_overlap = overlap
                best_speaker = speaker
        return best_speaker

    def _camera_boundaries_for_clip(
        self,
        clip: _TimelineClipPlan,
        speaker_ranges: list[tuple[int, int, str]],
    ) -> list[int]:
        boundaries = {clip.source_start_ms, clip.source_end_ms}
        for speaker_start, speaker_end, _speaker in speaker_ranges:
            if speaker_end <= clip.source_start_ms:
                continue
            if speaker_start >= clip.source_end_ms:
                break
            boundaries.add(max(clip.source_start_ms, speaker_start))
            boundaries.add(min(clip.source_end_ms, speaker_end))
        return sorted(boundaries)

    def _split_timeline_plan_by_speaker_angles(
        self,
        timeline_plan: list[_TimelineClipPlan],
        speaker_ranges: list[tuple[int, int, str]],
        speaker_angle_map: dict[str, str],
        default_video_angle_id: str,
        audio_angle_id: str,
        fps: float,
    ) -> list[_TimelineClipPlan]:
        pieces: list[_TimelineClipPlan] = []
        last_speaker: str | None = None
        last_video_angle_id = default_video_angle_id

        for clip in timeline_plan:
            boundaries = self._camera_boundaries_for_clip(clip, speaker_ranges)
            clip_end_frames = clip.start_frames + clip.duration_frames
            for piece_start_ms, piece_end_ms in zip(boundaries, boundaries[1:]):
                if piece_end_ms <= piece_start_ms:
                    continue

                local_start_frames = self._ms_to_frames_nearest(
                    piece_start_ms - clip.source_start_ms,
                    fps,
                )
                local_end_frames = self._ms_to_frames_nearest(
                    piece_end_ms - clip.source_start_ms,
                    fps,
                )
                start_frames = self._clamp_frame(
                    clip.start_frames + local_start_frames,
                    clip_end_frames,
                )
                end_frames = self._clamp_frame(
                    clip.start_frames + local_end_frames,
                    clip_end_frames,
                )
                duration_frames = end_frames - start_frames
                if duration_frames <= 0:
                    continue

                speaker = self._speaker_for_range(
                    piece_start_ms,
                    piece_end_ms,
                    speaker_ranges,
                )
                if speaker is None:
                    speaker = last_speaker
                    video_angle_id = last_video_angle_id
                else:
                    video_angle_id = speaker_angle_map.get(
                        speaker,
                        default_video_angle_id,
                    )
                    if speaker in speaker_angle_map:
                        last_speaker = speaker
                        last_video_angle_id = video_angle_id

                pieces.append(_TimelineClipPlan(
                    source_start_ms=piece_start_ms,
                    source_end_ms=piece_end_ms,
                    start_frames=start_frames,
                    duration_frames=duration_frames,
                    timeline_offset_frames=(
                        clip.timeline_offset_frames
                        + start_frames
                        - clip.start_frames
                    ),
                    enabled=clip.enabled,
                    video_angle_id=video_angle_id,
                    audio_angle_id=audio_angle_id,
                    speaker=speaker,
                ))

        return self._merge_camera_plan_pieces(pieces)

    def _merge_camera_plan_pieces(
        self,
        pieces: list[_TimelineClipPlan],
    ) -> list[_TimelineClipPlan]:
        merged: list[_TimelineClipPlan] = []
        for piece in pieces:
            if piece.duration_frames <= 0:
                continue
            if not merged:
                merged.append(piece)
                continue

            previous = merged[-1]
            if (
                previous.video_angle_id == piece.video_angle_id
                and previous.audio_angle_id == piece.audio_angle_id
                and previous.enabled == piece.enabled
                and previous.source_end_ms == piece.source_start_ms
                and previous.start_frames + previous.duration_frames == piece.start_frames
                and previous.timeline_offset_frames + previous.duration_frames
                == piece.timeline_offset_frames
            ):
                merged[-1] = replace(
                    previous,
                    source_end_ms=piece.source_end_ms,
                    duration_frames=previous.duration_frames + piece.duration_frames,
                    speaker=(
                        previous.speaker
                        if previous.speaker == piece.speaker
                        else None
                    ),
                )
                continue

            merged.append(piece)
        return merged

    def _apply_conservative_multicam_rules(
        self,
        pieces: list[_TimelineClipPlan],
    ) -> list[_TimelineClipPlan]:
        pieces = self._merge_camera_plan_pieces(pieces)
        adjusted = list(pieces)
        if len(adjusted) >= 3:
            for index in range(1, len(adjusted) - 1):
                previous = adjusted[index - 1]
                current = adjusted[index]
                following = adjusted[index + 1]
                duration_ms = current.source_end_ms - current.source_start_ms
                if (
                    duration_ms <= CONSERVATIVE_BACKCHANNEL_MAX_MS
                    and previous.video_angle_id == following.video_angle_id
                    and current.video_angle_id != previous.video_angle_id
                    and previous.enabled == current.enabled == following.enabled
                ):
                    adjusted[index] = replace(
                        current,
                        video_angle_id=previous.video_angle_id,
                        speaker=previous.speaker,
                    )

        adjusted = self._merge_camera_plan_pieces(adjusted)
        stabilized: list[_TimelineClipPlan] = []
        for current in adjusted:
            if (
                stabilized
                and current.video_angle_id != stabilized[-1].video_angle_id
                and current.source_end_ms - current.source_start_ms
                < CONSERVATIVE_MIN_SHOT_MS
            ):
                current = replace(
                    current,
                    video_angle_id=stabilized[-1].video_angle_id,
                    speaker=stabilized[-1].speaker,
                )
            stabilized.append(current)
        return self._merge_camera_plan_pieces(stabilized)

    def _apply_multicam_switching(
        self,
        project: Project,
        timeline_plan: list[_TimelineClipPlan],
        multicam_context: _MulticamContext,
        fps: float,
    ) -> list[_TimelineClipPlan]:
        settings = self._resolve_multicam_settings(project)
        audio_angle_id = multicam_context.source_key_to_angle_id.get(
            settings.audio_source_key,
            multicam_context.primary_angle_id,
        )
        default_plan = [
            replace(
                clip,
                video_angle_id=multicam_context.primary_angle_id,
                audio_angle_id=audio_angle_id,
            )
            for clip in timeline_plan
        ]

        if settings.switching == "none":
            return default_plan

        speaker_angle_map: dict[str, str] = {}
        for speaker, source_key in settings.speaker_source_map.items():
            if not isinstance(speaker, str) or not isinstance(source_key, str):
                continue
            angle_id = multicam_context.source_key_to_angle_id.get(source_key)
            if angle_id:
                speaker_angle_map[speaker] = angle_id

        if not speaker_angle_map:
            return default_plan

        speaker_ranges = self._speaker_ranges(project)
        if not speaker_ranges:
            return default_plan

        pieces = self._split_timeline_plan_by_speaker_angles(
            timeline_plan,
            speaker_ranges,
            speaker_angle_map,
            multicam_context.primary_angle_id,
            audio_angle_id,
            fps,
        )
        if settings.switching == "conservative_follow_speaker":
            return self._apply_conservative_multicam_rules(pieces)
        return pieces

    def _add_multicam_media(
        self,
        resources: ET.Element,
        primary_track: Track,
        primary_source: MediaFile,
        extra_tracks: list[tuple[Track, MediaFile, int]],
        media_id: str,
        asset_map: dict[str, str],
        source_format_map: dict[str, tuple[str, float]],
        primary_format_id: str,
        primary_fps: float,
        sequence_width: int,
        sequence_height: int,
    ) -> _MulticamContext:
        """Create a native FCP multicam media resource for synced sources."""
        angle_entries: list[tuple[Track, MediaFile, str]] = [
            (primary_track, primary_source, "a1")
        ]
        source_key_to_angle_id = {"primary": "a1"}
        for extra_index, (track, source, _) in enumerate(extra_tracks):
            angle_id = f"a{extra_index + 2}"
            angle_entries.append((track, source, angle_id))
            source_key_to_angle_id[f"extra:{extra_index}"] = angle_id

        # Multicam base format = the angle with the LOWEST fps.  That angle
        # (typically the camera used as the video source) then sits 1:1 inside
        # the multicam with no frame-rate conform, which is what FCP's own
        # "New Multicam Clip" does.  Conforming a fractional-rate angle INSIDE
        # the multicam (the old behaviour) makes FCP drift ~0.1% over the run.
        # The base->sequence rate change is handled once at the spine mc-clip.
        base_format_id, base_fps = primary_format_id, primary_fps
        for _track, source, _angle_id in angle_entries:
            _fmt_id, _src_fps = source_format_map[source.id]
            if _src_fps < base_fps:
                base_format_id, base_fps = _fmt_id, _src_fps

        min_offset_ms = min(track.offset_ms for track, _, _ in angle_entries)
        primary_offset_ms = primary_track.offset_ms - min_offset_ms
        # primary_offset for the SEQUENCE spine stays in sequence fps.
        primary_offset_frames = self._ms_to_frames_nearest(primary_offset_ms, primary_fps)
        media_name = f"{primary_source.original_name.rsplit(chr(46), 1)[0]}_multicam"

        media = ET.SubElement(resources, "media", id=media_id, name=media_name)
        multicam = ET.SubElement(
            media,
            "multicam",
            format=base_format_id,
            tcStart="0s",
            tcFormat="NDF",
        )

        total_duration_frames = 0
        for track, source, angle_id in angle_entries:
            asset_id = asset_map.get(source.id)
            if not asset_id:
                continue
            source_format_id, source_fps = source_format_map[source.id]
            source_frames = self._source_duration_frames(source, source_fps)
            angle_offset_ms = track.offset_ms - min_offset_ms
            # Angle layout uses the multicam BASE fps.
            angle_offset_frames = self._ms_to_frames_nearest(angle_offset_ms, base_fps)
            source_timeline_frames = self._source_frames_to_timeline_frames_floor(
                source_frames, source_fps, base_fps
            )
            # Track total multicam span in SEQUENCE fps for the context duration.
            seq_offset_frames = self._ms_to_frames_nearest(angle_offset_ms, primary_fps)
            seq_timeline_frames = self._source_frames_to_timeline_frames_floor(
                source_frames, source_fps, primary_fps
            )
            total_duration_frames = max(
                total_duration_frames,
                seq_offset_frames + seq_timeline_frames,
            )

            angle = ET.SubElement(
                multicam,
                "mc-angle",
                name=source.original_name.rsplit(".", 1)[0],
                angleID=angle_id,
            )
            angle_offset_time = self._frames_to_time(angle_offset_frames, base_fps)
            if angle_offset_frames > 0:
                ET.SubElement(
                    angle,
                    "gap",
                    name="Gap",
                    offset="0s",
                    start="0s",
                    duration=angle_offset_time,
                )
            legacy_grid_time = not bool(
                source.info and getattr(source.info, "video_frame_count", None)
            )
            clip_start_time = self._source_clip_start_time(source, source_fps, 0)
            if not self._source_timecode_origin(source) and legacy_grid_time:
                clip_start_time = self._frames_to_time(0, source_fps)
            clip_duration_time = self._frames_to_time(source_timeline_frames, base_fps)
            if legacy_grid_time and source.info and source.info.duration_ms:
                clip_duration_time = self._frames_to_time(
                    self._ms_to_frames_nearest(source.info.duration_ms, primary_fps),
                    primary_fps,
                )

            clip_attrs = {
                "ref": asset_id,
                "offset": angle_offset_time,
                "start": clip_start_time,
                "name": source.original_name,
                "format": source_format_id,
                "tcFormat": "NDF",
                "duration": clip_duration_time,
            }
            if source.info and source.info.sample_rate:
                clip_attrs["audioRole"] = "dialogue"
            clip = ET.SubElement(angle, "asset-clip", **clip_attrs)
            # Conform only angles whose native rate differs from the base; the
            # base-rate angle (the video source) stays 1:1.  No timeMap retime.
            if abs(source_fps - base_fps) > 1e-6:
                ET.SubElement(
                    clip,
                    "conform-rate",
                    scaleEnabled="0",
                    srcFrameRate=self._fps_to_conform_rate(source_fps),
                )
            self._add_spatial_conform_if_needed(
                clip, source, sequence_width, sequence_height
            )

        conform_src_rate = (
            self._fps_to_conform_rate(base_fps)
            if abs(base_fps - primary_fps) > 1e-6
            else None
        )
        return _MulticamContext(
            media_id=media_id,
            name=media_name,
            primary_angle_id="a1",
            source_key_to_angle_id=source_key_to_angle_id,
            primary_offset_frames=primary_offset_frames,
            duration_frames=total_duration_frames,
            conform_src_rate=conform_src_rate,
        )

    def _add_timeline_source_clip(
        self,
        spine: ET.Element,
        *,
        asset_id: str,
        source: MediaFile,
        format_id: str,
        fps: float,
        start_frames: int,
        duration_frames: int,
        enabled: bool,
        timeline_offset_frames: int | None,
        multicam_context: _MulticamContext | None,
        video_angle_id: str | None = None,
        audio_angle_id: str | None = None,
    ) -> ET.Element:
        if multicam_context:
            clip_attrs = {
                "ref": multicam_context.media_id,
                "duration": self._frames_to_time(duration_frames, fps),
                "start": self._frames_to_time(
                    start_frames + multicam_context.primary_offset_frames, fps
                ),
                "name": multicam_context.name,
            }
            if timeline_offset_frames is not None:
                clip_attrs["offset"] = self._frames_to_time(timeline_offset_frames, fps)
            if not enabled:
                clip_attrs["enabled"] = "0"
            clip = ET.SubElement(spine, "mc-clip", **clip_attrs)
            if multicam_context.conform_src_rate:
                ET.SubElement(
                    clip,
                    "conform-rate",
                    srcFrameRate=multicam_context.conform_src_rate,
                )
            selected_video_angle_id = (
                video_angle_id or multicam_context.primary_angle_id
            )
            selected_audio_angle_id = audio_angle_id or selected_video_angle_id
            ET.SubElement(
                clip,
                "mc-source",
                angleID=selected_video_angle_id,
                srcEnable=(
                    "all"
                    if selected_video_angle_id == selected_audio_angle_id
                    else "video"
                ),
            )
            if selected_audio_angle_id != selected_video_angle_id:
                ET.SubElement(
                    clip,
                    "mc-source",
                    angleID=selected_audio_angle_id,
                    srcEnable="audio",
                )
            return clip

        clip_attrs = {
            "ref": asset_id,
            "duration": self._frames_to_time(duration_frames, fps),
            "start": self._frames_to_time(start_frames, fps),
            "format": format_id,
            "tcFormat": "NDF",
            "name": source.original_name,
        }
        if not enabled:
            clip_attrs["enabled"] = "0"
        return ET.SubElement(spine, "asset-clip", **clip_attrs)

    def _build_video_timeline(
        self,
        spine: ET.Element,
        project: Project,
        asset_map: dict[str, str],
        format_id: str,
        fps: float,
        show_disabled_cuts: bool = False,
        merge_short_gaps_ms: int = 500,
        source_format_map: dict[str, tuple[str, float]] | None = None,
        sequence_width: int | None = None,
        sequence_height: int | None = None,
        multicam_context: _MulticamContext | None = None,
        timeline_plan: list[_TimelineClipPlan] | None = None,
    ) -> None:
        """Build the video timeline with clips (no embedded captions).

        Args:
            spine: Parent spine element
            project: Project with edit decisions
            asset_map: Source file ID to asset ID mapping
            format_id: Primary format resource ID
            fps: Primary frame rate
            show_disabled_cuts: If True, include disabled CUT clips; if False, remove them
                               MUTE clips are always shown as disabled.
            merge_short_gaps_ms: Short enabled segments (< this duration) between
                                disabled segments will also be disabled.
            source_format_map: source_file_id → (format_id, fps) per source.
            sequence_width: Timeline raster width for explicit spatial conform.
            sequence_height: Timeline raster height for explicit spatial conform.
        """
        video_tracks = project.get_video_tracks()
        if not video_tracks:
            return

        primary_track = video_tracks[0]
        source = project.get_source_file(primary_track.source_file_id)
        if not source:
            return

        asset_id = asset_map.get(source.id)
        if not asset_id:
            return

        # Resolve extra sources once for use in connected clips
        extra_tracks = self._get_extra_source_tracks(project, primary_track)
        if timeline_plan is None:
            timeline_plan = self._build_primary_timeline_plan(
                project,
                primary_track,
                fps,
                merge_short_gaps_ms,
            )

        for planned_clip in timeline_plan:
            clip_elem = self._add_timeline_source_clip(
                spine,
                asset_id=asset_id,
                source=source,
                format_id=format_id,
                fps=fps,
                start_frames=planned_clip.start_frames,
                duration_frames=planned_clip.duration_frames,
                enabled=planned_clip.enabled,
                timeline_offset_frames=(
                    planned_clip.timeline_offset_frames
                    if multicam_context else None
                ),
                multicam_context=multicam_context,
                video_angle_id=planned_clip.video_angle_id,
                audio_angle_id=planned_clip.audio_angle_id,
            )
            if not multicam_context:
                self._add_connected_clips(
                    clip_elem,
                    planned_clip.source_start_ms,
                    planned_clip.source_end_ms,
                    extra_tracks,
                    planned_clip.duration_frames,
                    asset_map,
                    source_format_map,
                    fps,
                    sequence_width,
                    sequence_height,
                    enabled=planned_clip.enabled,
                )

    def _get_extra_source_tracks(
        self,
        project: Project,
        primary_track: Track,
    ) -> list[tuple[Track, MediaFile, int]]:
        """Return non-primary source tracks with lane assignments.

        Each entry is ``(track, media_file, lane_number)`` where lane numbers
        start at -1 and decrement (-1, -2, …).  Only one track per
        *source_file_id* is returned (video preferred over audio-only).

        Args:
            project: The project containing all tracks.
            primary_track: The primary video track to exclude.

        Returns:
            List of (Track, MediaFile, lane) tuples.
        """
        primary_source_id = primary_track.source_file_id
        seen_source_ids: set[str] = {primary_source_id}
        extras: list[tuple[Track, MediaFile, int]] = []
        lane = -1

        # Prefer video tracks first, then audio-only
        for track in project.get_video_tracks() + project.get_audio_tracks():
            if track.source_file_id in seen_source_ids:
                continue
            source = project.get_source_file(track.source_file_id)
            if not source:
                continue
            seen_source_ids.add(track.source_file_id)
            extras.append((track, source, lane))
            lane -= 1

        return extras

    def _add_connected_clips(
        self,
        parent_clip: ET.Element,
        main_start_ms: int,
        main_end_ms: int,
        extra_tracks: list[tuple[Track, MediaFile, int]],
        timeline_duration_frames: int,
        asset_map: dict[str, str],
        source_format_map: dict[str, tuple[str, float]] | None,
        primary_fps: float,
        sequence_width: int | None = None,
        sequence_height: int | None = None,
        enabled: bool = True,
    ) -> None:
        """Attach connected clips for extra sources as children of *parent_clip*.

        Each connected clip lives in its own lane (negative lane numbers).
        The ``offset`` uses the **primary** (sequence) fps so it aligns to
        the parent timeline grid. ``start`` uses the extra source fps, while
        ``duration`` uses the primary timeline fps so FCP imports it on an
        edit-frame boundary.

        Args:
            parent_clip: The parent ``<asset-clip>`` element.
            main_start_ms: Start of the main clip in main-source time.
            main_end_ms: End of the main clip in main-source time.
            extra_tracks: Output of ``_get_extra_source_tracks()``.
            timeline_duration_frames: Parent clip duration in sequence frames.
            asset_map: source_file_id → FCPXML asset ID.
            source_format_map: source_file_id → (format_id, fps).
            primary_fps: Frame rate of the sequence timeline.
            sequence_width: Timeline raster width for explicit spatial conform.
            sequence_height: Timeline raster height for explicit spatial conform.
            enabled: If False, connected clips get ``enabled="0"``.
        """
        if not extra_tracks:
            return

        clip_duration_ms = main_end_ms - main_start_ms
        if clip_duration_ms <= 0:
            return

        primary_format_id = parent_clip.get("format", "r1")

        for track, source, lane in extra_tracks:
            extra_asset_id = asset_map.get(source.id)
            if not extra_asset_id:
                continue

            extra_duration_ms = source.info.duration_ms
            extra_format_id = primary_format_id
            extra_fps = primary_fps
            if source_format_map and source.id in source_format_map:
                extra_format_id, extra_fps = source_format_map[source.id]
            extra_duration_frames = self._source_duration_frames(source, extra_fps)

            # Track offsets are expressed on the unified timeline. Intersect
            # the parent main clip range with the extra source available span
            # before converting to parent-local edit frames.
            extra_timeline_start_ms = track.offset_ms
            extra_timeline_end_ms = track.offset_ms + extra_duration_ms
            overlap_start_ms = max(main_start_ms, extra_timeline_start_ms)
            overlap_end_ms = min(main_end_ms, extra_timeline_end_ms)
            if overlap_end_ms <= overlap_start_ms:
                continue

            local_offset_frames = self._clamp_frame(
                self._ms_to_frames_nearest(overlap_start_ms - main_start_ms, primary_fps),
                timeline_duration_frames,
            )
            local_end_frames = self._clamp_frame(
                self._ms_to_frames_nearest(overlap_end_ms - main_start_ms, primary_fps),
                timeline_duration_frames,
            )
            timeline_clip_duration_frames = local_end_frames - local_offset_frames
            if timeline_clip_duration_frames <= 0:
                continue

            extra_start_ms = overlap_start_ms - track.offset_ms
            extra_start_frames = self._clamp_frame(
                self._ms_to_frames_nearest(extra_start_ms, extra_fps),
                extra_duration_frames,
            )
            available_timeline_frames = self._source_frames_to_timeline_frames_floor(
                extra_duration_frames - extra_start_frames,
                extra_fps,
                primary_fps,
            )
            duration_frames = min(timeline_clip_duration_frames, available_timeline_frames)
            if duration_frames <= 0:
                continue

            attrs = {
                "ref": extra_asset_id,
                "lane": str(lane),
                "offset": self._frames_to_time(local_offset_frames, primary_fps),
                "start": self._source_clip_start_time(source, extra_fps, extra_start_frames),
                "duration": self._frames_to_time(duration_frames, primary_fps),
                "format": extra_format_id,
                "tcFormat": "NDF",
                "name": source.original_name,
            }
            if not enabled:
                attrs["enabled"] = "0"
            clip = ET.SubElement(parent_clip, "asset-clip", **attrs)
            self._add_spatial_conform_if_needed(clip, source, sequence_width, sequence_height)

    def _build_timeline(
        self,
        spine: ET.Element,
        project: Project,
        asset_map: dict[str, str],
        format_id: str,
        fps: float,
        show_disabled_cuts: bool = False,
    ) -> None:
        """Build the timeline with clips based on edit decisions (legacy, no captions)."""
        # If no edit decisions, add all source files as sequential clips
        if not project.edit_decisions:
            self._add_simple_timeline(spine, project, asset_map, format_id, fps)
            return

        # Build timeline based on edit decisions
        self._add_edited_timeline(
            spine, project, asset_map, format_id, fps, show_disabled_cuts
        )

    def _add_simple_timeline(
        self,
        spine: ET.Element,
        project: Project,
        asset_map: dict[str, str],
        format_id: str,
        fps: float,
    ) -> None:
        """Add a simple timeline with all video sources (no edits)."""
        video_tracks = project.get_video_tracks()

        if not video_tracks:
            return

        # Use first video track as primary
        primary_track = video_tracks[0]
        source = project.get_source_file(primary_track.source_file_id)

        if not source:
            return

        asset_id = asset_map.get(source.id)
        if not asset_id:
            return

        # Add primary video clip
        duration_ms = source.info.duration_ms
        ET.SubElement(
            spine,
            "asset-clip",
            ref=asset_id,
            duration=self._ms_to_time(duration_ms, fps),
            start=self._ms_to_time(0, fps),
            format=format_id,
            tcFormat="NDF",
            name=source.original_name,
        )

        # Add other video tracks as connected clips (multicam style)
        for track in video_tracks[1:]:
            other_source = project.get_source_file(track.source_file_id)
            if not other_source:
                continue

            other_asset_id = asset_map.get(other_source.id)
            if not other_asset_id:
                continue

            # Connected clip with offset
            offset_time = self._ms_to_time(track.offset_ms, fps)
            # Note: Connected clips are added differently in FCPXML
            # For now, we just add them to spine with their offset

        # Add audio-only tracks as connected audio
        for track in project.get_audio_tracks():
            # Skip audio from video files (already included)
            source = project.get_source_file(track.source_file_id)
            if source and source.is_video:
                continue

            # Audio-only file
            if source:
                audio_asset_id = asset_map.get(source.id)
                if audio_asset_id:
                    # Add as connected audio clip
                    # TODO: Implement connected audio clips
                    pass

    def _add_edited_timeline(
        self,
        spine: ET.Element,
        project: Project,
        asset_map: dict[str, str],
        format_id: str,
        fps: float,
        show_disabled_cuts: bool = False,
    ) -> None:
        """Add timeline with edit decisions applied.

        This builds the timeline by finding segments to KEEP (i.e., segments
        that are NOT cut out). CUT edit decisions define what to remove,
        so we include everything else.

        Overlapping CUT decisions are merged into unified ranges before
        building the timeline. This handles cases where multiple edit
        passes (e.g., silence detection + manual cuts) have overlapping regions.

        Args:
            show_disabled_cuts: If True, CUT segments are included but disabled.
        """
        # Get primary video track and source
        video_tracks = project.get_video_tracks()
        if not video_tracks:
            return

        primary_track = video_tracks[0]
        source = project.get_source_file(primary_track.source_file_id)
        if not source:
            return

        asset_id = asset_map.get(source.id)
        if not asset_id:
            return

        total_duration_ms = source.info.duration_ms

        # Get all CUT decisions for this track, sorted by start time
        cut_decisions = sorted(
            [
                d
                for d in project.edit_decisions
                if d.edit_type == EditType.CUT
                and d.active_video_track_id == primary_track.id
            ],
            key=lambda d: d.range.start_ms,
        )

        # Merge overlapping cut ranges
        merged_cuts = self._merge_overlapping_ranges(
            [(d.range.start_ms, d.range.end_ms) for d in cut_decisions]
        )

        # Build all segments with their enabled/disabled state
        # Each segment: (start_ms, end_ms, enabled)
        segments: list[tuple[int, int, bool]] = []
        current_pos = 0

        for cut_start, cut_end in merged_cuts:
            # Add segment before this cut (if any) - enabled
            if cut_start > current_pos:
                segments.append((current_pos, cut_start, True))

            # Add the cut segment itself - disabled (only if show_disabled_cuts)
            if show_disabled_cuts:
                segments.append((cut_start, cut_end, False))

            # Move position past the cut
            current_pos = cut_end

        # Add final segment after last cut (if any) - enabled
        if current_pos < total_duration_ms:
            segments.append((current_pos, total_duration_ms, True))

        # Add clips for each segment
        for start_ms, end_ms, enabled in segments:
            duration_ms = end_ms - start_ms
            clip_attrs = {
                "ref": asset_id,
                "duration": self._ms_to_time(duration_ms, fps),
                "start": self._ms_to_time(start_ms, fps),
                "format": format_id,
                "tcFormat": "NDF",
                "name": source.original_name,
            }
            if not enabled:
                clip_attrs["enabled"] = "0"

            ET.SubElement(spine, "asset-clip", **clip_attrs)

    def _merge_overlapping_ranges(
        self, ranges: list[tuple[int, int]]
    ) -> list[tuple[int, int]]:
        """Merge overlapping or adjacent time ranges.

        Args:
            ranges: List of (start_ms, end_ms) tuples

        Returns:
            List of merged (start_ms, end_ms) tuples, sorted by start time
        """
        if not ranges:
            return []

        # Sort by start time
        sorted_ranges = sorted(ranges, key=lambda r: r[0])

        merged: list[tuple[int, int]] = []
        current_start, current_end = sorted_ranges[0]

        for start, end in sorted_ranges[1:]:
            if start <= current_end:
                # Overlapping or adjacent - extend current range
                current_end = max(current_end, end)
            else:
                # Gap - save current and start new
                merged.append((current_start, current_end))
                current_start, current_end = start, end

        # Don't forget the last range
        merged.append((current_start, current_end))

        return merged

    def _merge_short_gaps(
        self,
        segments: list[tuple[int, int, bool]],
        threshold_ms: int,
    ) -> list[tuple[int, int, bool]]:
        """Disable short enabled segments that are surrounded by disabled segments.

        When a short enabled segment (< threshold_ms) has disabled segments on both
        sides, it should also be disabled. This prevents tiny "islands" of enabled
        content between disabled regions.

        Args:
            segments: List of (start_ms, end_ms, enabled) tuples
            threshold_ms: Segments shorter than this duration will be disabled
                         if surrounded by disabled segments

        Returns:
            Modified list with short gaps disabled
        """
        if len(segments) < 3:
            return segments

        result = list(segments)

        for i in range(1, len(result) - 1):
            start, end, enabled = result[i]
            duration = end - start

            if enabled and duration < threshold_ms:
                # Check if neighbors are both disabled
                prev_enabled = result[i - 1][2]
                next_enabled = result[i + 1][2]

                if not prev_enabled and not next_enabled:
                    # Both neighbors are disabled, so disable this segment too
                    result[i] = (start, end, False)

        return result

    def _source_duration_frames(self, source: MediaFile, fps: float) -> int:
        """Return the frame count FCP may safely reference for a source."""
        if not source.info:
            return 0

        available_duration = self._source_available_duration(source)
        duration_frames = self._duration_to_frames_floor(available_duration, fps)
        frame_count = getattr(source.info, "video_frame_count", None)
        if frame_count and frame_count > 0:
            return min(frame_count, duration_frames) if duration_frames > 0 else frame_count

        has_precise_duration = bool(
            getattr(source.info, "video_duration", None)
            or getattr(source.info, "audio_sample_count", None)
        )
        if has_precise_duration:
            return duration_frames

        duration_ms = getattr(source.info, "duration_ms", None)
        if duration_ms and duration_ms > 0:
            return max(0, self._ms_to_frames_nearest(duration_ms, fps))
        return duration_frames

    def _source_duration_time(self, source: MediaFile, fps: float) -> str:
        """Return frame-aligned source duration for FCPXML asset metadata."""
        return self._frames_to_time(self._source_duration_frames(source, fps), fps)

    def _source_start_time(self, source: MediaFile) -> str:
        """Return the source media-range start used by FCP relink."""
        value = getattr(getattr(source, "info", None), "timecode_start_seconds", None)
        if value:
            return value if str(value).endswith("s") else f"{value}s"
        return "0s"

    def _source_timecode_origin(self, source: MediaFile) -> Fraction:
        value = getattr(getattr(source, "info", None), "timecode_start_seconds", None)
        if not value:
            return Fraction(0, 1)
        return self._time_fraction(value if str(value).endswith("s") else f"{value}s")

    def _source_clip_start_time(self, source: MediaFile, fps: float, start_frames: int) -> str:
        origin = self._source_timecode_origin(source)
        if origin <= 0:
            return self._frames_to_time(start_frames, fps)
        if start_frames == 0:
            return self._source_start_time(source)
        frame_duration = self._fps_to_frame_duration_fraction(fps)
        return self._fraction_to_time(origin + start_frames * frame_duration)

    def _source_frame_duration_time(self, source: MediaFile, fps: float) -> str:
        """Return a relink-safe FCPXML frameDuration for a source format.

        FCP uses this value as part of relink compatibility. Do not use
        duration/frame-count drift compensation here; that can make FCP reject
        the original media as a different frame rate.
        """
        return self._fps_to_frame_duration(fps)

    def _source_available_duration(self, source: MediaFile) -> Fraction:
        durations: list[Fraction] = []
        duration_ms = getattr(source.info, "duration_ms", None)
        if duration_ms and duration_ms > 0:
            durations.append(Fraction(duration_ms, 1000))

        sample_rate = (
            getattr(source.info, "audio_sample_rate", None)
            or getattr(source.info, "sample_rate", None)
        )
        sample_count = getattr(source.info, "audio_sample_count", None)
        if sample_rate and sample_count and sample_rate > 0 and sample_count > 0:
            durations.append(Fraction(sample_count, sample_rate))

        return min(durations) if durations else Fraction(0, 1)

    def _source_actual_video_duration(self, source: MediaFile) -> Fraction:
        if not source.info:
            return Fraction(0, 1)

        video_duration = getattr(source.info, "video_duration", None)
        if video_duration:
            parsed_duration = self._time_fraction(video_duration)
            if parsed_duration > 0:
                return parsed_duration

        return self._source_available_duration(source)

    def _source_retime_correction(
        self,
        source: MediaFile,
        fps: float,
        track: Track | None = None,
    ) -> _RetimeCorrection | None:
        if not source.is_video or not source.info:
            return None

        actual_duration = self._source_actual_video_duration(source)
        if actual_duration <= 0:
            return None

        track_speed = getattr(track, "sync_drift_retime_speed", None) if track else None
        if track_speed and track_speed > 0:
            speed = Fraction(str(track_speed)).limit_denominator(1_000_000_000)
            if abs(speed - 1) < Fraction(1, 100000):
                return None
            if abs(speed - 1) > MAX_MULTICAM_RETIME_SPEED_DELTA:
                return None
            return _RetimeCorrection(
                speed=speed,
                nominal_duration=actual_duration * speed,
                actual_duration=actual_duration,
                drift=actual_duration * (speed - 1),
            )

        frame_count = getattr(source.info, "video_frame_count", None)
        if not frame_count or frame_count <= 0:
            return None

        frame_duration = self._fps_to_frame_duration_fraction(fps)
        nominal_duration = frame_count * frame_duration
        drift = nominal_duration - actual_duration
        if abs(drift) < MIN_MULTICAM_RETIME_DRIFT:
            return None

        speed = nominal_duration / actual_duration
        if abs(speed - 1) > MAX_MULTICAM_RETIME_SPEED_DELTA:
            return None

        return _RetimeCorrection(
            speed=speed,
            nominal_duration=nominal_duration,
            actual_duration=actual_duration,
            drift=drift,
        )

    def _clamp_retimed_timeline_frames(
        self,
        source: MediaFile,
        source_fps: float,
        timeline_fps: float,
        timeline_frames: int,
        track: Track | None = None,
    ) -> int:
        retime = self._source_retime_correction(source, source_fps, track)
        if not retime or timeline_frames <= 0:
            return timeline_frames

        asset_duration = self._time_fraction(self._source_duration_time(source, source_fps))
        if asset_duration <= 0:
            return timeline_frames

        # A speed-up timeMap consumes more source time than timeline time.
        # Keep the retimed source value inside the real asset duration so FCP
        # relink does not reject the original media as too short.
        safe_timeline_duration = asset_duration / retime.speed
        timeline_frame_duration = self._fps_to_frame_duration_fraction(timeline_fps)
        safe_timeline_frames = int(safe_timeline_duration / timeline_frame_duration)
        return max(0, min(timeline_frames, safe_timeline_frames))

    def _add_linear_retime_if_needed(
        self,
        clip: ET.Element,
        source: MediaFile,
        fps: float,
        clip_duration: Fraction,
        track: Track | None = None,
    ) -> None:
        if clip_duration <= 0:
            return

        retime = self._source_retime_correction(source, fps, track)
        if not retime:
            return

        time_map = ET.SubElement(
            clip,
            "timeMap",
            frameSampling="floor",
        )
        ET.SubElement(
            time_map,
            "timept",
            time="0s",
            value="0s",
            interp="linear",
        )
        ET.SubElement(
            time_map,
            "timept",
            time=self._fraction_to_time(clip_duration),
            value=self._fraction_to_time(clip_duration * retime.speed),
            interp="linear",
        )

    def _duration_to_frames_floor(self, duration: Fraction, fps: float) -> int:
        if duration <= 0:
            return 0
        return max(0, int(duration / self._fps_to_frame_duration_fraction(fps)))

    def _clamp_frame(self, frame: int, max_frames: int) -> int:
        return max(0, min(frame, max_frames))

    def _fps_to_frame_duration_fraction(self, fps: float) -> Fraction:
        if abs(fps - 23.976) < 0.01:
            return Fraction(1001, 24000)
        if abs(fps - 29.97) < 0.01:
            return Fraction(1001, 30000)
        if abs(fps - 59.94) < 0.01:
            return Fraction(1001, 60000)
        return Fraction(1, int(round(fps)))

    def _source_frames_to_timeline_frames_floor(
        self,
        source_frames: int,
        source_fps: float,
        timeline_fps: float,
    ) -> int:
        """Return how many timeline frames fit within a source frame span."""
        if source_frames <= 0:
            return 0
        source_duration = source_frames * self._fps_to_frame_duration_fraction(source_fps)
        timeline_frame_duration = self._fps_to_frame_duration_fraction(timeline_fps)
        return max(0, int(source_duration / timeline_frame_duration))

    def _add_spatial_conform_if_needed(
        self,
        clip: ET.Element,
        source: MediaFile,
        sequence_width: int | None,
        sequence_height: int | None,
    ) -> None:
        """Make cross-raster placement deterministic in FCP imports."""
        if not source.is_video or not sequence_width or not sequence_height:
            return
        if source.info.width == sequence_width and source.info.height == sequence_height:
            return
        ET.SubElement(clip, "adjust-conform", type="fit")

    def _validate_no_disabled_clips(self, root: ET.Element) -> list[str]:
        """Return errors for disabled clips in delivery FCPXML exports."""
        errors: list[str] = []
        for clip in root.iter():
            if clip.get("enabled") != "0":
                continue
            name = clip.get("name") or clip.tag
            start = clip.get("start") or "unknown"
            duration = clip.get("duration") or "unknown"
            errors.append(
                f"{clip.tag} {name} start={start} duration={duration} has enabled=0"
            )
        return errors

    def _validate_sequence_spine_duration(self, root: ET.Element) -> list[str]:
        """Return errors when a sequence duration disagrees with its spine."""
        errors: list[str] = []
        for sequence in root.findall("./library/event/project/sequence"):
            sequence_duration = self._time_fraction(sequence.get("duration"))
            spine = sequence.find("spine")
            if spine is None:
                continue

            cursor = Fraction(0, 1)
            max_end = Fraction(0, 1)
            for child in list(spine):
                duration = self._time_fraction(child.get("duration"))
                if duration <= 0:
                    continue

                offset_attr = child.get("offset")
                start = self._time_fraction(offset_attr) if offset_attr else cursor
                end = start + duration
                max_end = max(max_end, end)
                cursor = end

            if sequence_duration != max_end:
                errors.append(
                    "sequence duration="
                    f"{sequence_duration}s spine end={max_end}s"
                )

        return errors

    def _validate_asset_reference_bounds(self, root: ET.Element) -> list[str]:
        """Return errors for asset-clips that read past their asset duration."""
        asset_ranges: dict[str, tuple[Fraction, Fraction]] = {}
        for asset in root.findall("./resources/asset"):
            asset_id = asset.get("id")
            start = self._time_fraction(asset.get("start"))
            duration = self._time_fraction(asset.get("duration"))
            if asset_id and duration > 0:
                asset_ranges[asset_id] = (start, start + duration)

        errors: list[str] = []
        tolerance = Fraction(1, 1000)
        for clip in root.iter("asset-clip"):
            ref = clip.get("ref")
            asset_range = asset_ranges.get(ref or "")
            if asset_range is None:
                continue
            asset_start, asset_end = asset_range
            start = self._time_fraction(clip.get("start"))
            duration = self._time_fraction(clip.get("duration"))
            time_map_values = [
                self._time_fraction(timept.get("value"))
                for timept in clip.findall("./timeMap/timept")
            ]
            end = start + max(time_map_values) if time_map_values else start + duration
            if start < asset_start - tolerance or end > asset_end + tolerance:
                name = clip.get("name") or ref or "asset-clip"
                errors.append(
                    f"{name} range={start}-{end}s exceeds asset range={asset_start}-{asset_end}s"
                )
        return errors

    def _fraction_to_time(self, value: Fraction) -> str:
        if value.denominator == 1:
            return f"{value.numerator}s"
        return f"{value.numerator}/{value.denominator}s"

    def _time_fraction(self, value: str | None) -> Fraction:
        if not value:
            return Fraction(0, 1)
        raw = value[:-1] if value.endswith("s") else value
        if "/" in raw:
            numerator, denominator = raw.split("/", 1)
            return Fraction(int(numerator), int(denominator))
        return Fraction(raw)

    def _ms_to_frames(self, ms: int | float, fps: float) -> int:
        """Convert milliseconds to frame count.

        For NTSC frame rates, uses proper 1001-based calculation.
        """
        return int(self._ms_to_exact_frames(ms, fps))

    def _ms_to_frames_nearest(self, ms: int | float, fps: float) -> int:
        """Convert milliseconds to the nearest frame count."""
        frames = self._ms_to_exact_frames(ms, fps)
        if frames >= 0:
            return math.floor(frames + 0.5)
        return math.ceil(frames - 0.5)

    def _ms_to_exact_frames(self, ms: int | float, fps: float) -> float:
        """Convert milliseconds to fractional frames for an FCP frame rate."""
        if abs(fps - 23.976) < 0.01:
            return ms * 24000 / 1000 / 1001
        elif abs(fps - 29.97) < 0.01:
            return ms * 30000 / 1000 / 1001
        elif abs(fps - 59.94) < 0.01:
            return ms * 60000 / 1000 / 1001
        else:
            return ms * fps / 1000

    def _ms_to_frames_ceil(self, ms: int | float, fps: float) -> int:
        """Convert milliseconds to frame count (ceil)."""
        return math.ceil(self._ms_to_exact_frames(ms, fps))

    def _frames_to_time(self, frames: int, fps: float) -> str:
        """Convert frame count to FCPXML time format.

        For NTSC frame rates, uses 1001-based timing.
        """
        if abs(fps - 23.976) < 0.01:
            time_units = frames * 1001
            return f"{time_units}/24000s"
        elif abs(fps - 29.97) < 0.01:
            time_units = frames * 1001
            return f"{time_units}/30000s"
        elif abs(fps - 59.94) < 0.01:
            time_units = frames * 1001
            return f"{time_units}/60000s"
        else:
            fps_int = int(round(fps))
            return f"{frames}/{fps_int}s"

    def _ms_to_time(self, ms: int, fps: float) -> str:
        """Convert milliseconds to FCPXML time format.

        For NTSC frame rates (23.976, 29.97, 59.94), use 1001-based timing.
        For integer frame rates, use simple frames/fps format.
        """
        frames = self._ms_to_frames(ms, fps)
        return self._frames_to_time(frames, fps)

    def _fps_to_frame_duration(self, fps: float) -> str:
        """Convert FPS to frame duration format.

        Common frame rates and their durations:
        - 23.976 fps: 1001/24000s
        - 24 fps: 1/24s
        - 25 fps: 1/25s
        - 29.97 fps: 1001/30000s
        - 30 fps: 1/30s
        - 59.94 fps: 1001/60000s
        - 60 fps: 1/60s
        """
        # Handle common NTSC frame rates with proper rational numbers
        if abs(fps - 23.976) < 0.01:
            return "1001/24000s"
        elif abs(fps - 29.97) < 0.01:
            return "1001/30000s"
        elif abs(fps - 59.94) < 0.01:
            return "1001/60000s"
        else:
            fps_int = int(round(fps))
            return f"1/{fps_int}s"

    def _fps_to_conform_rate(self, fps: float) -> str:
        """Return the FCP ``conform-rate srcFrameRate`` string for *fps*.

        FCP uses fixed labels for source frame rates (e.g. "29.97", "60").
        """
        for ref, label in (
            (23.976, "23.98"), (24.0, "24"), (25.0, "25"), (29.97, "29.97"),
            (30.0, "30"), (50.0, "50"), (59.94, "59.94"), (60.0, "60"),
        ):
            if abs(fps - ref) < 0.05:
                return label
        return f"{fps:.2f}".rstrip("0").rstrip(".")

    def _get_format_name(self, width: int, height: int, fps: float) -> str:
        """Generate FCP format name.

        FCP format names follow pattern: FFVideoFormat{width}x{height}p{fps_code}
        For 4K UHD: FFVideoFormat3840x2160p2398
        For 1080p: FFVideoFormat1920x1080p2398

        Common fps codes:
        - 23.976 fps: 2398
        - 24 fps: 24
        - 25 fps: 25
        - 29.97 fps: 2997
        - 30 fps: 30
        - 59.94 fps: 5994
        - 60 fps: 60
        """
        # Determine fps code for format name
        if abs(fps - 23.976) < 0.01:
            fps_code = "2398"
        elif abs(fps - 29.97) < 0.01:
            fps_code = "2997"
        elif abs(fps - 59.94) < 0.01:
            fps_code = "5994"
        else:
            fps_code = str(int(round(fps)))

        return f"FFVideoFormat{width}x{height}p{fps_code}"
