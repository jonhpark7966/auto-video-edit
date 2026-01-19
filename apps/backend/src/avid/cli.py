"""Command-line interface for AVID."""

import argparse
import asyncio
from pathlib import Path

from avid.export.fcpxml import FCPXMLExporter
from avid.models.project import Project
from avid.services.media import MediaService


async def create_project(
    video_paths: list[Path],
    audio_paths: list[Path],
    output_path: Path,
    project_name: str = "Untitled Project",
) -> Path:
    """Create a project from video and audio files, export to FCPXML.

    Args:
        video_paths: List of video file paths
        audio_paths: List of audio file paths
        output_path: Path for output .fcpxml file
        project_name: Name for the project

    Returns:
        Path to the exported file
    """
    media_service = MediaService()

    # Create project
    project = Project(name=project_name)

    # Add video files
    for video_path in video_paths:
        print(f"분석 중: {video_path.name}")
        media_file = await media_service.create_media_file(video_path)
        tracks = project.add_source_file(media_file)

        print(f"  - 길이: {media_file.info.duration_seconds:.2f}초")
        print(f"  - 해상도: {media_file.info.resolution}")
        print(f"  - FPS: {media_file.info.fps}")
        print(f"  - 트랙 생성: {[t.id for t in tracks]}")

    # Add audio files
    for audio_path in audio_paths:
        print(f"분석 중: {audio_path.name}")
        media_file = await media_service.create_media_file(audio_path)
        tracks = project.add_source_file(media_file)

        print(f"  - 길이: {media_file.info.duration_seconds:.2f}초")
        print(f"  - 샘플레이트: {media_file.info.sample_rate}Hz")
        print(f"  - 트랙 생성: {[t.id for t in tracks]}")

    # Summary
    print(f"\n프로젝트 요약:")
    print(f"  - 소스 파일: {len(project.source_files)}개")
    print(f"  - 비디오 트랙: {len(project.get_video_tracks())}개")
    print(f"  - 오디오 트랙: {len(project.get_audio_tracks())}개")
    print(f"  - 총 길이: {project.duration_ms / 1000:.2f}초")

    # Save project file
    project_file = output_path.with_suffix(".avid.json")
    project.save(project_file)
    print(f"\n프로젝트 저장: {project_file}")

    # Export to FCPXML
    exporter = FCPXMLExporter()
    result_path = await exporter.export(project, output_path)
    print(f"FCPXML 내보내기: {result_path}")

    return result_path


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="AVID - Auto Video Edit CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "videos",
        type=Path,
        nargs="+",
        help="입력 영상 파일 경로 (여러 개 가능)",
    )

    parser.add_argument(
        "-a", "--audio",
        type=Path,
        action="append",
        default=[],
        help="별도 오디오 파일 경로 (여러 개 가능)",
    )

    parser.add_argument(
        "-o", "--output",
        type=Path,
        default=None,
        help="출력 파일 경로 (.fcpxml)",
    )

    parser.add_argument(
        "-n", "--name",
        type=str,
        default="Auto Edit Project",
        help="프로젝트 이름",
    )

    args = parser.parse_args()

    # Validate video inputs
    for video_path in args.videos:
        if not video_path.exists():
            print(f"오류: 영상 파일을 찾을 수 없습니다: {video_path}")
            return

    # Validate audio inputs
    for audio_path in args.audio:
        if not audio_path.exists():
            print(f"오류: 오디오 파일을 찾을 수 없습니다: {audio_path}")
            return

    # Set default output path
    output_path = args.output
    if output_path is None:
        output_path = args.videos[0].with_suffix(".fcpxml")

    # Run
    asyncio.run(create_project(args.videos, args.audio, output_path, args.name))


if __name__ == "__main__":
    main()
