"""AVID command-line interface with subcommands.

Usage:
    avid-cli transcribe <video> [-l ko] [--chalna-url URL]
    avid-cli transcript-overview <srt> [-o storyline.json] [--provider codex] [--content-type auto]
    avid-cli subtitle-cut <video> --srt sub.srt [--provider codex] [--context storyline.json] [-o output.fcpxml]
    avid-cli podcast-cut <audio> [--srt sub.srt] [--provider codex] [--context storyline.json] [-d output_dir]
    avid-cli eval <predicted.fcpxml> <ground-truth.fcpxml>
"""

import argparse
import asyncio
import json
import subprocess
import sys
from pathlib import Path

from avid.export.fcpxml import FCPXMLExporter
from avid.models.project import Project
from avid.services.evaluation import FCPXMLEvaluator


# --- Transcribe subcommand ---

_VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".flv", ".wmv"}


def _extract_audio(video_path: Path, output_dir: Path) -> Path:
    """Extract audio from video file using ffmpeg.

    Returns:
        Path to extracted WAV file.
    """
    wav_path = output_dir / f"{video_path.stem}_audio.wav"
    cmd = [
        "ffmpeg", "-y", "-i", str(video_path),
        "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
        str(wav_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg 오디오 추출 실패:\n{result.stderr[-1000:]}")
    return wav_path


async def cmd_transcribe(args: argparse.Namespace) -> None:
    """Run transcription using Chalna API."""
    video_path = Path(args.input).resolve()
    if not video_path.exists():
        print(f"오류: 파일을 찾을 수 없습니다: {video_path}", file=sys.stderr)
        sys.exit(1)

    output_dir = Path(args.output_dir) if args.output_dir else video_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)

    # Extract audio if input is a video file
    audio_path = video_path
    temp_audio = None
    if video_path.suffix.lower() in _VIDEO_EXTENSIONS:
        print(f"비디오에서 오디오 추출 중: {video_path.name}")
        audio_path = _extract_audio(video_path, output_dir)
        temp_audio = audio_path
        print(f"  추출 완료: {audio_path.name}")

    from avid.services.transcription import ChalnaTranscriptionService

    chalna_url = args.chalna_url
    service = ChalnaTranscriptionService(base_url=chalna_url)

    print(f"음성 인식 시작 (Chalna API): {video_path.name}")
    print(f"  API: {service.base_url}")
    print(f"  언어: {args.language}")

    if not await service.health_check():
        print(f"오류: Chalna API에 연결할 수 없습니다: {service.base_url}", file=sys.stderr)
        sys.exit(1)

    def progress_cb(progress: float, status: str) -> None:
        bar_width = 30
        filled = int(bar_width * progress)
        bar = "=" * filled + "-" * (bar_width - filled)
        print(f"\r  [{bar}] {progress*100:.0f}% {status}", end="", flush=True)

    try:
        result = await service.transcribe_async(
            audio_path=audio_path,
            language=args.language,
            progress_callback=progress_cb,
        )
    finally:
        if temp_audio and temp_audio.exists():
            temp_audio.unlink()
    print()  # newline after progress bar

    # Save as SRT
    srt_path = output_dir / f"{video_path.stem}.srt"
    lines = []
    for i, seg in enumerate(result.segments, 1):
        start_ms = int(seg.start * 1000)
        end_ms = int(seg.end * 1000)
        start_str = _ms_to_srt_time(start_ms)
        end_str = _ms_to_srt_time(end_ms)
        lines.append(f"{i}\n{start_str} --> {end_str}\n{seg.text}\n")
    srt_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"  세그먼트: {len(result.segments)}개")

    print(f"\n완료: {srt_path}")


def _ms_to_srt_time(ms: int) -> str:
    """Format milliseconds as SRT timestamp."""
    hours = ms // 3600000
    ms %= 3600000
    minutes = ms // 60000
    ms %= 60000
    seconds = ms // 1000
    millis = ms % 1000
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


