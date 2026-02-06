"""AVID command-line interface with subcommands.

Usage:
    avid-cli transcribe <video> [-l ko] [-m base] [-o output.srt]
    avid-cli silence <video> [--srt sub.srt] [-o output.fcpxml]
    avid-cli transcript-overview <srt> [-o storyline.json] [--content-type auto]
    avid-cli subtitle-cut <video> --srt sub.srt [--context storyline.json] [-o output.fcpxml]
    avid-cli podcast-cut <audio> [--srt sub.srt] [--context storyline.json] [-d output_dir]
    avid-cli eval <predicted.fcpxml> <ground-truth.fcpxml>
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from avid.export.fcpxml import FCPXMLExporter
from avid.models.project import Project
from avid.services.evaluation import FCPXMLEvaluator


# --- Transcribe subcommand ---

async def cmd_transcribe(args: argparse.Namespace) -> None:
    """Run transcription."""
    from avid.services.transcription import TranscriptionService

    service = TranscriptionService()
    if not service.is_available():
        print("오류: whisper CLI가 설치되어 있지 않습니다.", file=sys.stderr)
        print("설치: pip install openai-whisper", file=sys.stderr)
        sys.exit(1)

    video_path = Path(args.input).resolve()
    if not video_path.exists():
        print(f"오류: 파일을 찾을 수 없습니다: {video_path}", file=sys.stderr)
        sys.exit(1)

    output_dir = Path(args.output_dir) if args.output_dir else video_path.parent

    print(f"음성 인식 시작: {video_path.name}")
    print(f"  언어: {args.language}")
    print(f"  모델: {args.model}")

    srt_path = await service.transcribe(
        input_path=video_path,
        language=args.language,
        model=args.model,
        output_dir=output_dir,
    )

    print(f"\n완료: {srt_path}")


# --- Silence detection subcommand ---

async def cmd_silence(args: argparse.Namespace) -> None:
    """Run silence detection."""
    from avid.services.silence import SilenceDetectionService

    service = SilenceDetectionService()
    video_path = Path(args.input).resolve()

    if not video_path.exists():
        print(f"오류: 파일을 찾을 수 없습니다: {video_path}", file=sys.stderr)
        sys.exit(1)

    srt_path = Path(args.srt).resolve() if args.srt else None
    output_dir = Path(args.output_dir) if args.output_dir else video_path.parent

    print(f"무음 감지 시작: {video_path.name}")
    if srt_path:
        print(f"  SRT: {srt_path.name}")
    print(f"  모드: {args.mode}")
    print(f"  템포: {args.tempo}")

    project, project_path = await service.detect(
        video_path=video_path,
        srt_path=srt_path,
        output_dir=output_dir,
        mode=args.mode,
        tempo=args.tempo,
        min_duration_ms=args.min_duration,
        threshold_db=args.threshold,
        padding_ms=args.padding,
    )

    # Export to FCPXML
    fcpxml_path = Path(args.output) if args.output else output_dir / f"{video_path.stem}_silence.fcpxml"
    exporter = FCPXMLExporter()
    await exporter.export(project, fcpxml_path)

    print(f"\n결과:")
    print(f"  편집 결정: {len(project.edit_decisions)}개 컷")
    print(f"  프로젝트: {project_path}")
    print(f"  FCPXML: {fcpxml_path}")


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

    storyline_path = await service.analyze(
        srt_path=srt_path,
        output_path=output_path,
        content_type=args.content_type,
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

    print(f"자막 분석 시작: {srt_path.name}")
    print(f"  비디오: {video_path.name}")
    if context_path:
        print(f"  컨텍스트: {context_path.name}")

    project, project_path = await service.analyze(
        srt_path=srt_path,
        video_path=video_path,
        output_dir=output_dir,
        storyline_path=context_path,
    )

    # Export to FCPXML
    fcpxml_path = Path(args.output) if args.output else output_dir / f"{srt_path.stem}_subtitle_cut.fcpxml"
    exporter = FCPXMLExporter()
    await exporter.export(project, fcpxml_path)

    print(f"\n결과:")
    print(f"  편집 결정: {len(project.edit_decisions)}개 컷")
    print(f"  프로젝트: {project_path}")
    print(f"  FCPXML: {fcpxml_path}")


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
    p_transcribe = subparsers.add_parser("transcribe", help="음성 인식 (Whisper)")
    p_transcribe.add_argument("input", type=str, help="입력 영상/오디오 파일")
    p_transcribe.add_argument("-l", "--language", default="ko", help="언어 (기본: ko)")
    p_transcribe.add_argument("-m", "--model", default="base", help="Whisper 모델 (기본: base)")
    p_transcribe.add_argument("-d", "--output-dir", type=str, help="출력 디렉토리")

    # --- silence ---
    p_silence = subparsers.add_parser("silence", help="무음 감지")
    p_silence.add_argument("input", type=str, help="입력 영상/오디오 파일")
    p_silence.add_argument("--srt", type=str, help="SRT 자막 파일 (선택)")
    p_silence.add_argument("--mode", default="or", choices=["or", "and", "ffmpeg", "srt", "diff"], help="감지 모드 (기본: or)")
    p_silence.add_argument("--tempo", type=str, default="tight", choices=["relaxed", "normal", "tight"], help="템포 프리셋")
    p_silence.add_argument("--min-duration", type=int, default=500, help="최소 무음 길이 ms (기본: 500)")
    p_silence.add_argument("--threshold", type=float, default=None, help="무음 임계값 dB")
    p_silence.add_argument("--padding", type=int, default=100, help="패딩 ms (기본: 100)")
    p_silence.add_argument("-o", "--output", type=str, help="출력 FCPXML 경로")
    p_silence.add_argument("-d", "--output-dir", type=str, help="출력 디렉토리")

    # --- transcript-overview ---
    p_overview = subparsers.add_parser("transcript-overview", help="스토리 구조 분석 (Pass 1)")
    p_overview.add_argument("input", type=str, help="입력 SRT 자막 파일")
    p_overview.add_argument("-o", "--output", type=str, help="출력 storyline JSON 경로")
    p_overview.add_argument("--content-type", choices=["lecture", "podcast", "auto"], default="auto", help="콘텐츠 유형 (기본: auto)")

    # --- subtitle-cut ---
    p_subcut = subparsers.add_parser("subtitle-cut", help="자막 기반 컷 편집")
    p_subcut.add_argument("input", type=str, help="입력 영상 파일")
    p_subcut.add_argument("--srt", type=str, required=True, help="SRT 자막 파일 (필수)")
    p_subcut.add_argument("--context", type=str, help="storyline.json 경로 (Pass 1 결과)")
    p_subcut.add_argument("-o", "--output", type=str, help="출력 FCPXML 경로")
    p_subcut.add_argument("-d", "--output-dir", type=str, help="출력 디렉토리")

    # --- podcast-cut ---
    p_podcast = subparsers.add_parser("podcast-cut", help="팟캐스트 편집 (재미 기준)")
    p_podcast.add_argument("input", type=str, help="입력 오디오/영상 파일")
    p_podcast.add_argument("--srt", type=str, help="SRT 자막 파일 (없으면 chalna로 생성)")
    p_podcast.add_argument("--context", type=str, help="storyline.json 경로 (Pass 1 결과)")
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
    elif args.command == "silence":
        asyncio.run(cmd_silence(args))
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
