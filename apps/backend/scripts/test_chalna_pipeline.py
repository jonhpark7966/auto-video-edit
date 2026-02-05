#!/usr/bin/env python3
"""End-to-end test script for Chalna transcription pipeline.

Usage:
    python scripts/test_chalna_pipeline.py <video_or_audio_file> [options]

Example:
    python scripts/test_chalna_pipeline.py ~/videos/test.mp4 --min-silence 500 --output ./output
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Add src to path for development
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from avid.models.media import MediaFile, MediaInfo
from avid.models.pipeline import PipelineConfig
from avid.models.project import Project, Transcription, TranscriptSegment
from avid.models.timeline import EditDecision
from avid.pipeline.context import PipelineContext
from avid.pipeline.executor import PipelineExecutor
from avid.pipeline.stages import SilenceStage, TranscriptionStage
from avid.export.fcpxml import FCPXMLExporter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def get_media_info(file_path: Path) -> MediaInfo:
    """Get media info using ffprobe.

    For now, returns dummy info. In production, use FFmpeg service.
    """
    import subprocess
    import json

    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v", "quiet",
                "-print_format", "json",
                "-show_format",
                "-show_streams",
                str(file_path),
            ],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            logger.warning(f"ffprobe failed, using default values")
            return MediaInfo(duration_ms=0)

        data = json.loads(result.stdout)

        # Get duration
        duration_sec = float(data.get("format", {}).get("duration", 0))
        duration_ms = int(duration_sec * 1000)

        # Find video and audio streams
        width = None
        height = None
        fps = None
        sample_rate = None

        for stream in data.get("streams", []):
            if stream.get("codec_type") == "video":
                width = stream.get("width")
                height = stream.get("height")
                # Parse fps from avg_frame_rate (e.g., "30/1")
                fps_str = stream.get("avg_frame_rate", "0/1")
                if "/" in fps_str:
                    num, den = fps_str.split("/")
                    fps = float(num) / float(den) if float(den) > 0 else None
            elif stream.get("codec_type") == "audio":
                sample_rate = int(stream.get("sample_rate", 0)) or None

        return MediaInfo(
            duration_ms=duration_ms,
            width=width,
            height=height,
            fps=fps,
            sample_rate=sample_rate,
        )
    except Exception as e:
        logger.warning(f"Error getting media info: {e}")
        return MediaInfo(duration_ms=0)


def progress_callback(stage_name: str, status: str, progress: float) -> None:
    """Print progress updates."""
    bar_width = 30
    filled = int(bar_width * progress)
    bar = "=" * filled + "-" * (bar_width - filled)
    print(f"\r[{bar}] {progress*100:.1f}% - {stage_name}: {status}", end="", flush=True)


async def run_pipeline(
    input_file: Path,
    output_dir: Path,
    min_silence_ms: int = 500,
    language: str = "ko",
    use_alignment: bool = True,
    use_llm_refinement: bool = False,
    chalna_url: str | None = None,
) -> Path:
    """Run the full transcription and silence detection pipeline.

    Args:
        input_file: Path to input video/audio file.
        output_dir: Directory for output files.
        min_silence_ms: Minimum silence duration threshold.
        language: Transcription language.
        use_alignment: Use Qwen2 alignment.
        use_llm_refinement: Use LLM text refinement.
        chalna_url: Optional Chalna API URL override.

    Returns:
        Path to exported FCPXML file.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"Processing: {input_file}")
    logger.info(f"Output dir: {output_dir}")

    # 1. Get media info
    logger.info("Getting media info...")
    media_info = await get_media_info(input_file)
    logger.info(f"  Duration: {media_info.duration_ms}ms ({media_info.duration_seconds:.1f}s)")
    if media_info.width:
        logger.info(f"  Resolution: {media_info.resolution}")
    if media_info.fps:
        logger.info(f"  FPS: {media_info.fps}")

    # 2. Create MediaFile
    media_file = MediaFile(
        path=input_file.absolute(),
        original_name=input_file.name,
        info=media_info,
    )

    # 3. Create pipeline context
    context = PipelineContext(
        video_file=media_file if media_file.is_video else None,
        audio_file=media_file if media_file.is_audio_only else None,
        working_dir=output_dir / "temp",
        output_dir=output_dir,
    )

    # If it's a video, also set audio_file for transcription
    if media_file.is_video:
        context.audio_file = media_file

    # 4. Create and configure executor
    executor = PipelineExecutor()
    executor.register_stage(TranscriptionStage())
    executor.register_stage(SilenceStage())

    logger.info("Registered stages:")
    for name, display_name in executor.list_stages():
        logger.info(f"  - {name}: {display_name}")

    # 5. Create pipeline config
    config = PipelineConfig(
        stages=["transcribe", "silence"],
        stage_options={
            "transcribe": {
                "language": language,
                "use_alignment": use_alignment,
                "use_llm_refinement": use_llm_refinement,
                "chalna_url": chalna_url,
            },
            "silence": {
                "min_silence_ms": min_silence_ms,
            },
        },
    )

    # 6. Execute pipeline
    logger.info("\n" + "=" * 50)
    logger.info("Starting pipeline execution...")
    logger.info("=" * 50)

    results = await executor.execute(context, config, progress_callback)
    print()  # New line after progress bar

    # 7. Save SRT immediately after transcription (before any errors)
    transcribe_data = context.get_stage_data("transcribe")
    if transcribe_data and "transcription" in transcribe_data:
        trans_dict = transcribe_data["transcription"]
        segments = trans_dict.get("segments", [])
        if segments:
            srt_path = output_dir / f"{input_file.stem}.srt"
            with open(srt_path, "w", encoding="utf-8") as f:
                for i, seg in enumerate(segments, 1):
                    start = format_srt_time(seg["start_ms"])
                    end = format_srt_time(seg["end_ms"])
                    f.write(f"{i}\n{start} --> {end}\n{seg['text']}\n\n")
            logger.info(f"SRT saved immediately: {srt_path}")

    # 8. Print results
    logger.info("\n" + "=" * 50)
    logger.info("Pipeline Results:")
    logger.info("=" * 50)

    for stage_name, result in results.items():
        logger.info(f"\n[{stage_name}] Status: {result.status.value}")
        if result.message:
            logger.info(f"  Message: {result.message}")
        if result.data:
            for key, value in result.data.items():
                if isinstance(value, list) and len(value) > 3:
                    logger.info(f"  {key}: [{len(value)} items]")
                else:
                    logger.info(f"  {key}: {value}")

    # 8. Create Project for export
    logger.info("\n" + "=" * 50)
    logger.info("Creating Project for export...")
    logger.info("=" * 50)

    project = Project(name=input_file.stem)
    project.add_source_file(media_file)

    # Add transcription to project
    transcribe_data = context.get_stage_data("transcribe")
    if transcribe_data and "transcription" in transcribe_data:
        trans_dict = transcribe_data["transcription"]
        project.transcription = Transcription(
            source_track_id=trans_dict["source_track_id"],
            language=trans_dict["language"],
            segments=[
                TranscriptSegment(**seg)
                for seg in trans_dict["segments"]
            ],
        )
        logger.info(f"  Transcription: {len(project.transcription.segments)} segments")

    # Add edit decisions from silence stage
    silence_data = context.get_stage_data("silence")
    if silence_data and "edit_decisions" in silence_data:
        for ed_dict in silence_data["edit_decisions"]:
            ed = EditDecision.model_validate(ed_dict)
            project.edit_decisions.append(ed)
        logger.info(f"  Edit decisions: {len(project.edit_decisions)} cuts")

    # Calculate keep vs cut
    total_duration = media_info.duration_ms
    cut_duration = sum(ed.range.duration_ms for ed in project.edit_decisions)
    keep_duration = total_duration - cut_duration

    logger.info(f"\nTimeline Summary:")
    logger.info(f"  Total duration: {total_duration/1000:.1f}s")
    logger.info(f"  Keep duration:  {keep_duration/1000:.1f}s ({keep_duration/total_duration*100:.1f}%)")
    logger.info(f"  Cut duration:   {cut_duration/1000:.1f}s ({cut_duration/total_duration*100:.1f}%)")

    # 9. Export to FCPXML
    logger.info("\n" + "=" * 50)
    logger.info("Exporting to FCPXML...")
    logger.info("=" * 50)

    exporter = FCPXMLExporter()
    output_path = output_dir / f"{input_file.stem}.fcpxml"

    exported_path = await exporter.export(project, output_path)
    logger.info(f"  Exported: {exported_path}")

    # 10. Save project JSON for debugging
    project_path = output_dir / f"{input_file.stem}.avid.json"
    project.save(project_path)
    logger.info(f"  Project saved: {project_path}")

    # 11. Export SRT subtitles
    if project.transcription:
        srt_path = output_dir / f"{input_file.stem}.srt"
        export_srt(project.transcription, srt_path)
        logger.info(f"  Subtitles saved: {srt_path}")

    logger.info("\n" + "=" * 50)
    logger.info("Done!")
    logger.info("=" * 50)

    return exported_path


