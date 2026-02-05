#!/usr/bin/env python3
"""Quick test for silence detection and FCPXML export (no Chalna).

Uses mock transcription data to test the pipeline without waiting for Chalna.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from avid.models.media import MediaFile, MediaInfo
from avid.models.project import Project, Transcription, TranscriptSegment
from avid.models.timeline import EditDecision
from avid.pipeline.stages.silence import detect_silence_from_segments
from avid.export.fcpxml import FCPXMLExporter


# Mock transcription data from last successful run
MOCK_SEGMENTS = [
    {"start_ms": 960, "end_ms": 5699, "text": "Let's sit down."},
    {"start_ms": 5699, "end_ms": 9180, "text": "안녕하세요."},
    {"start_ms": 9180, "end_ms": 15000, "text": "오늘은 네이버 D2SF 왔습니다."},
    {"start_ms": 18000, "end_ms": 25000, "text": "팀 어텐션 구원 엔트로피 구원."},
    {"start_ms": 28000, "end_ms": 35000, "text": "클로드 스킬 턴에 왔는데요."},
    {"start_ms": 38000, "end_ms": 45000, "text": "스킬을 만드는 해커 턴입니다."},
    {"start_ms": 50000, "end_ms": 58000, "text": "스킬은 월플로우를 자동화하는 건데"},
    {"start_ms": 60000, "end_ms": 70000, "text": "저도 자동화."},
    {"start_ms": 75000, "end_ms": 85000, "text": "오늘 저희는 영상 편집 자동화를 해보려고 합니다."},
    {"start_ms": 90000, "end_ms": 100000, "text": "무음 구간을 자동으로 제거하고"},
    {"start_ms": 105000, "end_ms": 115000, "text": "FCPXML로 내보내는 기능입니다."},
]


async def main():
    output_dir = Path("/home/jonhpark/workspace/auto-video-edit/samples")
    video_path = output_dir / "C1718_compressed.mp4"

    print("=" * 50)
    print("Quick Test: Silence Detection + FCPXML Export")
    print("=" * 50)

    # 1. Create mock transcription segments
    segments = [
        TranscriptSegment(
            start_ms=seg["start_ms"],
            end_ms=seg["end_ms"],
            text=seg["text"],
            confidence=1.0,
        )
        for seg in MOCK_SEGMENTS
    ]
    print(f"\nMock segments: {len(segments)}")

    # 2. Detect silence from gaps
    total_duration_ms = 119619  # From actual video
    min_silence_ms = 500

    edit_decisions = detect_silence_from_segments(
        segments=segments,
        min_silence_ms=min_silence_ms,
        total_duration_ms=total_duration_ms,
    )

    print(f"\nSilence Detection (threshold: {min_silence_ms}ms):")
    total_silence = sum(ed.range.duration_ms for ed in edit_decisions)
    print(f"  Found: {len(edit_decisions)} silence regions")
    print(f"  Total silence: {total_silence}ms ({total_silence/total_duration_ms*100:.1f}%)")

    for i, ed in enumerate(edit_decisions[:5]):
        print(f"  [{i+1}] {ed.range.start_ms}ms - {ed.range.end_ms}ms ({ed.range.duration_ms}ms)")
    if len(edit_decisions) > 5:
        print(f"  ... and {len(edit_decisions) - 5} more")

    # 3. Create Project
    media_info = MediaInfo(
        duration_ms=total_duration_ms,
        width=3840,
        height=2160,
        fps=23.976,
        sample_rate=48000,
    )

    media_file = MediaFile(
        path=video_path,
        original_name=video_path.name,
        info=media_info,
    )

    project = Project(name=video_path.stem)
    project.add_source_file(media_file)

    # Add transcription
    project.transcription = Transcription(
        source_track_id=f"{media_file.id}_audio",
        language="ko",
        segments=segments,
    )

    # Add edit decisions
    project.edit_decisions = edit_decisions

    # 4. Export FCPXML
    print("\n" + "=" * 50)
    print("Exporting...")
    print("=" * 50)

    exporter = FCPXMLExporter()
    fcpxml_path = output_dir / f"{video_path.stem}_test.fcpxml"
    await exporter.export(project, fcpxml_path)
    print(f"  FCPXML: {fcpxml_path}")

    # 5. Save SRT
    srt_path = output_dir / f"{video_path.stem}_test.srt"
    with open(srt_path, "w", encoding="utf-8") as f:
        for i, seg in enumerate(segments, 1):
            start = format_srt_time(seg.start_ms)
            end = format_srt_time(seg.end_ms)
            f.write(f"{i}\n{start} --> {end}\n{seg.text}\n\n")
    print(f"  SRT: {srt_path}")

    # 6. Save project JSON
    project_path = output_dir / f"{video_path.stem}_test.avid.json"
    project.save(project_path)
    print(f"  Project: {project_path}")

    # 7. Summary
    keep_duration = total_duration_ms - total_silence
    print(f"\nTimeline Summary:")
    print(f"  Total: {total_duration_ms/1000:.1f}s")
    print(f"  Keep:  {keep_duration/1000:.1f}s ({keep_duration/total_duration_ms*100:.1f}%)")
    print(f"  Cut:   {total_silence/1000:.1f}s ({total_silence/total_duration_ms*100:.1f}%)")

    print("\n" + "=" * 50)
    print("Done!")
    print("=" * 50)


def format_srt_time(ms: int) -> str:
    hours = ms // 3600000
    ms %= 3600000
    minutes = ms // 60000
    ms %= 60000
    seconds = ms // 1000
    milliseconds = ms % 1000
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"


if __name__ == "__main__":
    asyncio.run(main())
