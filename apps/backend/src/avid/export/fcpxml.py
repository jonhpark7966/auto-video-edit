"""Final Cut Pro XML exporter."""

import xml.etree.ElementTree as ET
from pathlib import Path

from avid.export.base import ProjectExporter
from avid.models.project import Project
from avid.models.timeline import EditType
from avid.models.track import TrackType


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
    ) -> Path:
        """Export project to FCPXML format.

        Args:
            project: Project to export
            output_path: Path for the output file
            show_disabled_cuts: If True, CUT segments are included but disabled
                               in the timeline (visible but won't play).
                               If False, CUT segments are completely removed.

        Returns:
            Path to the exported file
        """
        root = self._create_fcpxml_structure(project, show_disabled_cuts)
        tree = ET.ElementTree(root)

        # Ensure output path has correct extension
        if not output_path.suffix == self.file_extension:
            output_path = output_path.with_suffix(self.file_extension)

        # Write with XML declaration
        with open(output_path, "wb") as f:
            tree.write(f, encoding="utf-8", xml_declaration=True)

        return output_path

    def _create_fcpxml_structure(
        self, project: Project, show_disabled_cuts: bool = False
    ) -> ET.Element:
        """Create the FCPXML document structure."""
        # Root element
        fcpxml = ET.Element("fcpxml", version="1.10")

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

        # Format resource
        format_id = "r1"
        format_name = self._get_format_name(width, height, fps)
        frame_duration = self._fps_to_frame_duration(fps)
        format_attrs = {
            "id": format_id,
            "name": format_name,
            "width": str(width),
            "height": str(height),
            "frameDuration": frame_duration,
        }
        ET.SubElement(resources, "format", **format_attrs)

        # Asset resources for each source file
        asset_map: dict[str, str] = {}  # source_file_id -> asset_id
        for i, source_file in enumerate(project.source_files):
            asset_id = f"r{i + 2}"
            asset_map[source_file.id] = asset_id

            asset = ET.SubElement(
                resources,
                "asset",
                id=asset_id,
                name=source_file.original_name,
                uid=source_file.id,
            )
            ET.SubElement(
                asset,
                "media-rep",
                kind="original-media",
                src=f"file://{source_file.path.absolute()}",
            )

        # Library and Event
        library = ET.SubElement(fcpxml, "library")
        event = ET.SubElement(library, "event", name=project.name)

        # Project
        fcp_project = ET.SubElement(event, "project", name=project.name)

        # Sequence
        duration_ms = project.duration_ms
        sequence = ET.SubElement(
            fcp_project,
            "sequence",
            format=format_id,
            duration=self._ms_to_time(duration_ms, fps),
        )

        # Spine (main video track)
        spine = ET.SubElement(sequence, "spine")

        # Build timeline
        self._build_timeline(spine, project, asset_map, format_id, fps, show_disabled_cuts)

        return fcpxml

    def _build_timeline(
        self,
        spine: ET.Element,
        project: Project,
        asset_map: dict[str, str],
        format_id: str,
        fps: float,
        show_disabled_cuts: bool = False,
    ) -> None:
        """Build the timeline with clips based on edit decisions."""
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

    def _ms_to_time(self, ms: int, fps: float) -> str:
        """Convert milliseconds to FCPXML time format.

        For NTSC frame rates (23.976, 29.97, 59.94), use 1001-based timing.
        For integer frame rates, use simple frames/fps format.
        """
        # Handle common NTSC frame rates with proper rational timing
        if abs(fps - 23.976) < 0.01:
            # 23.976 fps: time in 1/24000s units
            # frames * 1001 gives time in 1/24000s
            frames = int(ms * 24000 / 1000 / 1001)
            time_units = frames * 1001
            return f"{time_units}/24000s"
        elif abs(fps - 29.97) < 0.01:
            # 29.97 fps: time in 1/30000s units
            frames = int(ms * 30000 / 1000 / 1001)
            time_units = frames * 1001
            return f"{time_units}/30000s"
        elif abs(fps - 59.94) < 0.01:
            # 59.94 fps: time in 1/60000s units
            frames = int(ms * 60000 / 1000 / 1001)
            time_units = frames * 1001
            return f"{time_units}/60000s"
        else:
            # Integer frame rates
            frames = int(ms * fps / 1000)
            fps_int = int(round(fps))
            return f"{frames}/{fps_int}s"

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

        FCP format names follow pattern: FFVideoFormat{height}p{fps_code}
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

        return f"FFVideoFormat{height}p{fps_code}"
