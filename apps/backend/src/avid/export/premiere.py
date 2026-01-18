"""Adobe Premiere Pro XML exporter."""

import xml.etree.ElementTree as ET
from pathlib import Path
from uuid import uuid4

from avid.export.base import TimelineExporter
from avid.models.timeline import EditType, Timeline


class PremiereXMLExporter(TimelineExporter):
    """Export timeline to Adobe Premiere Pro XML format (.xml)."""

    @property
    def format_name(self) -> str:
        return "Premiere Pro"

    @property
    def file_extension(self) -> str:
        return ".xml"

    async def export(self, timeline: Timeline, output_path: Path) -> Path:
        """Export timeline to Premiere Pro XML format.

        Args:
            timeline: Timeline to export
            output_path: Path for the output file

        Returns:
            Path to the exported file
        """
        root = self._create_premiere_structure(timeline)
        tree = ET.ElementTree(root)

        # Ensure output path has correct extension
        if not output_path.suffix == self.file_extension:
            output_path = output_path.with_suffix(self.file_extension)

        # Write with XML declaration
        with open(output_path, "wb") as f:
            tree.write(f, encoding="utf-8", xml_declaration=True)

        return output_path

    def _create_premiere_structure(self, timeline: Timeline) -> ET.Element:
        """Create the Premiere Pro XML document structure."""
        media_info = timeline.source_media.info
        fps = media_info.fps or 30
        timebase = int(fps)

        # Root element
        xmeml = ET.Element("xmeml", version="5")

        # Sequence
        sequence = ET.SubElement(xmeml, "sequence")
        ET.SubElement(sequence, "uuid").text = str(uuid4())
        ET.SubElement(sequence, "name").text = "Auto Edit Sequence"

        # Duration
        total_frames = int(timeline.duration_ms * fps / 1000)
        ET.SubElement(sequence, "duration").text = str(total_frames)

        # Rate
        rate = ET.SubElement(sequence, "rate")
        ET.SubElement(rate, "timebase").text = str(timebase)
        ET.SubElement(rate, "ntsc").text = "FALSE"

        # Timecode
        timecode = ET.SubElement(sequence, "timecode")
        tc_rate = ET.SubElement(timecode, "rate")
        ET.SubElement(tc_rate, "timebase").text = str(timebase)
        ET.SubElement(tc_rate, "ntsc").text = "FALSE"
        ET.SubElement(timecode, "string").text = "00:00:00:00"
        ET.SubElement(timecode, "frame").text = "0"
        ET.SubElement(timecode, "displayformat").text = "NDF"

        # Media
        media = ET.SubElement(sequence, "media")

        # Video track
        video = ET.SubElement(media, "video")
        video_track = ET.SubElement(video, "track")

        # Add clips to video track
        self._add_clips_to_track(video_track, timeline, fps, timebase, is_video=True)

        # Audio track
        audio = ET.SubElement(media, "audio")
        audio_track = ET.SubElement(audio, "track")

        # Add clips to audio track
        self._add_clips_to_track(audio_track, timeline, fps, timebase, is_video=False)

        return xmeml

    def _add_clips_to_track(
        self,
        track: ET.Element,
        timeline: Timeline,
        fps: float,
        timebase: int,
        is_video: bool,
    ) -> None:
        """Add clips to a track, excluding cut regions."""
        media_info = timeline.source_media.info

        # Get all cut decisions and sort by start time
        cuts = sorted(
            [ed for ed in timeline.edit_decisions if ed.edit_type == EditType.CUT],
            key=lambda x: x.range.start_ms,
        )

        # Build segments between cuts
        segments: list[tuple[int, int]] = []  # (start_ms, end_ms)
        current_position = 0

        for cut in cuts:
            if cut.range.start_ms > current_position:
                segments.append((current_position, cut.range.start_ms))
            current_position = cut.range.end_ms

        # Add final segment after last cut
        if current_position < timeline.duration_ms:
            segments.append((current_position, timeline.duration_ms))

        # If no cuts, add the full clip
        if not segments:
            segments = [(0, timeline.duration_ms)]

        # Create clip items for each segment
        timeline_position = 0
        for start_ms, end_ms in segments:
            clip_item = ET.SubElement(track, "clipitem")
            ET.SubElement(clip_item, "name").text = timeline.source_media.original_name

            # Duration of this segment
            segment_frames = int((end_ms - start_ms) * fps / 1000)
            ET.SubElement(clip_item, "duration").text = str(segment_frames)

            # Rate
            rate = ET.SubElement(clip_item, "rate")
            ET.SubElement(rate, "timebase").text = str(timebase)
            ET.SubElement(rate, "ntsc").text = "FALSE"

            # Timeline position
            start_frame = int(timeline_position * fps / 1000)
            end_frame = start_frame + segment_frames
            ET.SubElement(clip_item, "start").text = str(start_frame)
            ET.SubElement(clip_item, "end").text = str(end_frame)

            # Source in/out points
            in_frame = int(start_ms * fps / 1000)
            out_frame = int(end_ms * fps / 1000)
            ET.SubElement(clip_item, "in").text = str(in_frame)
            ET.SubElement(clip_item, "out").text = str(out_frame)

            # File reference
            file_elem = ET.SubElement(clip_item, "file")
            ET.SubElement(file_elem, "name").text = timeline.source_media.original_name
            ET.SubElement(file_elem, "pathurl").text = f"file://localhost{timeline.source_media.path.absolute()}"

            # Media info
            if is_video and media_info.width and media_info.height:
                media_elem = ET.SubElement(file_elem, "media")
                video_elem = ET.SubElement(media_elem, "video")
                ET.SubElement(video_elem, "duration").text = str(int(timeline.duration_ms * fps / 1000))
                sample_char = ET.SubElement(video_elem, "samplecharacteristics")
                ET.SubElement(sample_char, "width").text = str(media_info.width)
                ET.SubElement(sample_char, "height").text = str(media_info.height)

            # Update timeline position for next segment
            timeline_position += end_ms - start_ms

    def _ms_to_frames(self, ms: int, fps: float) -> int:
        """Convert milliseconds to frames."""
        return int(ms * fps / 1000)