def export_srt(transcription: Transcription, output_path: Path) -> None:
    """Export transcription as SRT subtitle file."""
    lines = []
    for i, seg in enumerate(transcription.segments, 1):
        start = format_srt_time(seg.start_ms)
        end = format_srt_time(seg.end_ms)
        lines.append(f"{i}")
        lines.append(f"{start} --> {end}")
        lines.append(seg.text)
        lines.append("")

    output_path.write_text("\n".join(lines), encoding="utf-8")


def format_srt_time(ms: int) -> str:
    """Format milliseconds as SRT timestamp (HH:MM:SS,mmm)."""
    hours = ms // 3600000
    ms %= 3600000
    minutes = ms // 60000
    ms %= 60000
    seconds = ms // 1000
    milliseconds = ms % 1000
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"


def main():
    parser = argparse.ArgumentParser(
        description="Test Chalna transcription pipeline end-to-end"
    )
    parser.add_argument(
        "input_file",
        type=Path,
        help="Input video or audio file",
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=Path("./output"),
        help="Output directory (default: ./output)",
    )
    parser.add_argument(
        "--min-silence", "-s",
        type=int,
        default=500,
        help="Minimum silence duration in ms (default: 500)",
    )
    parser.add_argument(
        "--language", "-l",
        type=str,
        default="ko",
        help="Transcription language (default: ko)",
    )
    parser.add_argument(
        "--no-alignment",
        action="store_true",
        help="Disable Qwen2 alignment",
    )
    parser.add_argument(
        "--use-llm",
        action="store_true",
        help="Enable LLM text refinement",
    )
    parser.add_argument(
        "--chalna-url",
        type=str,
        help="Chalna API URL (default: CHALNA_API_URL env or http://localhost:7861)",
    )

    args = parser.parse_args()

    if not args.input_file.exists():
        print(f"Error: Input file not found: {args.input_file}")
        sys.exit(1)

    try:
        asyncio.run(run_pipeline(
            input_file=args.input_file,
            output_dir=args.output,
            min_silence_ms=args.min_silence,
            language=args.language,
            use_alignment=not args.no_alignment,
            use_llm_refinement=args.use_llm,
            chalna_url=args.chalna_url,
        ))
    except KeyboardInterrupt:
        print("\nInterrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.exception(f"Pipeline failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
