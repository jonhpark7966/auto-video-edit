#!/usr/bin/env python3
"""Full workflow test: Chalna transcription -> silence detection -> FCPXML export."""

import asyncio
import subprocess
import json
from pathlib import Path

# Add backend to path
import sys
sys.path.insert(0, str(Path(__file__).parent / "apps/backend/src"))

from avid.models.media import MediaFile, MediaInfo
from avid.models.project import Project, Transcription, TranscriptSegment
from avid.models.timeline import EditDecision, EditType, EditReason, TimeRange
from avid.services.transcription import ChalnaTranscriptionService, seconds_to_ms
from avid.export.fcpxml import FCPXMLExporter


def get_media_info(video_path: Path) -> MediaInfo:
    """Get media info using ffprobe."""
    cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams", str(video_path)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    data = json.loads(result.stdout)

    # Find video stream
    video_stream = next((s for s in data["streams"] if s["codec_type"] == "video"), None)
    audio_stream = next((s for s in data["streams"] if s["codec_type"] == "audio"), None)

    duration_ms = int(float(data["format"]["duration"]) * 1000)

    # Parse frame rate (e.g., "24000/1001" -> 23.976)
    fps = None
    if video_stream and "r_frame_rate" in video_stream:
        fps_str = video_stream["r_frame_rate"]
        if "/" in fps_str:
            num, den = fps_str.split("/")
            fps = float(num) / float(den)
        else:
            fps = float(fps_str)

    return MediaInfo(
        duration_ms=duration_ms,
        width=int(video_stream["width"]) if video_stream else None,
        height=int(video_stream["height"]) if video_stream else None,
        fps=fps,
        sample_rate=int(audio_stream["sample_rate"]) if audio_stream else None,
    )


def detect_silence_from_gaps(
    segments: list[TranscriptSegment],
    total_duration_ms: int,
    min_silence_ms: int = 500,
    video_track_id: str = "",
) -> list[EditDecision]:
    """Detect silence based on gaps between subtitle segments."""
    edit_decisions = []

    if not segments:
        return edit_decisions

    # Gap from start to first segment
    if segments[0].start_ms >= min_silence_ms:
        edit_decisions.append(EditDecision(
            range=TimeRange(start_ms=0, end_ms=segments[0].start_ms),
            edit_type=EditType.CUT,
            reason=EditReason.SILENCE,
            active_video_track_id=video_track_id,
        ))

    # Gaps between segments
    for i in range(len(segments) - 1):
        gap_start = segments[i].end_ms
        gap_end = segments[i + 1].start_ms
        if gap_end - gap_start >= min_silence_ms:
            edit_decisions.append(EditDecision(
                range=TimeRange(start_ms=gap_start, end_ms=gap_end),
                edit_type=EditType.CUT,
                reason=EditReason.SILENCE,
                active_video_track_id=video_track_id,
            ))

    # Gap from last segment to end
    if total_duration_ms - segments[-1].end_ms >= min_silence_ms:
        edit_decisions.append(EditDecision(
            range=TimeRange(start_ms=segments[-1].end_ms, end_ms=total_duration_ms),
            edit_type=EditType.CUT,
            reason=EditReason.SILENCE,
            active_video_track_id=video_track_id,
        ))

    return edit_decisions


def segments_to_srt(segments: list[TranscriptSegment], output_path: Path) -> None:
    """Export segments to SRT file."""
    def ms_to_srt_time(ms: int) -> str:
        hours = ms // 3600000
        minutes = (ms % 3600000) // 60000
        seconds = (ms % 60000) // 1000
        millis = ms % 1000
        return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"

    lines = []
    for i, seg in enumerate(segments, 1):
        lines.append(str(i))
        lines.append(f"{ms_to_srt_time(seg.start_ms)} --> {ms_to_srt_time(seg.end_ms)}")
        lines.append(seg.text)
        lines.append("")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


