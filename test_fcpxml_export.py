#!/usr/bin/env python3
"""Test FCPXML export using actual exporter with real SRT data."""

import asyncio
import re
import sys
from pathlib import Path

# Add the backend src to path
sys.path.insert(0, str(Path(__file__).parent / "apps/backend/src"))

from avid.models.media import MediaFile, MediaInfo
from avid.models.project import Project, Transcription, TranscriptSegment
from avid.models.timeline import EditDecision, EditReason, EditType, TimeRange
from avid.export.fcpxml import FCPXMLExporter


def parse_srt_time(time_str: str) -> int:
    """Parse SRT time format (HH:MM:SS,mmm) to milliseconds."""
    match = re.match(r'(\d{2}):(\d{2}):(\d{2}),(\d{3})', time_str)
    if not match:
        raise ValueError(f"Invalid time format: {time_str}")
    hours, minutes, seconds, ms = map(int, match.groups())
    return hours * 3600000 + minutes * 60000 + seconds * 1000 + ms


def parse_srt(srt_path: Path) -> list[tuple[int, int, str]]:
    """Parse SRT file and return list of (start_ms, end_ms, text)."""
    content = srt_path.read_text(encoding='utf-8')
    segments = []

    blocks = re.split(r'\n\n+', content.strip())

    for block in blocks:
        lines = block.strip().split('\n')
        if len(lines) >= 2:
            time_match = re.match(r'(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})', lines[1])
            if time_match:
                start_ms = parse_srt_time(time_match.group(1))
                end_ms = parse_srt_time(time_match.group(2))
                text = '\n'.join(lines[2:]) if len(lines) > 2 else ''
                segments.append((start_ms, end_ms, text))

    return segments


def create_silence_edit_decisions(
    segments: list[tuple[int, int, str]],
    total_duration_ms: int,
    video_track_id: str,
    min_silence_ms: int = 500,
) -> list[EditDecision]:
    """Create CUT edit decisions for silence gaps between subtitle segments."""
    edit_decisions = []

    if not segments:
        return edit_decisions

    # Gap before first segment
    if segments[0][0] >= min_silence_ms:
        edit_decisions.append(EditDecision(
            range=TimeRange(start_ms=0, end_ms=segments[0][0]),
            edit_type=EditType.CUT,
            reason=EditReason.SILENCE,
            active_video_track_id=video_track_id,
        ))

    # Gaps between segments
    for i in range(len(segments) - 1):
        gap_start = segments[i][1]
        gap_end = segments[i + 1][0]
        if gap_end - gap_start >= min_silence_ms:
            edit_decisions.append(EditDecision(
                range=TimeRange(start_ms=gap_start, end_ms=gap_end),
                edit_type=EditType.CUT,
                reason=EditReason.SILENCE,
                active_video_track_id=video_track_id,
            ))

    # Gap after last segment
    if total_duration_ms - segments[-1][1] >= min_silence_ms:
        edit_decisions.append(EditDecision(
            range=TimeRange(start_ms=segments[-1][1], end_ms=total_duration_ms),
            edit_type=EditType.CUT,
            reason=EditReason.SILENCE,
            active_video_track_id=video_track_id,
        ))

    return edit_decisions


def create_transcription(
    segments: list[tuple[int, int, str]],
    audio_track_id: str,
) -> Transcription:
    """Create Transcription from SRT segments."""
    transcript_segments = [
        TranscriptSegment(
            start_ms=start_ms,
            end_ms=end_ms,
            text=text,
            confidence=1.0,
        )
        for start_ms, end_ms, text in segments
    ]

    return Transcription(
        source_track_id=audio_track_id,
        language="ko",
        segments=transcript_segments,
    )


async def main():
    # Video file info (from FCP export)
    # Path should be the macOS path where FCP will find it
    video_path = Path("/Users/jonhpark/workspace/auto-video-edit/srcs/C1718_compressed.mp4")

    media_info = MediaInfo(
        duration_ms=119620,  # 119.62 seconds
        width=3840,
        height=2160,
        fps=23.976,
        sample_rate=48000,
    )

    media_file = MediaFile(
        id="video_001",
        path=video_path,
        original_name="C1718_compressed.mp4",
        info=media_info,
    )

    # Create project
    project = Project(name="C1718_silence_edited")
    project.add_source_file(media_file)

    # Get track IDs
    video_track = project.get_video_tracks()[0]
    audio_track = project.get_audio_tracks()[0]
    print(f"Video track ID: {video_track.id}")
    print(f"Audio track ID: {audio_track.id}")

    # Parse SRT
    srt_path = Path(__file__).parent / "srcs/C1718_compressed.srt"
    segments = parse_srt(srt_path)
    print(f"Parsed {len(segments)} subtitle segments")

    # Create transcription from SRT (for captions)
    transcription = create_transcription(segments, audio_track.id)
    project.transcription = transcription
    print(f"Created transcription with {len(transcription.segments)} segments")

    # Create silence cut decisions
    edit_decisions = create_silence_edit_decisions(
        segments,
        total_duration_ms=media_info.duration_ms,
        video_track_id=video_track.id,
        min_silence_ms=500,
    )
    print(f"Created {len(edit_decisions)} silence cut decisions")
    project.edit_decisions = edit_decisions

    # Export using actual exporter
    exporter = FCPXMLExporter()
    samples_dir = Path(__file__).parent / "samples"

    # Mode 1: CUT mode (silence removed, SRT adjusted)
    cut_output_path = samples_dir / "C1718_silence_cut.fcpxml"
    fcpxml_path, srt_path = await exporter.export(project, cut_output_path, show_disabled_cuts=False)
    print(f"\n[CUT MODE]")
    print(f"  FCPXML: {fcpxml_path}")
    print(f"  SRT: {srt_path}")

    # Mode 2: Disabled mode (silence disabled but visible, SRT unchanged)
    disabled_output_path = samples_dir / "C1718_silence_disabled.fcpxml"
    fcpxml_path, srt_path = await exporter.export(project, disabled_output_path, show_disabled_cuts=True)
    print(f"\n[DISABLED MODE]")
    print(f"  FCPXML: {fcpxml_path}")
    print(f"  SRT: {srt_path}")

    # Print summary
    total_cut_ms = sum(d.range.duration_ms for d in edit_decisions)
    final_duration_ms = media_info.duration_ms - total_cut_ms
    print(f"\nSummary:")
    print(f"  Original duration: {media_info.duration_ms/1000:.2f}s")
    print(f"  Total silence cut: {total_cut_ms/1000:.2f}s")
    print(f"  Final duration (CUT mode): {final_duration_ms/1000:.2f}s")
    print(f"  Subtitle segments: {len(segments)}")

    # Show cut decisions
    print(f"\nSilence cut decisions:")
    for i, d in enumerate(edit_decisions):
        print(f"  {i+1}. {d.range.start_ms/1000:.2f}s - {d.range.end_ms/1000:.2f}s ({d.range.duration_ms/1000:.2f}s)")


if __name__ == "__main__":
    asyncio.run(main())
