"""Final Cut Pro XML exporter."""

import xml.etree.ElementTree as ET
from pathlib import Path

from avid.export.base import TimelineExporter
from avid.models.timeline import EditType, Timeline


class FCPXMLExporter(TimelineExporter):
    """Export timeline to Final Cut Pro XML format (.fcpxml)."""

    @property
    def format_name(self) -> str:
        return "Final Cut Pro"

    @property
    def file_extension(self) -> str:
        return ".fcpxml"

    async def export(self, timeline: Timeline, output_path: Path) -> Path:
        """Export timeline to FCPXML format.

        Args:
            timeline: Timeline to export
            output_path: Path for the output file

        Returns:
            Path to the exported file
        """
        root = self._create_fcpxml_structure(timeline)
        tree = ET.ElementTree(root)

        # Ensure output path has correct extension
        if not output_path.suffix == self.file_extension:
            output_path = output_path.with_suffix(self.file_extension)

        # Write with XML declaration
        with open(output_path, "wb") as f:
            tree.write(f, encoding="utf-8", xml_declaration=True)

        return output_path

    def _create_fcpxml_structure(self, timeline: Timeline) -> ET.Element:
        """Create the FCPXML document structure."""
        # Root element
        fcpxml = ET.Element("fcpxml", version="1.10")

        # Resources
        resources = ET.SubElement(fcpxml, "resources")

        # Format resource
        media_info = timeline.source_media.info
        format_id = "r1"
        format_attrs = {
            "id": format_id,
            "name": f"FFVideoFormat{media_info.height or 1080}p{int(media_info.fps or 30)}",
        }
        if media_info.width and media_info.height:
            format_attrs["width"] = str(media_info.width)
            format_attrs["height"] = str(media_info.height)
        if media_info.fps:
            format_attrs["frameDuration"] = self._fps_to_frame_duration(media_info.fps)
        ET.SubElement(resources, "format", **format_attrs)

        # Asset resource
        asset_id = "r2"
        asset = ET.SubElement(
            resources,
            "asset",
            id=asset_id,
            name=timeline.source_media.original_name,
            src=f"file://{timeline.source_media.path.absolute()}",
        )
        ET.SubElement(
            asset,
            "media-rep",
            kind="original-media",
            src=f"file://{timeline.source_media.path.absolute()}",
        )

        # Library and Event
        library = ET.SubElement(fcpxml, "library")
        event = ET.SubElement(library, "event", name="Auto Edit")

        # Project
        project = ET.SubElement(event, "project", name="Auto Edit Project")

        # Sequence
        sequence = ET.SubElement(
            project,
            "sequence",
            format=format_id,
            duration=self._ms_to_time(timeline.duration_ms, media_info.fps or 30),
        )

        # Spine
        spine = ET.SubElement(sequence, "spine")

        # Create clips based on edit decisions
        self._add_clips_to_spine(spine, timeline, asset_id, format_id)

        return fcpxml

    def _add_clips_to_spine(
        self,
        spine: ET.Element,
        timeline: Timeline,
        asset_id: str,
        format_id: str,
    ) -> None:
        """Add clips to the spine, excluding cut regions."""
        fps = timeline.source_media.info.fps or 30

        # Get all cut decisions and sort by start time
        cuts = sorted(
            [ed for ed in timeline.edit_decisions if ed.edit_type == EditType.CUT],
            key=lambda x: x.range.start_ms,
        )

        # If no cuts, add the full clip
        if not cuts:
            clip = ET.SubElement(
                spine,
                "asset-clip",
                ref=asset_id,
                duration=self._ms_to_time(timeline.duration_ms, fps),
                start=self._ms_to_time(0, fps),
                format=format_id,
            )
            return

        # Build segments between cuts
        current_position = 0
        for cut in cuts:
            if cut.range.start_ms > current_position:
                # Add segment before this cut
                segment_duration = cut.range.start_ms - current_position
                ET.SubElement(
                    spine,
                    "asset-clip",
                    ref=asset_id,
                    duration=self._ms_to_time(segment_duration, fps),
                    start=self._ms_to_time(current_position, fps),
                    format=format_id,
                )
            current_position = cut.range.end_ms

        # Add final segment after last cut
        if current_position < timeline.duration_ms:
            segment_duration = timeline.duration_ms - current_position
            ET.SubElement(
                spine,
                "asset-clip",
                ref=asset_id,
                duration=self._ms_to_time(segment_duration, fps),
                start=self._ms_to_time(current_position, fps),
                format=format_id,
            )

    def _ms_to_time(self, ms: int, fps: float) -> str:
        """Convert milliseconds to FCPXML time format (frames/fps)."""
        frames = int(ms * fps / 1000)
        # Use integer frame rate for duration string
        fps_int = int(fps)
        return f"{frames}/{fps_int}s"

    def _fps_to_frame_duration(self, fps: float) -> str:
        """Convert FPS to frame duration format."""
        fps_int = int(fps)
        return f"1/{fps_int}s"