# --- Transcript overview subcommand ---

async def cmd_transcript_overview(args: argparse.Namespace) -> None:
    """Run transcript overview analysis (Pass 1)."""
    from avid.services.transcript_overview import TranscriptOverviewService

    service = TranscriptOverviewService()

    srt_path = Path(args.input).resolve()
    if not srt_path.exists():
        print(f"오류: SRT 파일을 찾을 수 없습니다: {srt_path}", file=sys.stderr)
        sys.exit(1)

    output_path = Path(args.output).resolve() if args.output else None

    print(f"스토리 구조 분석 시작: {srt_path.name}")
    print(f"  콘텐츠 유형: {args.content_type}")
    print(f"  프로바이더: {args.provider}")

    storyline_path = await service.analyze(
        srt_path=srt_path,
        output_path=output_path,
        content_type=args.content_type,
        provider=args.provider,
    )

    # Load and show summary
    storyline = service.load_storyline(storyline_path)
    chapters = storyline.get("chapters", [])
    deps = storyline.get("dependencies", [])
    kms = storyline.get("key_moments", [])

    print(f"\n완료!")
    print(f"  챕터: {len(chapters)}개")
    print(f"  의존성: {len(deps)}개")
    print(f"  핵심 순간: {len(kms)}개")
    print(f"  출력: {storyline_path}")


# --- Subtitle cut subcommand ---

async def cmd_subtitle_cut(args: argparse.Namespace) -> None:
    """Run subtitle cut analysis."""
    from avid.services.subtitle_cut import SubtitleCutService

    service = SubtitleCutService()

    video_path = Path(args.input).resolve()
    srt_path = Path(args.srt).resolve()
    context_path = Path(args.context).resolve() if args.context else None

    if not video_path.exists():
        print(f"오류: 비디오 파일을 찾을 수 없습니다: {video_path}", file=sys.stderr)
        sys.exit(1)
    if not srt_path.exists():
        print(f"오류: SRT 파일을 찾을 수 없습니다: {srt_path}", file=sys.stderr)
        sys.exit(1)
    if context_path and not context_path.exists():
        print(f"오류: Context 파일을 찾을 수 없습니다: {context_path}", file=sys.stderr)
        sys.exit(1)

    output_dir = Path(args.output_dir) if args.output_dir else video_path.parent
    export_mode = "final" if args.final else "review"

    print(f"자막 분석 시작: {srt_path.name}")
    print(f"  비디오: {video_path.name}")
    print(f"  프로바이더: {args.provider}")
    print(f"  모드: {export_mode} ({'모든 편집 적용' if export_mode == 'final' else '검토용 disabled'})")
    if context_path:
        print(f"  컨텍스트: {context_path.name}")

    project, project_path = await service.analyze(
        srt_path=srt_path,
        video_path=video_path,
        output_dir=output_dir,
        storyline_path=context_path,
        provider=args.provider,
    )

    # Export to FCPXML + adjusted SRT
    fcpxml_path = Path(args.output) if args.output else output_dir / f"{srt_path.stem}_subtitle_cut.fcpxml"
    exporter = FCPXMLExporter()

    if export_mode == "final":
        show_disabled = False
        content_mode = "cut"
    else:
        show_disabled = True
        content_mode = "disabled"

    fcpxml_result, srt_result = await exporter.export(
        project,
        fcpxml_path,
        show_disabled_cuts=show_disabled,
        silence_mode="cut",
        content_mode=content_mode,
    )

    print(f"\n결과:")
    print(f"  편집 결정: {len(project.edit_decisions)}개")
    print(f"  프로젝트: {project_path}")
    print(f"  FCPXML: {fcpxml_result}")
    if srt_result:
        print(f"  SRT: {srt_result}")


# --- Podcast cut subcommand ---

