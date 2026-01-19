"""Command-line interface for AVID."""

import argparse
import asyncio
from pathlib import Path

from avid.export.fcpxml import FCPXMLExporter
from avid.models.media import MediaFile
from avid.models.timeline import Timeline
from avid.services.media import MediaService


async def create_basic_project(
    video_path: Path,
    audio_path: Path | None,
    output_path: Path,
) -> Path:
    """Create a basic FCP XML project from video and optional audio.

    Args:
        video_path: Path to video file
        audio_path: Optional path to separate audio file
        output_path: Path for output .fcpxml file

    Returns:
        Path to the exported file
    """
    media_service = MediaService()

    # Get video info
    print(f"분석 중: {video_path.name}")
    video_file = await media_service.create_media_file(video_path)
    print(f"  - 길이: {video_file.info.duration_seconds:.2f}초")
    print(f"  - 해상도: {video_file.info.resolution}")
    print(f"  - FPS: {video_file.info.fps}")

    # Create timeline from video
    timeline = Timeline(
        source_media=video_file,
        edit_decisions=[],  # No edits for basic project
        duration_ms=video_file.info.duration_ms,
    )

    if audio_path:
        print(f"분석 중: {audio_path.name}")
        audio_file = await media_service.create_media_file(audio_path)
        print(f"  - 길이: {audio_file.info.duration_seconds:.2f}초")
        print(f"  - 샘플레이트: {audio_file.info.sample_rate}Hz")

    # Export to FCPXML
    exporter = FCPXMLExporter()
    result_path = await exporter.export(timeline, output_path)

    print(f"\n내보내기 완료: {result_path}")
    return result_path


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="AVID - Auto Video Edit CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "video",
        type=Path,
        help="입력 영상 파일 경로",
    )

    parser.add_argument(
        "-a", "--audio",
        type=Path,
        default=None,
        help="별도 오디오 파일 경로 (선택)",
    )

    parser.add_argument(
        "-o", "--output",
        type=Path,
        default=None,
        help="출력 파일 경로 (.fcpxml)",
    )

    args = parser.parse_args()

    # Validate inputs
    if not args.video.exists():
        print(f"오류: 영상 파일을 찾을 수 없습니다: {args.video}")
        return

    if args.audio and not args.audio.exists():
        print(f"오류: 오디오 파일을 찾을 수 없습니다: {args.audio}")
        return

    # Set default output path
    output_path = args.output
    if output_path is None:
        output_path = args.video.with_suffix(".fcpxml")

    # Run
    asyncio.run(create_basic_project(args.video, args.audio, output_path))


if __name__ == "__main__":
    main()