async def main():
    samples_dir = Path(__file__).parent / "samples"
    video_path = samples_dir / "C1718_compressed.mp4"

    if not video_path.exists():
        print(f"Error: {video_path} not found")
        return

    # Step 1: Get media info
    print("=" * 60)
    print("Step 1: Getting media info...")
    media_info = get_media_info(video_path)
    print(f"  Duration: {media_info.duration_ms}ms ({media_info.duration_seconds:.2f}s)")
    print(f"  Resolution: {media_info.width}x{media_info.height}")
    print(f"  FPS: {media_info.fps}")
    print(f"  Sample rate: {media_info.sample_rate}")

    # Step 2: Transcribe with Chalna
    print("\n" + "=" * 60)
    print("Step 2: Transcribing with Chalna API...")
    print("  Options: vibe_voice + forced_align + llm_refined")

    chalna = ChalnaTranscriptionService()

    # Check API health
    if not await chalna.health_check():
        print("  Error: Chalna API not available")
        return

    def progress_callback(progress: float, status: str):
        print(f"  [{progress*100:.0f}%] {status}")

    try:
        result = await chalna.transcribe_async(
            audio_path=video_path,
            language="ko",
            use_alignment=True,  # Qwen2-based forced alignment
            use_llm_refinement=True,  # LLM text refinement
            progress_callback=progress_callback,
        )
        print(f"  Transcription complete: {len(result.segments)} segments")
    except Exception as e:
        print(f"  Error: {e}")
        return

    # Convert Chalna segments to TranscriptSegments
    segments = [
        TranscriptSegment(
            start_ms=seconds_to_ms(seg.start),
            end_ms=seconds_to_ms(seg.end),
            text=seg.text,
        )
        for seg in result.segments
    ]

    # Step 3: Save original SRT
    print("\n" + "=" * 60)
    print("Step 3: Saving original SRT...")
    original_srt_path = samples_dir / "C1718_original.srt"
    segments_to_srt(segments, original_srt_path)
    print(f"  Saved: {original_srt_path}")

    # Step 4: Create project
    print("\n" + "=" * 60)
    print("Step 4: Creating project...")

    media_file = MediaFile(
        path=video_path.absolute(),
        original_name=video_path.name,
        info=media_info,
    )

    project = Project(name="C1718_silence_edited")
    tracks = project.add_source_file(media_file)
    video_track = next(t for t in tracks if t.is_video)
    audio_track = next(t for t in tracks if t.is_audio)

    # Add transcription
    project.transcription = Transcription(
        source_track_id=audio_track.id,
        language="ko",
        segments=segments,
    )

    print(f"  Video track: {video_track.id}")
    print(f"  Audio track: {audio_track.id}")
    print(f"  Segments: {len(segments)}")

    # Step 5: Detect silence from gaps
    print("\n" + "=" * 60)
    print("Step 5: Detecting silence from subtitle gaps...")

    silence_decisions = detect_silence_from_gaps(
        segments=segments,
        total_duration_ms=media_info.duration_ms,
        min_silence_ms=500,  # 0.5s threshold
        video_track_id=video_track.id,
    )

    project.edit_decisions.extend(silence_decisions)

    print(f"  Found {len(silence_decisions)} silence regions:")
    total_silence_ms = sum(d.range.duration_ms for d in silence_decisions)
    print(f"  Total silence: {total_silence_ms}ms ({total_silence_ms/1000:.2f}s)")
    print(f"  Remaining: {media_info.duration_ms - total_silence_ms}ms")

    # Step 6: Export FCPXML (both modes)
    print("\n" + "=" * 60)
    print("Step 6: Exporting FCPXML...")

    exporter = FCPXMLExporter()

    # CUT mode (silence removed)
    cut_output = samples_dir / "C1718_silence_cut.fcpxml"
    fcpxml_path, srt_path = await exporter.export(project, cut_output, show_disabled_cuts=False)
    print(f"  CUT mode: {fcpxml_path}")
    if srt_path:
        print(f"  Adjusted SRT: {srt_path}")

    # DISABLED mode (silence present but disabled)
    disabled_output = samples_dir / "C1718_silence_disabled.fcpxml"
    fcpxml_path2, srt_path2 = await exporter.export(project, disabled_output, show_disabled_cuts=True)
    print(f"  DISABLED mode: {fcpxml_path2}")
    if srt_path2:
        print(f"  Original SRT: {srt_path2}")

    # Step 7: Save project
    print("\n" + "=" * 60)
    print("Step 7: Saving project...")
    project_path = project.save(samples_dir / "C1718_compressed.avid.json")
    print(f"  Saved: {project_path}")

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Original duration: {media_info.duration_ms/1000:.2f}s")
    print(f"Silence removed:   {total_silence_ms/1000:.2f}s")
    print(f"Final duration:    {(media_info.duration_ms - total_silence_ms)/1000:.2f}s")
    print(f"Segments:          {len(segments)}")
    print(f"Silence regions:   {len(silence_decisions)}")
    print()
    print("Generated files:")
    print(f"  - {original_srt_path.name} (original transcription)")
    print(f"  - {cut_output.name} (silence removed)")
    print(f"  - {cut_output.with_suffix('.srt').name} (adjusted timestamps)")
    print(f"  - {disabled_output.name} (silence disabled)")
    print(f"  - {disabled_output.with_suffix('.srt').name} (original timestamps)")
    print(f"  - {project_path.name} (AVID project)")


if __name__ == "__main__":
    asyncio.run(main())
