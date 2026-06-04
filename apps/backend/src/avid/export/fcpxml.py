"""Final Cut Pro XML exporter."""

import math
import xml.etree.ElementTree as ET
from pathlib import Path

from avid.export.base import ProjectExporter
from avid.models.project import Project, TranscriptSegment
from avid.models.timeline import EditDecision, EditReason, EditType
from avid.models.media import MediaFile
from avid.models.track import Track, TrackType


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

        # Compute final removed ranges (including absorbed short gaps) once,
        # so both FCPXML timeline and SRT use the same cut list.
        final_removed_ranges = self._compute_removed_ranges(
            processed_project, merge_short_gaps_ms
        )

        root = self._create_fcpxml_structure(
            processed_project, show_disabled_cuts, merge_short_gaps_ms
        )
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
            # Determine which mode applies to this decision
            if decision.reason == EditReason.SILENCE:
                mode = silence_mode
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
                )
                new_decisions.append(new_decision)
            else:
                new_decisions.append(decision)

        # Create a new project with modified decisions
        # We use model_copy to avoid modifying the original
        new_project = project.model_copy(deep=True)
        new_project.edit_decisions = new_decisions

        return new_project

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
        # Each unique (width, height, fps) gets one <format> element.
        # source_format_map: source_file_id → (format_id, fps)
        primary_format_id = "r1"
        primary_spec = (width, height, fps)
        spec_to_format: dict[tuple[int, int, float], str] = {
            primary_spec: primary_format_id,
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

            spec = (src_w, src_h, src_fps)
            if spec not in spec_to_format:
                fmt_id = f"r{next_resource_id}"
                next_resource_id += 1
                spec_to_format[spec] = fmt_id
            source_format_map[source_file.id] = (
                spec_to_format[spec],
                src_fps,
            )

        # Create <format> elements for each unique spec
        for (fmt_w, fmt_h, fmt_fps), fmt_id in spec_to_format.items():
            ET.SubElement(
                resources,
                "format",
                id=fmt_id,
                name=self._get_format_name(fmt_w, fmt_h, fmt_fps),
                frameDuration=self._fps_to_frame_duration(fmt_fps),
                width=str(fmt_w),
                height=str(fmt_h),
                colorSpace="1-1-1 (Rec. 709)",
            )

        # Asset resources for each source file
        asset_map: dict[str, str] = {}  # source_file_id -> asset_id
        for source_file in project.source_files:
            asset_id = f"r{next_resource_id}"
            next_resource_id += 1
            asset_map[source_file.id] = asset_id

            src_format_id, src_fps = source_format_map[source_file.id]

            # Build asset attributes matching FCP's export format
            # Note: uid is omitted - FCP uses file hash for uid, using arbitrary values causes crashes
            has_audio = bool(source_file.info and source_file.info.has_audio)
            asset_attrs = {
                "id": asset_id,
                "name": source_file.original_name.rsplit(".", 1)[0],  # Name without extension
                "start": "0s",
                "hasVideo": "1" if source_file.is_video else "0",
                "format": src_format_id,
                "hasAudio": "1" if has_audio else "0",
            }

            # Add duration. Video assets use frame-aligned stream duration so
            # FCP relink does not reject files because of audio/container padding.
            if source_file.info and source_file.info.duration_ms:
                if source_file.is_video:
                    asset_attrs["duration"] = self._source_duration_time(source_file, src_fps)
                else:
                    asset_attrs["duration"] = f"{source_file.info.duration_ms}/1000s"

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

        multicam_media_id: str | None = None
        multicam_angle_map: dict[str, str] = {}
        if primary_video_track:
            multicam_tracks = self._get_multicam_angle_tracks(project, primary_video_track)
            if len(multicam_tracks) > 1:
                multicam_media_id = f"r{next_resource_id}"
                next_resource_id += 1
                multicam_angle_map = self._add_multicam_media(
                    resources,
                    project,
                    multicam_tracks,
                    asset_map,
                    source_format_map,
                    primary_format_id,
                    fps,
                    multicam_media_id,
                )

        # Library and Event
        library = ET.SubElement(fcpxml, "library")
        event = ET.SubElement(library, "event", name=project.name)

        # Project
        fcp_project = ET.SubElement(event, "project", name=project.name)

        # Sequence duration: always exclude CUT segments (silence).
        # MUTE segments (content edits shown as disabled) are still part of the timeline.
        duration_ms = self._calculate_kept_duration(project)

        sequence = ET.SubElement(
            fcp_project,
            "sequence",
            format=primary_format_id,
            duration=self._ms_to_time_nearest(duration_ms, fps),
        )

        # Spine (main video track)
        spine = ET.SubElement(sequence, "spine")

        # Build timeline (video clips only, no embedded captions)
        self._build_video_timeline(
            spine, project, asset_map, primary_format_id, fps,
            show_disabled_cuts, merge_short_gaps_ms, source_format_map,
            multicam_media_id, multicam_angle_map,
        )

        self._validate_asset_clip_bounds(fcpxml)
        return fcpxml

    def _calculate_kept_duration(self, project: Project) -> int:
        """Calculate total duration of kept segments (excluding cuts)."""
        video_tracks = project.get_video_tracks()
        if not video_tracks:
            return 0

        primary_track = video_tracks[0]
        source = project.get_source_file(primary_track.source_file_id)
        if not source:
            return 0

        total_duration_ms = source.info.duration_ms

        # Get all CUT decisions
        cut_decisions = [
            d
            for d in project.edit_decisions
            if d.edit_type == EditType.CUT
            and d.active_video_track_id == primary_track.id
        ]

        # Merge overlapping cuts
        merged_cuts = self._merge_overlapping_ranges(
            [(d.range.start_ms, d.range.end_ms) for d in cut_decisions]
        )

        # Subtract cut durations
        cut_duration = sum(end - start for start, end in merged_cuts)
        return total_duration_ms - cut_duration

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
        multicam_media_id: str | None = None,
        multicam_angle_map: dict[str, str] | None = None,
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
            multicam_media_id: Optional FCPXML media resource ID for multicam exports.
            multicam_angle_map: track ID → FCPXML angleID for multicam exports.
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

        total_duration_ms = source.info.duration_ms
        source_duration_frames = self._source_duration_frames(source, fps)

        # Resolve extra sources once for use in connected clips
        extra_tracks = self._get_extra_source_tracks(project, primary_track)
        use_multicam = bool(multicam_media_id and multicam_angle_map)

        # If no edit decisions, simple timeline with single clip
        if not project.edit_decisions:
            duration_frames = source_duration_frames
            if use_multicam:
                clip_elem = ET.SubElement(
                    spine,
                    "mc-clip",
                    ref=multicam_media_id,
                    offset=self._frames_to_time(0, fps),
                    duration=self._frames_to_time(duration_frames, fps),
                    start=self._frames_to_time(0, fps),
                    name=self._multicam_clip_name(project, source),
                )
                self._add_mc_source(clip_elem, primary_track, multicam_angle_map or {})
                return

            clip_elem = ET.SubElement(
                spine,
                "asset-clip",
                ref=asset_id,
                duration=self._frames_to_time(duration_frames, fps),
                start=self._ms_to_time(0, fps),
                format=format_id,
                tcFormat="NDF",
                name=source.original_name,
            )
            self._add_connected_clips(
                clip_elem, 0, total_duration_ms, extra_tracks,
                duration_frames, asset_map, source_format_map, fps,
            )
            return

        # Get CUT decisions (will be removed or shown as disabled)
        cut_decisions = [
            d
            for d in project.edit_decisions
            if d.edit_type == EditType.CUT
            and d.active_video_track_id == primary_track.id
        ]

        # Get MUTE decisions (always shown as disabled)
        mute_decisions = [
            d
            for d in project.edit_decisions
            if d.edit_type == EditType.MUTE
            and d.active_video_track_id == primary_track.id
        ]

        # Merge overlapping ranges for each type
        merged_cuts = self._merge_overlapping_ranges(
            [(d.range.start_ms, d.range.end_ms) for d in cut_decisions]
        )
        merged_mutes = self._merge_overlapping_ranges(
            [(d.range.start_ms, d.range.end_ms) for d in mute_decisions]
        )

        # Build segment states: collect all boundary points and determine state for each range
        # State: 'enabled', 'disabled', 'removed'
        boundary_points = {0, total_duration_ms}
        for start, end in merged_cuts:
            boundary_points.add(start)
            boundary_points.add(end)
        for start, end in merged_mutes:
            boundary_points.add(start)
            boundary_points.add(end)

        sorted_boundaries = sorted(boundary_points)

        # For each range between boundaries, determine the state
        # Priority: REMOVED > DISABLED > ENABLED
        segments: list[tuple[int, int, str]] = []  # (start_ms, end_ms, state)

        for i in range(len(sorted_boundaries) - 1):
            range_start = sorted_boundaries[i]
            range_end = sorted_boundaries[i + 1]

            if range_start >= range_end:
                continue

            # Check if this range is in a CUT region
            is_cut = any(
                cut_start <= range_start and range_end <= cut_end
                for cut_start, cut_end in merged_cuts
            )

            # Check if this range is in a MUTE region
            is_mute = any(
                mute_start <= range_start and range_end <= mute_end
                for mute_start, mute_end in merged_mutes
            )

            # Determine state
            # CUT segments are always removed from the timeline.
            # MUTE segments are always shown as disabled (for review).
            # show_disabled_cuts is kept for backward compat but no longer
            # changes behavior — silence→CUT (removed), content→MUTE (disabled).
            if is_cut:
                state = 'removed'
            elif is_mute:
                state = 'disabled'
            else:
                state = 'enabled'

            segments.append((range_start, range_end, state))

        # Absorb short enabled segments between removed segments
        # (e.g. tiny silence gaps between CUT regions)
        if merge_short_gaps_ms > 0:
            for i in range(1, len(segments) - 1):
                seg_start, seg_end, state = segments[i]
                if state == 'enabled' and (seg_end - seg_start) < merge_short_gaps_ms:
                    prev_state = segments[i - 1][2]
                    next_state = segments[i + 1][2]
                    if prev_state == 'removed' and next_state == 'removed':
                        segments[i] = (seg_start, seg_end, 'removed')

        # Filter out removed segments and convert to (start, end, enabled_bool)
        final_segments: list[tuple[int, int, bool]] = [
            (start, end, state == 'enabled')
            for start, end, state in segments
            if state != 'removed'
        ]

        # Merge short enabled gaps between disabled segments
        if merge_short_gaps_ms > 0:
            final_segments = self._merge_short_gaps(final_segments, merge_short_gaps_ms)

        # Convert all boundary points to frames ONCE to ensure continuity
        # This prevents gaps caused by independent rounding
        boundary_points_ms = [0]
        for start_ms, end_ms, _ in final_segments:
            if start_ms not in boundary_points_ms:
                boundary_points_ms.append(start_ms)
            if end_ms not in boundary_points_ms:
                boundary_points_ms.append(end_ms)
        boundary_points_ms.sort()

        # Convert to frame units (for 23.976fps: units of 1001/24000s)
        ms_to_frames_map: dict[int, int] = {}
        for ms in boundary_points_ms:
            frames = self._clamp_frame(
                self._ms_to_frames_nearest(ms, fps),
                source_duration_frames,
            )
            ms_to_frames_map[ms] = frames

        # Create clips for each segment using pre-calculated frame positions
        timeline_offset_frames = 0
        for source_start_ms, source_end_ms, enabled in final_segments:
            start_frames = ms_to_frames_map[source_start_ms]
            end_frames = ms_to_frames_map[source_end_ms]
            duration_frames = end_frames - start_frames

            if duration_frames <= 0:
                continue

            if use_multicam:
                clip_attrs = {
                    "ref": multicam_media_id,
                    "offset": self._frames_to_time(timeline_offset_frames, fps),
                    "duration": self._frames_to_time(duration_frames, fps),
                    "start": self._frames_to_time(start_frames, fps),
                    "name": self._multicam_clip_name(project, source),
                }
                if not enabled:
                    clip_attrs["enabled"] = "0"

                clip_elem = ET.SubElement(spine, "mc-clip", **clip_attrs)
                self._add_mc_source(clip_elem, primary_track, multicam_angle_map or {})
                timeline_offset_frames += duration_frames
                continue

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

            clip_elem = ET.SubElement(spine, "asset-clip", **clip_attrs)
            self._add_connected_clips(
                clip_elem, source_start_ms, source_end_ms, extra_tracks,
                duration_frames, asset_map, source_format_map, fps, enabled=enabled,
            )
            timeline_offset_frames += duration_frames

    def _get_multicam_angle_tracks(
        self,
        project: Project,
        primary_track: Track,
    ) -> list[tuple[Track, MediaFile, str]]:
        """Return video tracks that should become FCP multicam angles."""
        seen_source_ids: set[str] = set()
        angle_tracks: list[tuple[Track, MediaFile, str]] = []

        ordered_tracks = [
            primary_track,
            *[track for track in project.get_video_tracks() if track.id != primary_track.id],
        ]

        for track in ordered_tracks:
            if track.source_file_id in seen_source_ids:
                continue
            source = project.get_source_file(track.source_file_id)
            if not source or not source.is_video:
                continue

            seen_source_ids.add(track.source_file_id)
            angle_id = f"angle{len(angle_tracks) + 1}"
            angle_tracks.append((track, source, angle_id))

        return angle_tracks

    def _add_multicam_media(
        self,
        resources: ET.Element,
        project: Project,
        angle_tracks: list[tuple[Track, MediaFile, str]],
        asset_map: dict[str, str],
        source_format_map: dict[str, tuple[str, float]],
        primary_format_id: str,
        primary_fps: float,
        media_id: str,
    ) -> dict[str, str]:
        """Create a real FCPXML multicam media resource and return track angle IDs."""
        media = ET.SubElement(
            resources,
            "media",
            id=media_id,
            name=f"{project.name} Multicam",
        )
        multicam = ET.SubElement(
            media,
            "multicam",
            format=primary_format_id,
            tcStart="0s",
            tcFormat="NDF",
        )

        angle_map: dict[str, str] = {}
        for track, source, angle_id in angle_tracks:
            asset_id = asset_map.get(source.id)
            if not asset_id:
                continue

            angle_map[track.id] = angle_id
            angle = ET.SubElement(
                multicam,
                "mc-angle",
                name=source.original_name.rsplit(".", 1)[0],
                angleID=angle_id,
            )
            self._add_multicam_angle_asset_clip(
                angle,
                track,
                source,
                asset_id,
                source_format_map,
                primary_fps,
            )

        return angle_map

    def _add_multicam_angle_asset_clip(
        self,
        angle: ET.Element,
        track: Track,
        source: MediaFile,
        asset_id: str,
        source_format_map: dict[str, tuple[str, float]],
        primary_fps: float,
    ) -> None:
        """Place one source asset on a multicam angle timeline."""
        source_format_id, source_fps = source_format_map.get(
            source.id,
            ("r1", primary_fps),
        )
        source_duration_ms = source.info.duration_ms
        source_duration_frames = self._source_duration_frames(source, source_fps)

        if track.offset_ms > 0:
            offset_frames = self._ms_to_frames_nearest(track.offset_ms, primary_fps)
            if offset_frames > 0:
                ET.SubElement(
                    angle,
                    "gap",
                    name="Gap",
                    offset=self._frames_to_time(0, primary_fps),
                    start=self._frames_to_time(0, primary_fps),
                    duration=self._frames_to_time(offset_frames, primary_fps),
                )
            clip_offset = self._frames_to_time(offset_frames, primary_fps)
            quantized_offset_ms = self._frames_to_ms(offset_frames, primary_fps)
            source_start_ms = max(0, quantized_offset_ms - track.offset_ms)
        else:
            clip_offset = self._frames_to_time(0, primary_fps)
            source_start_ms = -track.offset_ms

        if source_start_ms >= source_duration_ms:
            return

        source_start_frames = self._clamp_frame(
            self._ms_to_frames_nearest(source_start_ms, source_fps),
            source_duration_frames,
        )
        available_source_ms = self._frames_to_ms(
            source_duration_frames - source_start_frames,
            source_fps,
        )
        timeline_duration_frames = min(
            self._ms_to_frames(source_duration_ms - source_start_ms, primary_fps),
            self._ms_to_frames(available_source_ms, primary_fps),
        )
        if timeline_duration_frames <= 0:
            return

        ET.SubElement(
            angle,
            "asset-clip",
            ref=asset_id,
            offset=clip_offset,
            name=source.original_name,
            start=self._frames_to_time(source_start_frames, source_fps),
            duration=self._frames_to_time(timeline_duration_frames, primary_fps),
            format=source_format_id,
            tcFormat="NDF",
        )

    def _multicam_clip_name(self, project: Project, source: MediaFile) -> str:
        """Return a stable timeline name for generated multicam clips."""
        if project.name:
            return f"{project.name} Multicam"
        return f"{source.original_name.rsplit('.', 1)[0]} Multicam"

    def _add_mc_source(
        self,
        mc_clip: ET.Element,
        primary_track: Track,
        angle_map: dict[str, str],
    ) -> None:
        """Select the primary angle for a generated multicam timeline clip."""
        angle_id = angle_map.get(primary_track.id)
        if not angle_id:
            return
        ET.SubElement(mc_clip, "mc-source", angleID=angle_id, srcEnable="all")

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
        enabled: bool = True,
    ) -> None:
        """Attach connected clips for extra sources as children of *parent_clip*.

        Each connected clip lives in its own lane (negative lane numbers).
        The ``offset`` uses the **primary** (sequence) fps so it aligns to
        the timeline grid. ``duration`` also uses the primary fps, because it
        describes the connected clip's timeline span. ``start`` uses the extra
        source's own fps so FCP can seek accurately in the source media.

        Args:
            parent_clip: The parent ``<asset-clip>`` element.
            main_start_ms: Start of the main clip in main-source time.
            main_end_ms: End of the main clip in main-source time.
            extra_tracks: Output of ``_get_extra_source_tracks()``.
            timeline_duration_frames: Parent clip duration in sequence frames.
            asset_map: source_file_id → FCPXML asset ID.
            source_format_map: source_file_id → (format_id, fps).
            primary_fps: Frame rate of the sequence timeline.
            enabled: If False, connected clips get ``enabled="0"``.
        """
        if not extra_tracks:
            return

        clip_duration_ms = main_end_ms - main_start_ms
        if clip_duration_ms <= 0:
            return

        # All connected clips use the primary (sequence) format so timing
        # is consistent and FCP scales resolution automatically.
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

            # track.offset_ms = when the extra track starts on the unified timeline.
            # So extra_source_time = unified_time - track.offset_ms.
            # Since main has offset 0, unified_time == main_time.
            extra_start_ms = main_start_ms - track.offset_ms
            extra_end_ms = main_end_ms - track.offset_ms

            # Clamp to the extra source's bounds
            extra_start_ms = max(0, min(extra_start_ms, extra_duration_ms))
            extra_end_ms = max(0, min(extra_end_ms, extra_duration_ms))

            if extra_end_ms <= extra_start_ms:
                continue

            extra_start_frames = self._clamp_frame(
                self._ms_to_frames_nearest(extra_start_ms, extra_fps),
                extra_duration_frames,
            )
            available_extra_ms = self._frames_to_ms(
                extra_duration_frames - extra_start_frames,
                extra_fps,
            )
            connected_duration_frames = min(
                timeline_duration_frames,
                self._ms_to_frames(available_extra_ms, primary_fps),
            )
            if connected_duration_frames <= 0:
                continue

            attrs = {
                "ref": extra_asset_id,
                "lane": str(lane),
                # This clip is nested under the parent main clip, so its
                # placement offset is parent-local. The source media position
                # is already represented by ``start`` below.
                "offset": self._ms_to_time(0, primary_fps),
                "start": self._frames_to_time(extra_start_frames, extra_fps),
                "duration": self._frames_to_time(connected_duration_frames, primary_fps),
                "format": extra_format_id,
                "tcFormat": "NDF",
                "name": source.original_name,
            }
            if not enabled:
                attrs["enabled"] = "0"
            ET.SubElement(parent_clip, "asset-clip", **attrs)

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
        if not source.info or not source.info.duration_ms:
            return 0
        return max(0, self._ms_to_frames_nearest(source.info.duration_ms, fps))

    def _source_duration_time(self, source: MediaFile, fps: float) -> str:
        """Return frame-aligned source duration for FCPXML asset metadata."""
        return self._frames_to_time(self._source_duration_frames(source, fps), fps)

    def _clamp_frame(self, frame: int, max_frames: int) -> int:
        return max(0, min(frame, max_frames))

    def _time_to_seconds(self, value: str | None) -> float:
        if not value:
            return 0.0
        raw = value[:-1] if value.endswith("s") else value
        if "/" in raw:
            num, den = raw.split("/", 1)
            den_float = float(den)
            if den_float == 0:
                return 0.0
            return float(num) / den_float
        return float(raw)

    def _validate_asset_clip_bounds(self, root: ET.Element) -> None:
        """Ensure exported asset clips do not reference beyond source duration."""
        asset_durations: dict[str, float] = {}
        for asset in root.findall("./resources/asset"):
            asset_id = asset.get("id")
            duration = asset.get("duration")
            if asset_id and duration:
                asset_durations[asset_id] = self._time_to_seconds(duration)

        for clip in root.findall(".//asset-clip"):
            ref = clip.get("ref")
            if ref not in asset_durations:
                continue

            start = self._time_to_seconds(clip.get("start"))
            duration = self._time_to_seconds(clip.get("duration"))
            asset_duration = asset_durations[ref]
            if start + duration > asset_duration + 1e-6:
                name = clip.get("name") or ref
                raise ValueError(
                    "FCPXML asset clip exceeds source duration: "
                    f"{name} start={start:.6f}s duration={duration:.6f}s "
                    f"asset_duration={asset_duration:.6f}s"
                )

    def _ms_to_frames(self, ms: int | float, fps: float) -> int:
        """Convert milliseconds to frame count (floor).

        For NTSC frame rates, uses proper 1001-based calculation.
        """
        return int(self._ms_to_exact_frames(ms, fps))

    def _ms_to_frames_nearest(self, ms: int | float, fps: float) -> int:
        """Convert milliseconds to the nearest frame count.

        This is used for FCPXML edit boundaries. It keeps exported ranges as
        close as possible to the source segment while making them divisible by
        the project frame duration.
        """
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
        """Convert milliseconds to frame count (ceil).

        Like ``_ms_to_frames`` but rounds up so the resulting frame span
        always covers the full millisecond duration.
        """
        return math.ceil(self._ms_to_exact_frames(ms, fps))

    def _frames_to_ms(self, frames: int, fps: float) -> float:
        """Convert frame count back to milliseconds for a given FCP frame rate."""
        if abs(fps - 23.976) < 0.01:
            return frames * 1001 * 1000 / 24000
        elif abs(fps - 29.97) < 0.01:
            return frames * 1001 * 1000 / 30000
        elif abs(fps - 59.94) < 0.01:
            return frames * 1001 * 1000 / 60000
        else:
            return frames * 1000 / fps

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

    def _ms_to_time_nearest(self, ms: int | float, fps: float) -> str:
        """Convert milliseconds to FCPXML time at the nearest frame boundary."""
        frames = self._ms_to_frames_nearest(ms, fps)
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
