"""AVID command-line interface with subcommands.

Usage:
    avid-cli transcribe <video> [-l ko] [-m base] [-o output.srt]
    avid-cli silence <video> [--srt sub.srt] [-o output.fcpxml]
    avid-cli subtitle-cut <video> --srt sub.srt [-o output.fcpxml]
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
    print(f"  tight: {args.tight}")

    project, project_path = await service.detect(
        video_path=video_path,
        srt_path=srt_path,
        output_dir=output_dir,
        mode=args.mode,
        tight=args.tight,
        min_silence_ms=args.min_silence,
        noise_db=args.noise,
    )

    # Export to FCPXML
    fcpxml_path = Path(args.output) if args.output else output_dir / f"{video_path.stem}_silence.fcpxml"
    exporter = FCPXMLExporter()
    await exporter.export(project, fcpxml_path)

    print(f"\n결과:")
    print(f"  편집 결정: {len(project.edit_decisions)}개 컷")
    print(f"  프로젝트: {project_path}")
    print(f"  FCPXML: {fcpxml_path}")


# --- Subtitle cut subcommand ---

async def cmd_subtitle_cut(args: argparse.Namespace) -> None:
    """Run subtitle cut analysis."""
    from avid.services.subtitle_cut import SubtitleCutService

    service = SubtitleCutService()

    video_path = Path(args.input).resolve()
    srt_path = Path(args.srt).resolve()

    if not video_path.exists():
        print(f"오류: 비디오 파일을 찾을 수 없습니다: {video_path}", file=sys.stderr)
        sys.exit(1)
    if not srt_path.exists():
        print(f"오류: SRT 파일을 찾을 수 없습니다: {srt_path}", file=sys.stderr)
        sys.exit(1)

    output_dir = Path(args.output_dir) if args.output_dir else video_path.parent

    print(f"자막 분석 시작: {srt_path.name}")
    print(f"  비디오: {video_path.name}")

    project, project_path = await service.analyze(
        srt_path=srt_path,
        video_path=video_path,
        output_dir=output_dir,
    )

    # Export to FCPXML
    fcpxml_path = Path(args.output) if args.output else output_dir / f"{srt_path.stem}_subtitle_cut.fcpxml"
    exporter = FCPXMLExporter()
    await exporter.export(project, fcpxml_path)

    print(f"\n결과:")
    print(f"  편집 결정: {len(project.edit_decisions)}개 컷")
    print(f"  프로젝트: {project_path}")
    print(f"  FCPXML: {fcpxml_path}")


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
    p_silence.add_argument("--mode", default="or", choices=["or", "and", "ffmpeg_only", "srt_only"], help="결합 모드 (기본: or)")
    p_silence.add_argument("--tight", action="store_true", default=True, help="tight 모드 (기본: 활성)")
    p_silence.add_argument("--no-tight", dest="tight", action="store_false", help="tight 모드 비활성")
    p_silence.add_argument("--min-silence", type=int, default=500, help="최소 무음 길이 ms (기본: 500)")
    p_silence.add_argument("--noise", type=float, default=-40.0, help="노이즈 임계값 dB (기본: -40)")
    p_silence.add_argument("-o", "--output", type=str, help="출력 FCPXML 경로")
    p_silence.add_argument("-d", "--output-dir", type=str, help="출력 디렉토리")

    # --- subtitle-cut ---
    p_subcut = subparsers.add_parser("subtitle-cut", help="자막 기반 컷 편집")
    p_subcut.add_argument("input", type=str, help="입력 영상 파일")
    p_subcut.add_argument("--srt", type=str, required=True, help="SRT 자막 파일 (필수)")
    p_subcut.add_argument("-o", "--output", type=str, help="출력 FCPXML 경로")
    p_subcut.add_argument("-d", "--output-dir", type=str, help="출력 디렉토리")

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
    elif args.command == "subtitle-cut":
        asyncio.run(cmd_subtitle_cut(args))
    elif args.command == "eval":
        asyncio.run(cmd_eval(args))


if __name__ == "__main__":
    main()