async def cmd_podcast_cut(args: argparse.Namespace) -> None:
    """Run podcast cut analysis (entertainment-focused editing)."""
    from avid.services.podcast_cut import PodcastCutService
    from avid.export.report import save_report

    service = PodcastCutService()

    audio_path = Path(args.input).resolve()
    srt_path = Path(args.srt).resolve() if args.srt else None
    context_path = Path(args.context).resolve() if args.context else None

    if not audio_path.exists():
        print(f"오류: 오디오 파일을 찾을 수 없습니다: {audio_path}", file=sys.stderr)
        sys.exit(1)
    if srt_path and not srt_path.exists():
        print(f"오류: SRT 파일을 찾을 수 없습니다: {srt_path}", file=sys.stderr)
        sys.exit(1)
    if context_path and not context_path.exists():
        print(f"오류: Context 파일을 찾을 수 없습니다: {context_path}", file=sys.stderr)
        sys.exit(1)

    output_dir = Path(args.output_dir) if args.output_dir else audio_path.parent

    # Determine export mode
    export_mode = "final" if args.final else "review"

    print(f"팟캐스트 편집 시작: {audio_path.name}")
    if srt_path:
        print(f"  SRT: {srt_path.name}")
        print(f"  (자막 생성 건너뜀)")
    else:
        print(f"  chalna로 자막 생성 예정")
    if context_path:
        print(f"  컨텍스트: {context_path.name}")
    print(f"  출력 디렉토리: {output_dir}")
    print(f"  모드: {export_mode} ({'모든 편집 적용' if export_mode == 'final' else '검토용 disabled'})")

    project, outputs = await service.process(
        audio_path=audio_path,
        output_dir=output_dir,
        srt_path=srt_path,
        skip_transcription=bool(srt_path),
        export_mode=export_mode,
        storyline_path=context_path,
        provider=args.provider,
    )

    # Generate report
    report_path = output_dir / f"{audio_path.stem}.report.md"
    save_report(project, report_path, format="markdown")

    print(f"\n완료!")
    print(f"  편집 결정: {len(project.edit_decisions)}개")
    print(f"  출력 파일:")
    for name, path in outputs.items():
        print(f"    - {name}: {path}")
    print(f"    - report: {report_path}")


# --- Eval subcommand ---

async def cmd_eval(args: argparse.Namespace) -> None:
    """Run FCPXML evaluation."""
    evaluator = FCPXMLEvaluator()

    predicted = Path(args.predicted).resolve()
    ground_truth = Path(args.ground_truth).resolve()

    if not predicted.exists():
        print(f"오류: 예측 FCPXML을 찾을 수 없습니다: {predicted}", file=sys.stderr)
        sys.exit(1)
    if not ground_truth.exists():
        print(f"오류: 정답 FCPXML을 찾을 수 없습니다: {ground_truth}", file=sys.stderr)
        sys.exit(1)

    result = evaluator.evaluate(
        predicted_fcpxml=predicted,
        ground_truth_fcpxml=ground_truth,
        overlap_threshold_ms=args.threshold,
    )

    # Print report
    report = evaluator.format_report(result)
    print(report)

    # Optionally save JSON
    if args.output:
        output_path = Path(args.output)
        data = {
            "predicted": str(predicted),
            "ground_truth": str(ground_truth),
            "total_gt_cuts": result.total_gt_cuts,
            "total_pred_cuts": result.total_pred_cuts,
            "matched_cuts": result.matched_cuts,
            "missed_cuts": result.missed_cuts,
            "extra_cuts": result.extra_cuts,
            "precision": result.precision,
            "recall": result.recall,
            "f1": result.f1,
            "gt_cut_duration_ms": result.gt_cut_duration_ms,
            "pred_cut_duration_ms": result.pred_cut_duration_ms,
            "overlap_duration_ms": result.overlap_duration_ms,
            "timeline_overlap_ratio": result.timeline_overlap_ratio,
        }
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"\n결과 저장: {output_path}")


# --- Main CLI ---

