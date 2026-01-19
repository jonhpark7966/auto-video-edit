"""Adobe Premiere Pro XML exporter."""

import xml.etree.ElementTree as ET
from pathlib import Path
from uuid import uuid4

from avid.export.base import ProjectExporter
from avid.models.project import Project
from avid.models.timeline import EditType


class PremiereXMLExporter(ProjectExporter):
    """Export project to Adobe Premiere Pro XML format (.xml)."""

    @property
    def format_name(self) -> str:
        return "Premiere Pro"

    @property
    def file_extension(self) -> str:
        return ".xml"

    async def export(self, project: Project, output_path: Path) -> Path:
        """Export project to Premiere Pro XML format.

        Args:
            project: Project to export
            output_path: Path for the output file

        Returns:
            Path to the exported file
        """
        root = self._create_premiere_structure(project)
        tree = ET.ElementTree(root)

        # Ensure output path has correct extension
        if not output_path.suffix == self.file_extension:
            output_path = output_path.with_suffix(self.file_extension)

        # Write with XML declaration
        with open(output_path, "wb") as f:
            tree.write(f, encoding="utf-8", xml_declaration=True)

        return output_path

    def _create_premiere_structure(self, project: Project) -> ET.Element:
        """Create the Premiere Pro XML document structure."""
        # Get format info from primary video track
        video_tracks = project.get_video_tracks()
        fps = 30.0
        width = 1920
        height = 1080

        if video_tracks:
            source = project.get_source_file(video_tracks[0].source_file_id)
            if source and source.info:
                fps = source.info.fps or 30.0
                width = source.info.width or 1920
                height = source.info.height or 1080

        timebase = int(fps)
        duration_ms = project.duration_ms

        # Root element
        xmeml = ET.Element("xmeml", version="5")

        # Sequence
        sequence = ET.SubElement(xmeml, "sequence")
        ET.SubElement(sequence, "uuid").text = str(uuid4())
        ET.SubElement(sequence, "name").text = project.name

        # Duration
        total_frames = int(duration_ms * fps / 1000)
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
        video_track_elem = ET.SubElement(video, "track")

        # Add video clips
        self._add_video_clips(video_track_elem, project, fps, timebase, width, height)

        # Audio track
        audio = ET.SubElement(media, "audio")
        audio_track_elem = ET.SubElement(audio, "track")

        # Add audio clips
        self._add_audio_clips(audio_track_elem, project, fps, timebase)

        return xmeml

    def _add_video_clips(
        self,
        track: ET.Element,
        project: Project,
        fps: float,
        timebase: int,
        width: int,
        height: int,
    ) -> None:
        """Add video clips to the track."""
        video_tracks = project.get_video_tracks()
        if not video_tracks:
            return

        # If no edit decisions, add simple clips
        if not project.edit_decisions:
            for vtrack in video_tracks:
                source = project.get_source_file(vtrack.source_file_id)
                if not source:
                    continue

                self._add_clip_item(
                    track,
                    source.original_name,
                    source.path,
                    0,
                    source.info.duration_ms,
                    vtrack.offset_ms,
                    fps,
                    timebase,
                    width,
                    height,
                    is_video=True,
                )
            return

        # Add clips based on edit decisions
        for decision in sorted(project.edit_decisions, key=lambda d: d.range.start_ms):
            if decision.edit_type == EditType.CUT:
                continue

            if decision.active_video_track_id:
                vtrack = project.get_track(decision.active_video_track_id)
                if vtrack:
                    source = project.get_source_file(vtrack.source_file_id)
                    if source:
                        source_start = decision.range.start_ms - vtrack.offset_ms
                        source_start = max(0, source_start)

                        self._add_clip_item(
                            track,
                            source.original_name,
                            source.path,
                            source_start,
                            source_start + decision.range.duration_ms,
                            decision.range.start_ms,
                            fps,
                            timebase,
                            width,
                            height,
                            is_video=True,
                        )

    def _add_audio_clips(
        self,
        track: ET.Element,
        project: Project,
        fps: float,
        timebase: int,
    ) -> None:
        """Add audio clips to the track."""
        audio_tracks = project.get_audio_tracks()
        if not audio_tracks:
            return

        # If no edit decisions, add simple clips
        if not project.edit_decisions:
            for atrack in audio_tracks:
                source = project.get_source_file(atrack.source_file_id)
                if not source:
                    continue

                self._add_clip_item(
                    track,
                    source.original_name,
                    source.path,
                    0,
                    source.info.duration_ms,
                    atrack.offset_ms,
                    fps,
                    timebase,
                    is_video=False,
                )

    def _add_clip_item(
        self,
        track: ET.Element,
        name: str,
        path: Path,
        source_start_ms: int,
        source_end_ms: int,
        timeline_start_ms: int,
        fps: float,
        timebase: int,
        width: int = 0,
        height: int = 0,
        is_video: bool = True,
    ) -> None:
        """Add a single clip item to the track."""
        clip_item = ET.SubElement(track, "clipitem")
        ET.SubElement(clip_item, "name").text = name

        duration_ms = source_end_ms - source_start_ms
        segment_frames = int(duration_ms * fps / 1000)
        ET.SubElement(clip_item, "duration").text = str(segment_frames)

        # Rate
        rate = ET.SubElement(clip_item, "rate")
        ET.SubElement(rate, "timebase").text = str(timebase)
        ET.SubElement(rate, "ntsc").text = "FALSE"

        # Timeline position
        start_frame = int(timeline_start_ms * fps / 1000)
        end_frame = start_frame + segment_frames
        ET.SubElement(clip_item, "start").text = str(start_frame)
        ET.SubElement(clip_item, "end").text = str(end_frame)

        # Source in/out points
        in_frame = int(source_start_ms * fps / 1000)
        out_frame = int(source_end_ms * fps / 1000)
        ET.SubElement(clip_item, "in").text = str(in_frame)
        ET.SubElement(clip_item, "out").text = str(out_frame)

        # File reference
        file_elem = ET.SubElement(clip_item, "file")
        ET.SubElement(file_elem, "name").text = name
        ET.SubElement(file_elem, "pathurl").text = f"file://localhost{path.absolute()}"

        # Media info for video
        if is_video and width and height:
            media_elem = ET.SubElement(file_elem, "media")
            video_elem = ET.SubElement(media_elem, "video")
            ET.SubElement(video_elem, "duration").text = str(segment_frames)
            sample_char = ET.SubElement(video_elem, "samplecharacteristics")
            ET.SubElement(sample_char, "width").text = str(width)
            ET.SubElement(sample_char, "height").text = str(height)

    def _ms_to_frames(self, ms: int, fps: float) -> int:
        """Convert milliseconds to frames."""
        return int(ms * fps / 1000)