def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="avid-cli",
        description="AVID - 자동 영상 편집 CLI",
    )
    subparsers = parser.add_subparsers(dest="command", help="사용 가능한 명령")

    # --- transcribe ---
    p_transcribe = subparsers.add_parser("transcribe", help="음성 인식 (Chalna API)")
    p_transcribe.add_argument("input", type=str, help="입력 영상/오디오 파일")
    p_transcribe.add_argument("-l", "--language", default="ko", help="언어 (기본: ko)")
    p_transcribe.add_argument("--chalna-url", type=str, help="Chalna API URL (기본: CHALNA_API_URL 환경변수 또는 http://localhost:7861)")
    p_transcribe.add_argument("-d", "--output-dir", type=str, help="출력 디렉토리")

    # --- transcript-overview ---
    p_overview = subparsers.add_parser("transcript-overview", help="스토리 구조 분석 (Pass 1)")
    p_overview.add_argument("input", type=str, help="입력 SRT 자막 파일")
    p_overview.add_argument("-o", "--output", type=str, help="출력 storyline JSON 경로")
    p_overview.add_argument("--content-type", choices=["lecture", "podcast", "auto"], default="auto", help="콘텐츠 유형 (기본: auto)")
    p_overview.add_argument("--provider", choices=["claude", "codex"], default="codex", help="AI 프로바이더 (기본: codex)")

    # --- subtitle-cut ---
    p_subcut = subparsers.add_parser("subtitle-cut", help="자막 기반 컷 편집")
    p_subcut.add_argument("input", type=str, help="입력 영상 파일")
    p_subcut.add_argument("--srt", type=str, required=True, help="SRT 자막 파일 (필수)")
    p_subcut.add_argument("--context", type=str, help="storyline.json 경로 (Pass 1 결과)")
    p_subcut.add_argument("--provider", choices=["claude", "codex"], default="codex", help="AI 프로바이더 (기본: codex)")
    p_subcut.add_argument("-o", "--output", type=str, help="출력 FCPXML 경로")
    p_subcut.add_argument("-d", "--output-dir", type=str, help="출력 디렉토리")
    p_subcut.add_argument("--final", action="store_true", help="최종 편집본 (모든 편집 적용, 기본: 검토용 disabled)")

    # --- podcast-cut ---
    p_podcast = subparsers.add_parser("podcast-cut", help="팟캐스트 편집 (재미 기준)")
    p_podcast.add_argument("input", type=str, help="입력 오디오/영상 파일")
    p_podcast.add_argument("--srt", type=str, help="SRT 자막 파일 (없으면 chalna로 생성)")
    p_podcast.add_argument("--context", type=str, help="storyline.json 경로 (Pass 1 결과)")
    p_podcast.add_argument("--provider", choices=["claude", "codex"], default="codex", help="AI 프로바이더 (기본: codex)")
    p_podcast.add_argument("-d", "--output-dir", type=str, help="출력 디렉토리")
    p_podcast.add_argument("--final", action="store_true", help="최종 편집본 (모든 편집 적용, 기본: 검토용 disabled)")

    # --- eval ---
    p_eval = subparsers.add_parser("eval", help="FCPXML 평가 (편집 결과 비교)")
    p_eval.add_argument("predicted", type=str, help="예측 FCPXML (자동 생성)")
    p_eval.add_argument("ground_truth", type=str, help="정답 FCPXML (사람 편집)")
    p_eval.add_argument("--threshold", type=int, default=200, help="매칭 임계값 ms (기본: 200)")
    p_eval.add_argument("-o", "--output", type=str, help="결과 JSON 저장 경로")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Dispatch
    if args.command == "transcribe":
        asyncio.run(cmd_transcribe(args))
    elif args.command == "transcript-overview":
        asyncio.run(cmd_transcript_overview(args))
    elif args.command == "subtitle-cut":
        asyncio.run(cmd_subtitle_cut(args))
    elif args.command == "podcast-cut":
        asyncio.run(cmd_podcast_cut(args))
    elif args.command == "eval":
        asyncio.run(cmd_eval(args))


if __name__ == "__main__":
    main()
