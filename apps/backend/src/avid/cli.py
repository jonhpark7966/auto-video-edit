"""AVID command-line interface with subcommands.

Usage:
    avid-cli transcribe <video> [-l ko] [--chalna-url URL]
    avid-cli transcript-overview <srt> [-o storyline.json] [--provider codex] [--content-type auto]
    avid-cli subtitle-cut <video> --srt sub.srt [--provider codex] [--context storyline.json] [-o output.fcpxml]
    avid-cli podcast-cut <audio> [--srt sub.srt] [--provider codex]
        [--prompt-profile podcast] [--context storyline.json] [-d output_dir]
    avid-cli review-segments --project-json project.avid.json
    avid-cli apply-evaluation --project-json project.avid.json --evaluation evaluation.json --output-project-json out.avid.json
    avid-cli reexport --project-json project.avid.json --output-dir out
    avid-cli create-proxy <input> --output output_360p.mp4 --mode preserve-timecode-proxy
"""

import argparse
import asyncio
import contextlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from avid import __version__
from avid.export.fcpxml import FCPXMLExporter
from avid.provider_runtime import probe_provider, provider_config_payload, resolve_provider_config


_VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".flv", ".wmv"}
MAX_REVIEW_GAP_PADDING_MS = 500


def _backend_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _git_revision() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(_backend_root()),
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return None

    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _base_payload(command: str) -> dict[str, Any]:
    git_revision = _git_revision()
    return {
        "command": command,
        "status": "ok",
        "avid_version": git_revision or __version__,
        "package_version": __version__,
        "git_revision": git_revision,
    }


def _payload(command: str, *, artifacts: dict[str, Any] | None = None, stats: dict[str, Any] | None = None, **extra: Any) -> dict[str, Any]:
    payload = _base_payload(command)
    if artifacts is not None:
        payload["artifacts"] = artifacts
    if stats is not None:
        payload["stats"] = stats
    payload.update(extra)
    return payload


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _provider_config_payload(provider: str, model: str | None = None, effort: str | None = None) -> dict[str, Any]:
    return provider_config_payload(resolve_provider_config(provider, model=model, effort=effort))


def _write_machine_output(args: argparse.Namespace, payload: dict[str, Any]) -> None:
    if getattr(args, "manifest_out", None):
        manifest_path = Path(args.manifest_out).resolve()
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default),
            encoding="utf-8",
        )

    if getattr(args, "json", False):
        print(json.dumps(payload, ensure_ascii=False, default=_json_default))


def _sync_result_payload(result: Any) -> dict[str, Any]:
    return {
        "source_name": getattr(result, "source_name", None),
        "offset_ms": result.offset_ms,
        "confidence": result.confidence,
        "method": result.method,
        "standard_score": result.standard_score,
        "retime_speed": getattr(result, "retime_speed", None),
        "diagnostics": getattr(result, "diagnostics", {}),
    }


def _write_sync_diagnostics(
    output_dir: Path,
    base_name: str,
    sync_results: list[Any],
) -> Path | None:
    if not sync_results:
        return None

    payload = {
        "status": "ok",
        "sources": [_sync_result_payload(result) for result in sync_results],
        "warnings": [
            warning
            for result in sync_results
            for warning in getattr(result, "diagnostics", {}).get("warnings", [])
        ],
    }
    diagnostics_path = output_dir / f"{base_name}.sync_diagnostics.json"
    diagnostics_path.parent.mkdir(parents=True, exist_ok=True)
    diagnostics_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default),
        encoding="utf-8",
    )
    return diagnostics_path


def _run_handler(args: argparse.Namespace, handler, *, is_async: bool) -> dict[str, Any]:
    redirect_stdout = getattr(args, "json", False)

    if is_async:
        if redirect_stdout:
            with contextlib.redirect_stdout(sys.stderr):
                return asyncio.run(handler(args))
        return asyncio.run(handler(args))

    if redirect_stdout:
        with contextlib.redirect_stdout(sys.stderr):
            return handler(args)
    return handler(args)


def _add_machine_output_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="stdout에 machine-readable JSON 출력")
    parser.add_argument("--manifest-out", type=str, help="지정 경로에 JSON manifest 저장")


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
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg 오디오 추출 실패:\n{result.stderr[-1000:]}")
    return wav_path


async def cmd_transcribe(args: argparse.Namespace) -> dict[str, Any]:
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
    service = ChalnaTranscriptionService(base_url=chalna_url, timeout=3.0)

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

    context = args.context if hasattr(args, "context") and args.context else None
    if context:
        print(f"  컨텍스트: {context[:80]}...")

    try:
        result = await service.transcribe_async(
            audio_path=audio_path,
            language=args.language,
            use_llm_refinement=args.llm_refine,
            context=context,
            progress_callback=progress_cb,
        )
    finally:
        if temp_audio and temp_audio.exists():
            temp_audio.unlink()
    print()  # newline after progress bar

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

    return _payload(
        "transcribe",
        artifacts={"srt": str(srt_path)},
        stats={
            "segments": len(result.segments),
            "language": args.language,
        },
    )


def _ms_to_srt_time(ms: int) -> str:
    """Format milliseconds as SRT timestamp."""
    hours = ms // 3600000
    ms %= 3600000
    minutes = ms // 60000
    ms %= 60000
    seconds = ms // 1000
    millis = ms % 1000
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


async def cmd_transcript_overview(args: argparse.Namespace) -> dict[str, Any]:
    """Run transcript overview analysis (Pass 1)."""
    from avid.services.transcript_overview import TranscriptOverviewService

    service = TranscriptOverviewService()
    provider_config = _provider_config_payload(
        args.provider,
        args.provider_model,
        args.provider_effort,
    )

    srt_path = Path(args.input).resolve()
    if not srt_path.exists():
        print(f"오류: SRT 파일을 찾을 수 없습니다: {srt_path}", file=sys.stderr)
        sys.exit(1)

    output_path = Path(args.output).resolve() if args.output else None

    print(f"스토리 구조 분석 시작: {srt_path.name}")
    print(f"  콘텐츠 유형: {args.content_type}")
    print(f"  프로바이더: {provider_config['provider']}")
    print(f"  모델: {provider_config['model']}")
    print(f"  effort: {provider_config['effort']}")

    storyline_path = await service.analyze(
        srt_path=srt_path,
        output_path=output_path,
        content_type=args.content_type,
        provider=args.provider,
        provider_model=args.provider_model,
        provider_effort=args.provider_effort,
    )

    storyline = service.load_storyline(storyline_path)
    chapters = storyline.get("chapters", [])
    deps = storyline.get("dependencies", [])
    kms = storyline.get("key_moments", [])

    print(f"\n완료!")
    print(f"  챕터: {len(chapters)}개")
    print(f"  의존성: {len(deps)}개")
    print(f"  핵심 순간: {len(kms)}개")
    print(f"  출력: {storyline_path}")

    return _payload(
        "transcript-overview",
        artifacts={"storyline": str(storyline_path)},
        stats={
            "chapters": len(chapters),
            "dependencies": len(deps),
            "key_moments": len(kms),
        },
        provider_config=provider_config,
    )


def _parse_extra_sources(args: argparse.Namespace) -> tuple[list[Path] | None, dict[str, int] | None]:
    """Parse --extra-source and --offset args into service-ready parameters."""
    extra_sources_raw: list[str] = getattr(args, "extra_source", [])
    offsets_raw: list[str] = getattr(args, "offset", [])

    if not extra_sources_raw:
        return None, None

    extra_sources = [Path(p).resolve() for p in extra_sources_raw]

    for p in extra_sources:
        if not p.exists():
            print(f"오류: 추가 소스 파일을 찾을 수 없습니다: {p}", file=sys.stderr)
            sys.exit(1)

    extra_offsets: dict[str, int] | None = None
    if offsets_raw:
        extra_offsets = {}
        for i, offset_str in enumerate(offsets_raw):
            if i >= len(extra_sources):
                break
            extra_offsets[extra_sources[i].name] = int(offset_str)

    return extra_sources, extra_offsets


async def cmd_subtitle_cut(args: argparse.Namespace) -> dict[str, Any]:
    """Run subtitle cut analysis."""
    from avid.export.report import save_report
    from avid.services.subtitle_cut import SubtitleCutService

    service = SubtitleCutService()
    provider_config = _provider_config_payload(
        args.provider,
        args.provider_model,
        args.provider_effort,
    )

    video_path = Path(args.input).resolve()
    srt_path = Path(args.srt).resolve()
    context_path = Path(args.context).resolve() if args.context else None
    segments_json_path = Path(args.segments_json).resolve() if args.segments_json else None

    if not video_path.exists():
        print(f"오류: 비디오 파일을 찾을 수 없습니다: {video_path}", file=sys.stderr)
        sys.exit(1)
    if not srt_path.exists():
        print(f"오류: SRT 파일을 찾을 수 없습니다: {srt_path}", file=sys.stderr)
        sys.exit(1)
    if context_path and not context_path.exists():
        print(f"오류: Context 파일을 찾을 수 없습니다: {context_path}", file=sys.stderr)
        sys.exit(1)
    if segments_json_path and not segments_json_path.exists():
        print(f"오류: Segments JSON 파일을 찾을 수 없습니다: {segments_json_path}", file=sys.stderr)
        sys.exit(1)

    output_dir = Path(args.output_dir) if args.output_dir else video_path.parent
    export_mode = "final" if args.final else "review"
    extra_sources, extra_offsets = _parse_extra_sources(args)

    print(f"자막 분석 시작: {srt_path.name}")
    print(f"  비디오: {video_path.name}")
    print(f"  프로바이더: {provider_config['provider']}")
    print(f"  모델: {provider_config['model']}")
    print(f"  effort: {provider_config['effort']}")
    print(f"  모드: {export_mode} ({'모든 편집 적용' if export_mode == 'final' else '검토용 disabled'})")
    if context_path:
        print(f"  컨텍스트: {context_path.name}")
    if segments_json_path:
        print(f"  Segments JSON: {segments_json_path.name}")
    if extra_sources:
        print(f"  추가 소스: {len(extra_sources)}개")
    print(f"  편집 강도: {args.edit_intensity}")
    print(f"  Edit decision version: {args.edit_decision_version}")
    print(f"  Segmentation boundary rule: {args.segmentation_boundary_rule}")

    project, project_path, sync_results = await service.analyze(
        srt_path=srt_path,
        video_path=video_path,
        output_dir=output_dir,
        storyline_path=context_path,
        provider=args.provider,
        provider_model=args.provider_model,
        provider_effort=args.provider_effort,
        extra_sources=extra_sources,
        extra_offsets=extra_offsets,
        edit_intensity=args.edit_intensity,
        edit_decision_version=args.edit_decision_version,
        segmentation_boundary_rule=args.segmentation_boundary_rule,
        segments_json_path=segments_json_path,
        junction_audit_enabled=args.junction_audit,
    )

    fcpxml_path = Path(args.output).resolve() if args.output else output_dir / f"{srt_path.stem}_subtitle_cut.fcpxml"
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

    report_path = output_dir / f"{video_path.stem}.report.md"
    save_report(project, report_path, format="markdown")

    print(f"\n결과:")
    print(f"  편집 결정: {len(project.edit_decisions)}개")
    print(f"  프로젝트: {project_path}")
    print(f"  FCPXML: {fcpxml_result}")
    if srt_result:
        print(f"  SRT: {srt_result}")
    print(f"  report: {report_path}")

    artifacts: dict[str, str] = {
        "project_json": str(project_path),
        "fcpxml": str(fcpxml_result),
        "report": str(report_path),
    }
    junction_audit_path = project_path.with_name(
        f"{project_path.stem}.junction_audit.json"
    )
    if junction_audit_path.exists():
        artifacts["junction_audit"] = str(junction_audit_path)
    if srt_result:
        artifacts["srt"] = str(srt_result)
    diagnostics_path = _write_sync_diagnostics(output_dir, video_path.stem, sync_results)
    if diagnostics_path is not None:
        artifacts["sync_diagnostics"] = str(diagnostics_path)

    return _payload(
        "subtitle-cut",
        artifacts=artifacts,
        stats={
            "edit_decisions": len(project.edit_decisions),
            "extra_sources": len(sync_results),
            "edit_decision_version": args.edit_decision_version,
            "junction_audit": project.junction_audit,
        },
        provider_config=provider_config,
    )


async def cmd_podcast_cut(args: argparse.Namespace) -> dict[str, Any]:
    """Run podcast cut analysis (entertainment-focused editing)."""
    from avid.export.report import save_report
    from avid.services.podcast_cut import PodcastCutService

    service = PodcastCutService()
    provider_config = _provider_config_payload(
        args.provider,
        args.provider_model,
        args.provider_effort,
    )

    audio_path = Path(args.input).resolve()
    srt_path = Path(args.srt).resolve() if args.srt else None
    context_path = Path(args.context).resolve() if args.context else None
    segments_json_path = Path(args.segments_json).resolve() if args.segments_json else None

    if not audio_path.exists():
        print(f"오류: 오디오 파일을 찾을 수 없습니다: {audio_path}", file=sys.stderr)
        sys.exit(1)
    if srt_path and not srt_path.exists():
        print(f"오류: SRT 파일을 찾을 수 없습니다: {srt_path}", file=sys.stderr)
        sys.exit(1)
    if context_path and not context_path.exists():
        print(f"오류: Context 파일을 찾을 수 없습니다: {context_path}", file=sys.stderr)
        sys.exit(1)
    if segments_json_path and not segments_json_path.exists():
        print(f"오류: Segments JSON 파일을 찾을 수 없습니다: {segments_json_path}", file=sys.stderr)
        sys.exit(1)

    output_dir = Path(args.output_dir) if args.output_dir else audio_path.parent
    export_mode = "final" if args.final else "review"
    extra_sources, extra_offsets = _parse_extra_sources(args)

    print(f"팟캐스트 편집 시작: {audio_path.name}")
    print(f"  프로바이더: {provider_config['provider']}")
    print(f"  모델: {provider_config['model']}")
    print(f"  effort: {provider_config['effort']}")
    print(f"  프롬프트 프로필: {args.prompt_profile}")
    if srt_path:
        print(f"  SRT: {srt_path.name}")
        print(f"  (자막 생성 건너뜀)")
    else:
        print(f"  chalna로 자막 생성 예정")
    if context_path:
        print(f"  컨텍스트: {context_path.name}")
    if segments_json_path:
        print(f"  Segments JSON: {segments_json_path.name}")
    if extra_sources:
        print(f"  추가 소스: {len(extra_sources)}개")
    print(f"  편집 강도: {args.edit_intensity}")
    print(f"  Edit decision version: {args.edit_decision_version}")
    print(f"  Segmentation boundary rule: {args.segmentation_boundary_rule}")
    print(f"  출력 디렉토리: {output_dir}")
    print(f"  모드: {export_mode} ({'모든 편집 적용' if export_mode == 'final' else '검토용 disabled'})")

    project, outputs, sync_results = await service.process(
        audio_path=audio_path,
        output_dir=output_dir,
        srt_path=srt_path,
        skip_transcription=bool(srt_path),
        export_mode=export_mode,
        storyline_path=context_path,
        provider=args.provider,
        provider_model=args.provider_model,
        provider_effort=args.provider_effort,
        prompt_profile=args.prompt_profile,
        extra_sources=extra_sources,
        extra_offsets=extra_offsets,
        edit_intensity=args.edit_intensity,
        edit_decision_version=args.edit_decision_version,
        segmentation_boundary_rule=args.segmentation_boundary_rule,
        segments_json_path=segments_json_path,
        junction_audit_enabled=args.junction_audit,
    )

    report_path = output_dir / f"{audio_path.stem}.report.md"
    save_report(project, report_path, format="markdown")

    print(f"\n완료!")
    print(f"  편집 결정: {len(project.edit_decisions)}개")
    print(f"  출력 파일:")
    for name, path in outputs.items():
        print(f"    - {name}: {path}")
    print(f"    - report: {report_path}")

    adjusted_srt = outputs.get("srt_adjusted")
    raw_srt = outputs.get("srt_raw")
    artifacts: dict[str, str] = {
        "project_json": str(outputs["project"]),
        "fcpxml": str(outputs["fcpxml"]),
        "report": str(report_path),
    }
    if adjusted_srt:
        artifacts["srt"] = str(adjusted_srt)
    elif srt_path:
        artifacts["srt"] = str(srt_path)
    if raw_srt:
        artifacts["srt_raw"] = str(raw_srt)
    if outputs.get("junction_audit"):
        artifacts["junction_audit"] = str(outputs["junction_audit"])
    diagnostics_path = _write_sync_diagnostics(output_dir, audio_path.stem, sync_results)
    if diagnostics_path is not None:
        artifacts["sync_diagnostics"] = str(diagnostics_path)

    return _payload(
        "podcast-cut",
        artifacts=artifacts,
        stats={
            "edit_decisions": len(project.edit_decisions),
            "extra_sources": len(sync_results),
            "edit_decision_version": args.edit_decision_version,
            "junction_audit": project.junction_audit,
        },
        provider_config=provider_config,
    )


def _load_evaluation_segments(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        segments = data.get("segments", [])
        if isinstance(segments, list):
            return segments
        raise RuntimeError("evaluation JSON must contain a list at 'segments'")
    if isinstance(data, list):
        return data
    raise RuntimeError("evaluation JSON must be a list or an object with 'segments'")


def _project_supports_index_patch(project: Any) -> bool:
    reviewable_decisions = [
        decision
        for decision in project.edit_decisions
        if decision.reason.value != "silence"
    ]
    return all(decision.source_segment_index is not None for decision in reviewable_decisions)


def _transcription_segment_lookup(project: Any) -> dict[int, Any]:
    if not project.transcription or not project.transcription.segments:
        return {}
    return {
        _segment_identity(segment, position): segment
        for position, segment in enumerate(project.transcription.segments)
    }


def _valid_segment_time(seg: dict[str, Any], fallback: Any | None = None) -> tuple[int, int] | None:
    start = seg.get("start_ms")
    end = seg.get("end_ms")
    if start is None and fallback is not None:
        start = fallback.start_ms
    if end is None and fallback is not None:
        end = fallback.end_ms
    try:
        start_ms = int(start)
        end_ms = int(end)
    except (TypeError, ValueError):
        return None
    if end_ms <= start_ms:
        return None
    return start_ms, end_ms


def _merged_ranges(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted((s, e) for s, e in ranges if e > s):
        if not merged or start > merged[-1][1]:
            merged.append((start, end))
            continue
        merged[-1] = (merged[-1][0], max(merged[-1][1], end))
    return merged


def _subtract_ranges(
    start_ms: int,
    end_ms: int,
    protected_ranges: list[tuple[int, int]],
) -> list[tuple[int, int]]:
    pieces: list[tuple[int, int]] = []
    cursor = start_ms
    for protected_start, protected_end in protected_ranges:
        if protected_end <= cursor:
            continue
        if protected_start >= end_ms:
            break
        if protected_start > cursor:
            pieces.append((cursor, min(protected_start, end_ms)))
        cursor = max(cursor, protected_end)
        if cursor >= end_ms:
            break
    if cursor < end_ms:
        pieces.append((cursor, end_ms))
    return pieces


def _edit_reason_from_value(value: Any, fallback: Any):
    from avid.models.timeline import EditReason

    try:
        return EditReason(value)
    except Exception:
        return fallback


def _edit_type_from_value(value: Any, fallback: Any):
    from avid.models.timeline import EditType

    try:
        return EditType(value)
    except Exception:
        return fallback


def _origin_kind_from_value(value: Any, fallback: Any):
    from avid.models.timeline import EditOriginKind

    try:
        return EditOriginKind(value)
    except Exception:
        return fallback


def _effective_ai_decision(ai: dict[str, Any]) -> dict[str, Any]:
    effective = dict(ai)
    repair = effective.get("junction_repair")
    if not isinstance(repair, dict):
        return effective

    apply_repair = repair.get("user_apply_junction_repair") is not False
    if apply_repair:
        repaired_to = repair.get("repaired_to")
        if repaired_to in {"keep", "cut"}:
            effective["action"] = repaired_to
        return effective

    original_action = repair.get("original_action") or repair.get("repaired_from")
    if original_action in {"keep", "cut"}:
        effective["action"] = original_action
    if repair.get("original_reason") is not None:
        effective["reason"] = repair.get("original_reason")
    if repair.get("original_note") is not None:
        effective["note"] = repair.get("original_note")
    if repair.get("original_edit_type") is not None:
        effective["edit_type"] = repair.get("original_edit_type")
    if repair.get("original_origin_kind") is not None:
        effective["origin_kind"] = repair.get("original_origin_kind")
    return effective


def _apply_evaluation_index_patch(project: Any, eval_segments: list[dict[str, Any]]) -> tuple[int, int, str]:
    from avid.models.timeline import EditDecision, EditOriginKind, EditReason, EditType, TimeRange

    video_tracks = project.get_video_tracks()
    primary_video_track_id = video_tracks[0].id if video_tracks else None
    audio_tracks = project.get_audio_tracks()
    primary_audio_track_ids: list[str] = []
    if video_tracks:
        primary_source_id = video_tracks[0].source_file_id
        primary_audio_track_ids = [
            t.id for t in audio_tracks if t.source_file_id == primary_source_id
        ]
    elif audio_tracks:
        primary_audio_track_ids = [t.id for t in audio_tracks]

    segment_lookup = _transcription_segment_lookup(project)
    eval_by_index: dict[int, dict[str, Any]] = {}
    protected_ranges: list[tuple[int, int]] = []
    human_override_count = 0
    for seg in eval_segments:
        seg_index = seg.get("index")
        if seg_index is None:
            continue
        try:
            normalized_index = int(seg_index)
        except (TypeError, ValueError):
            continue

        fallback_segment = segment_lookup.get(normalized_index)
        time_range = _valid_segment_time(seg, fallback_segment)
        if time_range is None:
            continue

        eval_by_index[normalized_index] = seg
        protected_ranges.append(time_range)
        human = seg.get("human")
        if human:
            human_override_count += 1

    if not eval_by_index:
        return 0, 0, "source_segment_index"

    original_count = len(project.edit_decisions)
    eval_indices = set(eval_by_index)
    protected_ranges = _merged_ranges(protected_ranges)

    new_decisions = []
    for ed in project.edit_decisions:
        if ed.reason == EditReason.SILENCE:
            remaining_ranges = _subtract_ranges(
                ed.range.start_ms,
                ed.range.end_ms,
                protected_ranges,
            )
            for start_ms, end_ms in remaining_ranges:
                new_decisions.append(ed.model_copy(update={
                    "range": TimeRange(start_ms=start_ms, end_ms=end_ms),
                }))
            continue
        if ed.source_segment_index in eval_indices:
            continue
        new_decisions.append(ed)

    cuts_added = 0
    for seg_index in sorted(eval_by_index):
        seg = eval_by_index[seg_index]
        human = seg.get("human")
        ai = _effective_ai_decision(seg.get("ai") or {})
        action = (human or ai or {}).get("action", "keep")
        if action == "cut":
            segment = segment_lookup.get(seg_index)
            time_range = _valid_segment_time(seg, segment)
            if time_range is None:
                continue
            start_ms, end_ms = time_range
            is_human_override = human is not None
            edit_type = EditType.CUT if is_human_override else _edit_type_from_value(ai.get("edit_type"), EditType.CUT)
            reason = EditReason.MANUAL if is_human_override else _edit_reason_from_value(ai.get("reason"), EditReason.MANUAL)
            origin_kind = (
                EditOriginKind.MANUAL_OVERRIDE
                if is_human_override
                else _origin_kind_from_value(ai.get("origin_kind"), EditOriginKind.CONTENT_SEGMENT)
            )
            confidence = 1.0 if is_human_override else float(ai.get("confidence") or 1.0)
            note = "human evaluation override" if is_human_override else ai.get("note")
            new_decisions.append(EditDecision(
                range=TimeRange(start_ms=start_ms, end_ms=end_ms),
                edit_type=edit_type,
                reason=reason,
                confidence=confidence,
                note=note,
                active_video_track_id=primary_video_track_id,
                active_audio_track_ids=primary_audio_track_ids,
                origin_kind=origin_kind,
                source_segment_index=seg_index,
                boundary=ai.get("boundary") if isinstance(ai.get("boundary"), dict) else None,
                junction_repair=ai.get("junction_repair") if isinstance(ai.get("junction_repair"), dict) else None,
            ))
            cuts_added += 1

    new_decisions.sort(key=lambda ed: ed.range.start_ms)
    project.edit_decisions = new_decisions

    changes = abs(original_count - len(new_decisions)) + cuts_added
    return human_override_count, changes, "source_segment_index"


def _apply_evaluation_overlap_patch(project: Any, eval_segments: list[dict[str, Any]]) -> tuple[int, int, str]:
    from avid.models.timeline import EditDecision, EditOriginKind, EditReason, EditType, TimeRange

    video_tracks = project.get_video_tracks()
    primary_video_track_id = video_tracks[0].id if video_tracks else None
    audio_tracks = project.get_audio_tracks()
    primary_audio_track_ids: list[str] = []
    if video_tracks:
        primary_source_id = video_tracks[0].source_file_id
        primary_audio_track_ids = [
            t.id for t in audio_tracks if t.source_file_id == primary_source_id
        ]
    elif audio_tracks:
        primary_audio_track_ids = [t.id for t in audio_tracks]

    human_overrides = []
    for seg in eval_segments:
        human = seg.get("human")
        if human:
            human_overrides.append((seg["start_ms"], seg["end_ms"], human["action"]))

    if not human_overrides:
        return 0, 0, "legacy_overlap"

    original_count = len(project.edit_decisions)

    new_decisions = []
    for ed in project.edit_decisions:
        ed_start = ed.range.start_ms
        ed_end = ed.range.end_ms

        overlaps_human = False
        for h_start, h_end, _ in human_overrides:
            if ed_start < h_end and ed_end > h_start:
                overlaps_human = True
                break

        if not overlaps_human:
            new_decisions.append(ed)

    cuts_added = 0
    for h_start, h_end, action in human_overrides:
        if action == "cut":
            new_decisions.append(EditDecision(
                range=TimeRange(start_ms=h_start, end_ms=h_end),
                edit_type=EditType.CUT,
                reason=EditReason.MANUAL,
                confidence=1.0,
                note="human evaluation override",
                active_video_track_id=primary_video_track_id,
                active_audio_track_ids=primary_audio_track_ids,
                origin_kind=EditOriginKind.MANUAL_OVERRIDE,
            ))
            cuts_added += 1

    new_decisions.sort(key=lambda ed: ed.range.start_ms)
    project.edit_decisions = new_decisions

    changes = abs(original_count - len(new_decisions)) + cuts_added
    return len(human_overrides), changes, "legacy_overlap"


def _apply_evaluation_to_project(project, eval_segments: list[dict[str, Any]]) -> tuple[int, int, str]:
    if _project_supports_index_patch(project):
        return _apply_evaluation_index_patch(project, eval_segments)
    return _apply_evaluation_overlap_patch(project, eval_segments)


def _apply_evaluation_from_path(project, evaluation_path: Path) -> tuple[int, int, str]:
    if not evaluation_path.exists():
        print(f"오류: evaluation JSON을 찾을 수 없습니다: {evaluation_path}", file=sys.stderr)
        sys.exit(1)

    eval_segments = _load_evaluation_segments(evaluation_path)
    return _apply_evaluation_to_project(project, eval_segments)


def _strip_extra_sources(project) -> int:
    if len(project.source_files) <= 1:
        return 0

    primary_source = project.source_files[0]
    primary_source_id = primary_source.id
    removed = max(0, len(project.source_files) - 1)
    project.source_files = [primary_source]
    project.tracks = [
        track for track in project.tracks
        if track.source_file_id == primary_source_id
    ]
    return removed


async def _refresh_primary_source_media(project, source_path: Path) -> None:
    if not project.source_files:
        return

    from avid.services.media import MediaService

    refreshed_source = await MediaService().create_media_file(source_path)
    primary_source = project.source_files[0]
    primary_source.path = refreshed_source.path
    primary_source.original_name = refreshed_source.original_name
    primary_source.info = refreshed_source.info


async def _rebuild_multicam_in_place(
    project,
    source_path: Path,
    extra_sources: list[Path],
    extra_offsets: dict[str, int] | None = None,
) -> list[Any]:
    from avid.services.audio_sync import AudioSyncService

    sync_service = AudioSyncService()
    await _refresh_primary_source_media(project, source_path)
    return await sync_service.add_extra_sources(
        project,
        source_path,
        extra_sources,
        extra_offsets or {},
    )


def _manifest_media_info(media_info_path: Path):
    from avid.models.media import MediaInfo

    payload = json.loads(media_info_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"media_info must be a JSON object: {media_info_path}")

    media_info = payload.get("media_info", payload)
    if not isinstance(media_info, dict):
        raise ValueError(f"media_info payload missing object: {media_info_path}")
    return MediaInfo(**media_info)


def _manifest_path(value: object, *, field_name: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"source manifest entry missing {field_name}")
    return Path(value).expanduser().resolve()


def _manifest_media_file(entry: dict[str, Any]):
    from avid.models.media import MediaFile

    media_info_path = _manifest_path(entry.get("media_info_path"), field_name="media_info_path")
    media_info = _manifest_media_info(media_info_path)
    original_name = (
        str(entry.get("original_name") or entry.get("filename") or "").strip()
        or Path(str(entry.get("path_hint") or media_info_path.stem)).name
    )
    path_hint_raw = str(entry.get("path_hint") or original_name).strip()
    path_hint = Path(path_hint_raw).expanduser()
    if not path_hint.is_absolute():
        path_hint = path_hint.resolve()

    return MediaFile(
        path=path_hint,
        original_name=original_name,
        info=media_info,
    )


async def _rebuild_multicam_from_manifest_in_place(
    project,
    manifest_path: Path,
) -> list[Any]:
    from avid.models.media import MediaFile
    from avid.services.audio_sync import AudioSyncService, SyncResult

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("source manifest must be a JSON object")

    primary_entry = payload.get("primary")
    extra_entries = payload.get("extras")
    if not isinstance(primary_entry, dict):
        raise ValueError("source manifest missing primary object")
    if not isinstance(extra_entries, list) or not extra_entries:
        raise ValueError("source manifest requires at least one extra source")

    primary_file: MediaFile = _manifest_media_file(primary_entry)
    if project.source_files:
        primary_source = project.source_files[0]
        primary_source.path = primary_file.path
        primary_source.original_name = primary_file.original_name
        primary_source.info = primary_file.info
    else:
        project.add_source_file(primary_file)

    primary_audio_proxy = _manifest_path(primary_entry.get("audio_proxy_path"), field_name="audio_proxy_path")
    sync_service = AudioSyncService()
    results: list[Any] = []

    for index, raw_entry in enumerate(extra_entries):
        if not isinstance(raw_entry, dict):
            raise ValueError(f"source manifest extras[{index}] must be an object")

        extra_file: MediaFile = _manifest_media_file(raw_entry)
        extra_audio_proxy = _manifest_path(raw_entry.get("audio_proxy_path"), field_name="audio_proxy_path")
        offset_value = raw_entry.get("offset_ms")

        if offset_value is None:
            sync_result = await sync_service.find_offset(primary_audio_proxy, extra_audio_proxy)
            sync_result.source_name = extra_file.original_name
        else:
            offset_ms = int(offset_value)
            sync_result = SyncResult(
                offset_ms=offset_ms,
                confidence=1.0,
                method="manual",
                standard_score=0.0,
                source_name=extra_file.original_name,
                diagnostics={
                    "selected_method": "manual",
                    "selected_offset_ms": offset_ms,
                    "manual_override": True,
                    "main_path": str(primary_audio_proxy),
                    "extra_path": str(extra_audio_proxy),
                },
            )
            drift = await sync_service.estimate_drift(primary_audio_proxy, extra_audio_proxy, offset_ms)
            sync_result.diagnostics["drift"] = drift
            if drift and isinstance(drift.get("retime_speed"), (float, int)):
                sync_result.retime_speed = float(drift["retime_speed"])

        created_tracks = project.add_source_file(extra_file)
        for track in created_tracks:
            project.set_track_offset(track.id, sync_result.offset_ms)
            if sync_result.retime_speed is not None:
                track.sync_drift_retime_speed = sync_result.retime_speed
        results.append(sync_result)

    return results


def _load_project_or_exit(project_json_path: str) -> tuple[Path, Any]:
    from avid.models.project import Project

    resolved_path = Path(project_json_path).resolve()
    if not resolved_path.exists():
        print(f"오류: 프로젝트 JSON을 찾을 수 없습니다: {resolved_path}", file=sys.stderr)
        sys.exit(1)

    return resolved_path, Project.load(resolved_path)


def _resolve_export_base_name(project_json_path: Path, project, source_path: Path | None = None) -> str:
    if source_path is not None:
        return source_path.stem
    if project.source_files:
        return Path(project.source_files[0].original_name).stem
    return project_json_path.stem


def _resolve_export_suffix(project_json_path: Path, project) -> str:
    hints = [
        project_json_path.name.lower(),
        project_json_path.stem.lower(),
        getattr(project, "name", "").lower(),
    ]
    if any("podcast" in hint for hint in hints):
        return "podcast_cut"
    return "subtitle_cut"


def _resolve_source_path_or_exit(source_path: str) -> Path:
    resolved_path = Path(source_path).resolve()
    if not resolved_path.exists():
        print(f"오류: 메인 소스 파일을 찾을 수 없습니다: {resolved_path}", file=sys.stderr)
        sys.exit(1)
    return resolved_path


def _segment_identity(segment: Any, position: int) -> int:
    return int(segment.index) if getattr(segment, "index", None) is not None else position + 1


def _review_ai_payload(decision: Any) -> dict[str, Any]:
    action = "cut" if decision.edit_type.value in ("cut", "mute") else "keep"
    return {
        "action": action,
        "reason": decision.reason.value,
        "confidence": decision.confidence,
        "note": decision.note,
        "edit_type": decision.edit_type.value,
        "origin_kind": decision.origin_kind.value if decision.origin_kind else None,
        "source_segment_index": decision.source_segment_index,
        "boundary": decision.boundary,
        "junction_repair": decision.junction_repair,
    }


def _annotation_ai_payload(annotation: Any) -> dict[str, Any] | None:
    if not isinstance(annotation, dict):
        return None
    ai = annotation.get("ai")
    if not isinstance(ai, dict):
        return None
    return dict(ai)


def _select_review_decision(candidates: list[Any]) -> Any | None:
    if not candidates:
        return None

    from avid.models.timeline import EditOriginKind

    origin_priority = {
        EditOriginKind.MANUAL_OVERRIDE: 0,
        EditOriginKind.CONTENT_SEGMENT: 1,
        EditOriginKind.SILENCE_GAP: 2,
        None: 9,
    }
    ranked = sorted(
        candidates,
        key=lambda decision: (
            origin_priority.get(decision.origin_kind, 9),
            decision.range.start_ms,
            decision.range.end_ms,
        ),
    )
    return ranked[0]


def _match_overlap_review_decision(project: Any, seg_start: int, seg_end: int) -> Any | None:
    candidates = []
    for decision in project.edit_decisions:
        if decision.range.start_ms < seg_end and decision.range.end_ms > seg_start:
            candidates.append(decision)
    return _select_review_decision(candidates)


def _adjust_review_segment_boundaries(segments: list[Any]) -> dict[int, tuple[int, int]]:
    valid: list[tuple[int, int, int, int]] = []
    for position, segment in enumerate(segments):
        segment_index = _segment_identity(segment, position)
        try:
            start_ms = int(segment.start_ms)
            end_ms = int(segment.end_ms)
        except (TypeError, ValueError):
            continue
        if end_ms <= start_ms:
            continue
        valid.append((position, segment_index, start_ms, end_ms))

    adjusted: dict[int, tuple[int, int]] = {}
    if not valid:
        return adjusted

    starts = {position: start_ms for position, _, start_ms, _ in valid}
    ends = {position: end_ms for position, _, _, end_ms in valid}

    for current, following in zip(valid, valid[1:]):
        current_position, _, _, current_end = current
        next_position, _, next_start, _ = following
        boundary = (current_end + next_start) // 2
        ends[current_position] = boundary
        starts[next_position] = boundary

    for position, segment_index, raw_start, raw_end in valid:
        start_ms = starts[position]
        end_ms = ends[position]
        if end_ms <= start_ms:
            start_ms = raw_start
            end_ms = raw_end
        adjusted[segment_index] = (start_ms, end_ms)
    return adjusted


def _raw_review_segment_boundaries(segments: list[Any]) -> dict[int, tuple[int, int]]:
    ranges: dict[int, tuple[int, int]] = {}
    for position, segment in enumerate(segments):
        segment_index = _segment_identity(segment, position)
        try:
            start_ms = int(segment.start_ms)
            end_ms = int(segment.end_ms)
        except (TypeError, ValueError):
            continue
        if end_ms > start_ms:
            ranges[segment_index] = (start_ms, end_ms)
    return ranges


def _build_review_segments_payload(project_json_path: Path, project: Any) -> dict[str, Any]:
    if not project.transcription or not project.transcription.segments:
        raise RuntimeError("review-segments requires transcription.segments in project JSON")

    segmentation_boundary_rule = getattr(project, "segmentation_boundary_rule", "word_boundary")
    if segmentation_boundary_rule == "word_boundary":
        adjusted_boundaries = _adjust_review_segment_boundaries(project.transcription.segments)
        boundary_strategy = "midpoint_between_transcript_segments"
    else:
        adjusted_boundaries = _raw_review_segment_boundaries(project.transcription.segments)
        boundary_strategy = "source_transcript_boundaries"
    indexed_decisions: dict[int, list[Any]] = {}
    for decision in project.edit_decisions:
        if decision.source_segment_index is None:
            continue
        indexed_decisions.setdefault(int(decision.source_segment_index), []).append(decision)

    legacy_overlap_fallback = not indexed_decisions
    annotations = getattr(project, "review_decision_annotations", None)
    if not isinstance(annotations, dict):
        annotations = {}
    review_segments = []
    for position, segment in enumerate(project.transcription.segments):
        segment_index = _segment_identity(segment, position)
        start_ms, end_ms = adjusted_boundaries.get(segment_index, (segment.start_ms, segment.end_ms))
        decision = None
        if legacy_overlap_fallback:
            decision = _match_overlap_review_decision(project, segment.start_ms, segment.end_ms)
        else:
            decision = _select_review_decision(indexed_decisions.get(segment_index, []))

        annotation_ai = _annotation_ai_payload(
            annotations.get(str(segment_index)) or annotations.get(segment_index)
        )
        decision_ai = _review_ai_payload(decision) if decision else None
        if annotation_ai and decision_ai:
            repair = annotation_ai.get("junction_repair")
            if isinstance(repair, dict):
                decision_ai["junction_repair"] = repair
        ai_payload = decision_ai or annotation_ai

        review_segment = {
            "index": segment_index,
            "start_ms": start_ms,
            "end_ms": end_ms,
            "raw_start_ms": segment.start_ms,
            "raw_end_ms": segment.end_ms,
            "text": segment.text,
            "speaker": segment.speaker,
            "ai": ai_payload,
            "human": None,
        }
        overlap_protection = getattr(segment, "overlap_protection", None)
        if isinstance(overlap_protection, dict):
            review_segment["overlap_protection"] = overlap_protection
        review_segments.append(review_segment)

    stats = {
        "segments": len(review_segments),
        "indexed_decisions": sum(len(items) for items in indexed_decisions.values()),
        "legacy_overlap_fallback": legacy_overlap_fallback,
        "boundary_strategy": boundary_strategy,
        "segmentation_boundary_rule": segmentation_boundary_rule,
    }
    junction_audit = getattr(project, "junction_audit", None)
    if isinstance(junction_audit, dict):
        stats["junction_audit"] = junction_audit

    return _payload(
        "review-segments",
        stats=stats,
        schema_version="review-segments/v1",
        project_json=str(project_json_path),
        review_scope="content_segments",
        join_strategy="legacy_overlap" if legacy_overlap_fallback else "source_segment_index",
        segments=review_segments,
    )


def cmd_review_segments(args: argparse.Namespace) -> dict[str, Any]:
    project_json_path, project = _load_project_or_exit(args.project_json)
    payload = _build_review_segments_payload(project_json_path, project)
    print(f"리뷰 세그먼트 생성 완료: {payload['stats']['segments']}개")
    return payload



def _load_speaker_source_map(path: str) -> dict[str, str]:
    resolved_path = Path(path).resolve()
    if not resolved_path.exists():
        print(f"오류: speaker source map JSON을 찾을 수 없습니다: {resolved_path}", file=sys.stderr)
        sys.exit(1)

    try:
        data = json.loads(resolved_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"오류: speaker source map JSON을 읽을 수 없습니다: {exc}", file=sys.stderr)
        sys.exit(1)

    if not isinstance(data, dict):
        print("오류: speaker source map JSON은 object 여야 합니다", file=sys.stderr)
        sys.exit(1)

    return {
        str(speaker): str(source_key)
        for speaker, source_key in data.items()
        if source_key is not None
    }


def _apply_multicam_export_args(project: Any, args: argparse.Namespace) -> None:
    switching = getattr(args, "multicam_switching", None)
    speaker_map_path = getattr(args, "speaker_source_map", None)
    audio_source_key = getattr(args, "audio_source_key", None)
    if not switching and not speaker_map_path and not audio_source_key:
        return

    from avid.models.project import MulticamSettings

    current = project.multicam_settings or MulticamSettings()
    project.multicam_settings = MulticamSettings(
        switching=switching or current.switching,
        speaker_source_map=(
            _load_speaker_source_map(speaker_map_path)
            if speaker_map_path
            else dict(current.speaker_source_map)
        ),
        audio_source_key=audio_source_key or current.audio_source_key,
    )


async def _export_project_artifacts(
    project,
    project_json_path: Path,
    output_dir: Path,
    *,
    output_path: str | None = None,
    silence_mode: str = "cut",
    content_mode: str = "disabled",
    source_path: Path | None = None,
) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)

    base_name = _resolve_export_base_name(project_json_path, project, source_path)
    export_suffix = _resolve_export_suffix(project_json_path, project)
    fcpxml_path = Path(output_path).resolve() if output_path else output_dir / f"{base_name}_{export_suffix}.fcpxml"

    exporter = FCPXMLExporter()
    fcpxml_result, srt_result = await exporter.export(
        project,
        fcpxml_path,
        silence_mode=silence_mode,
        content_mode=content_mode,
    )

    artifacts: dict[str, str] = {"fcpxml": str(fcpxml_result)}
    if srt_result:
        artifacts["srt"] = str(srt_result)
    return artifacts


def cmd_apply_evaluation(args: argparse.Namespace) -> dict[str, Any]:
    project_json_path, project = _load_project_or_exit(args.project_json)

    evaluation_path = Path(args.evaluation).resolve()
    if not evaluation_path.exists():
        print(f"오류: evaluation JSON을 찾을 수 없습니다: {evaluation_path}", file=sys.stderr)
        sys.exit(1)

    output_project_json = Path(args.output_project_json).resolve()
    output_project_json.parent.mkdir(parents=True, exist_ok=True)

    override_count, changes_applied, join_strategy = _apply_evaluation_from_path(project, evaluation_path)
    saved_project_json = project.save(output_project_json)

    if join_strategy == "legacy_overlap":
        print(
            "경고: apply-evaluation 이 legacy overlap fallback 으로 동작했습니다. "
            "review-segments/v1 payload 로 마이그레이션하세요.",
            file=sys.stderr,
        )
    print(f"평가 적용 완료: {saved_project_json}")

    return _payload(
        "apply-evaluation",
        artifacts={"project_json": str(saved_project_json)},
        stats={
            "applied_evaluation_segments": override_count,
            "applied_changes": changes_applied,
            "join_strategy": join_strategy,
        },
    )


async def cmd_export_project(args: argparse.Namespace) -> dict[str, Any]:
    project_json_path, project = _load_project_or_exit(args.project_json)
    output_dir = Path(args.output_dir).resolve()
    _apply_multicam_export_args(project, args)

    artifacts = await _export_project_artifacts(
        project,
        project_json_path,
        output_dir,
        output_path=args.output,
        silence_mode=args.silence_mode,
        content_mode=args.content_mode,
    )

    print(f"프로젝트 export 완료: {artifacts['fcpxml']}")

    return _payload("export-project", artifacts=artifacts)


async def cmd_rebuild_multicam(args: argparse.Namespace) -> dict[str, Any]:
    project_json_path, project = _load_project_or_exit(args.project_json)
    output_project_json = Path(args.output_project_json).resolve()
    output_project_json.parent.mkdir(parents=True, exist_ok=True)

    source_manifest = getattr(args, "source_manifest", None)
    if source_manifest and args.source:
        print("오류: --source-manifest 와 --source 는 함께 사용할 수 없습니다", file=sys.stderr)
        sys.exit(1)
    if source_manifest and args.extra_source:
        print("오류: --source-manifest 와 --extra-source 는 함께 사용할 수 없습니다", file=sys.stderr)
        sys.exit(1)
    if source_manifest and args.offset:
        print("오류: --source-manifest 와 --offset 은 함께 사용할 수 없습니다. manifest 의 offset_ms 를 사용하세요", file=sys.stderr)
        sys.exit(1)

    stripped_sources = _strip_extra_sources(project)
    if source_manifest:
        manifest_path = Path(source_manifest).expanduser().resolve()
        if not manifest_path.exists():
            print(f"오류: source manifest 를 찾을 수 없습니다: {manifest_path}", file=sys.stderr)
            sys.exit(1)
        sync_results = await _rebuild_multicam_from_manifest_in_place(project, manifest_path)
        extra_source_count = len(sync_results)
    else:
        if not args.source:
            print("오류: rebuild-multicam 에는 --source 또는 --source-manifest 가 필요합니다", file=sys.stderr)
            sys.exit(1)
        source_path = _resolve_source_path_or_exit(args.source)
        extra_sources, extra_offsets = _parse_extra_sources(args)
        if not extra_sources:
            print("오류: rebuild-multicam 에는 최소 한 개 이상의 --extra-source 가 필요합니다", file=sys.stderr)
            sys.exit(1)
        sync_results = await _rebuild_multicam_in_place(
            project,
            source_path,
            extra_sources,
            extra_offsets or {},
        )
        extra_source_count = len(extra_sources)

    saved_project_json = project.save(output_project_json)
    diagnostics_path = _write_sync_diagnostics(
        output_project_json.parent,
        output_project_json.stem,
        sync_results,
    )

    print(f"멀티캠 재구성 완료: {saved_project_json}")

    artifacts = {"project_json": str(saved_project_json)}
    if diagnostics_path is not None:
        artifacts["sync_diagnostics"] = str(diagnostics_path)

    return _payload(
        "rebuild-multicam",
        artifacts=artifacts,
        stats={
            "extra_sources": extra_source_count,
            "stripped_extra_sources": stripped_sources,
        },
    )


def cmd_clear_extra_sources(args: argparse.Namespace) -> dict[str, Any]:
    _, project = _load_project_or_exit(args.project_json)
    output_project_json = Path(args.output_project_json).resolve()
    output_project_json.parent.mkdir(parents=True, exist_ok=True)

    stripped_sources = _strip_extra_sources(project)
    saved_project_json = project.save(output_project_json)

    print(f"추가 소스 제거 완료: {saved_project_json}")

    return _payload(
        "clear-extra-sources",
        artifacts={"project_json": str(saved_project_json)},
        stats={"stripped_extra_sources": stripped_sources},
    )


async def cmd_reexport(args: argparse.Namespace) -> dict[str, Any]:
    project_json_path, project = _load_project_or_exit(args.project_json)
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    print(
        "경고: 'reexport' 는 deprecated 입니다. "
        "'apply-evaluation', 'rebuild-multicam', 'clear-extra-sources', 'export-project' 로 마이그레이션하세요.",
        file=sys.stderr,
    )

    override_count = 0
    changes_applied = 0
    join_strategy = None
    if args.evaluation:
        evaluation_path = Path(args.evaluation).resolve()
        override_count, changes_applied, join_strategy = _apply_evaluation_from_path(project, evaluation_path)

    stripped_sources = _strip_extra_sources(project)
    extra_sources, extra_offsets = _parse_extra_sources(args)

    source_path = None
    if args.source:
        source_path = _resolve_source_path_or_exit(args.source)

    if extra_sources:
        if source_path is None:
            print("오류: --extra-source 를 사용할 때는 --source 가 필요합니다", file=sys.stderr)
            sys.exit(1)
        sync_results = await _rebuild_multicam_in_place(
            project,
            source_path,
            extra_sources,
            extra_offsets or {},
        )
        diagnostics_path = _write_sync_diagnostics(
            output_dir,
            project_json_path.stem,
            sync_results,
        )
    else:
        diagnostics_path = None

    updated_json_path = output_dir / project_json_path.name
    project.save(updated_json_path)
    artifacts = {
        "project_json": str(updated_json_path),
        **(await _export_project_artifacts(
            project,
            project_json_path,
            output_dir,
            output_path=args.output,
            silence_mode=args.silence_mode,
            content_mode=args.content_mode,
            source_path=source_path,
        )),
    }
    if diagnostics_path is not None:
        artifacts["sync_diagnostics"] = str(diagnostics_path)

    print(f"재-export 완료: {artifacts['fcpxml']}")

    return _payload(
        "reexport",
        artifacts=artifacts,
        stats={
            "applied_evaluation_segments": override_count,
            "applied_changes": changes_applied,
            "extra_sources": len(extra_sources or []),
            "stripped_extra_sources": stripped_sources,
            "join_strategy": join_strategy,
        },
    )


def cmd_version(_args: argparse.Namespace) -> dict[str, Any]:
    return _payload("version")


def cmd_create_proxy(args: argparse.Namespace) -> dict[str, Any]:
    from avid.services.proxy import create_proxy

    input_path = Path(args.input).resolve()
    output_path = Path(args.output).resolve()
    stats = create_proxy(
        input_path,
        output_path,
        mode=args.mode,
        height=args.height,
        encoder=args.encoder,
    )
    print(f"프록시 생성 완료: {output_path}")
    return _payload(
        "create-proxy",
        artifacts={"proxy": str(output_path)},
        stats=stats,
    )


async def cmd_doctor(args: argparse.Namespace) -> dict[str, Any]:
    from avid.services.transcription import ChalnaTranscriptionService

    chalna_url = args.chalna_url or os.environ.get("CHALNA_API_URL") or "http://localhost:7861"
    requested_providers = list(dict.fromkeys(args.provider or ["claude", "codex"]))
    probe_requested = bool(args.probe_providers)

    if not probe_requested and (args.provider_model or args.provider_effort):
        raise RuntimeError(
            "--provider-model 과 --provider-effort 는 --probe-providers 와 함께 사용해야 합니다"
        )
    if len(requested_providers) != 1 and (args.provider_model or args.provider_effort):
        raise RuntimeError(
            "--provider-model 과 --provider-effort 는 정확히 하나의 --provider 와 함께 사용해야 합니다"
        )

    checks = {
        "python": True,
        "ffmpeg": shutil.which("ffmpeg") is not None,
        "ffprobe": shutil.which("ffprobe") is not None,
    }

    service = ChalnaTranscriptionService(base_url=chalna_url, timeout=3.0)
    try:
        checks["chalna"] = await service.health_check()
    except Exception:
        checks["chalna"] = False

    provider_checks: dict[str, bool] = {}
    provider_probe_checks: dict[str, bool] = {}
    provider_probes: dict[str, Any] = {}
    provider_configs: dict[str, Any] = {}
    hints: list[str] = []

    single_provider = len(requested_providers) == 1

    for provider in requested_providers:
        model_override = args.provider_model if single_provider else None
        effort_override = args.provider_effort if single_provider else None
        provider_configs[provider] = _provider_config_payload(
            provider,
            model_override,
            effort_override,
        )
        provider_checks[provider] = shutil.which(provider) is not None

        if not probe_requested:
            continue

        if not provider_checks[provider]:
            provider_probe_checks[provider] = False
            provider_probes[provider] = {
                "status": "failed",
                "provider": provider,
                "model": provider_configs[provider]["model"],
                "reasoning_effort": provider_configs[provider]["effort"],
                "source": provider_configs[provider]["source"],
                "error": f"{provider} binary not found",
            }
            continue

        try:
            provider_probes[provider] = probe_provider(
                provider,
                model=model_override,
                effort=effort_override,
                timeout=60,
            )
            provider_probe_checks[provider] = True
        except Exception as exc:
            provider_probe_checks[provider] = False
            provider_probes[provider] = {
                "status": "failed",
                "provider": provider,
                "model": provider_configs[provider]["model"],
                "reasoning_effort": provider_configs[provider]["effort"],
                "source": provider_configs[provider]["source"],
                "error": str(exc),
            }

    checks["provider"] = all(provider_checks.values()) if provider_checks else True
    if probe_requested:
        checks["provider"] = checks["provider"] and all(provider_probe_checks.values())
    else:
        hints.append("실제 Claude/Codex 호출까지 확인하려면 --probe-providers 를 사용하세요")

    ok = all(checks.values())

    if not args.json:
        print("환경 진단 결과:")
        for name, passed in checks.items():
            print(f"  {name}: {'ok' if passed else 'failed'}")
        for provider in requested_providers:
            print(
                f"  provider[{provider}]: "
                f"{'ok' if provider_checks[provider] else 'failed'}"
                f" ({'probe' if probe_requested else 'binary only'})"
            )
            print(f"    model: {provider_configs[provider]['model']}")
            print(f"    effort: {provider_configs[provider]['effort']}")
            if probe_requested and provider in provider_probes and not provider_probe_checks.get(provider, False):
                print(f"    error: {provider_probes[provider].get('error')}")
        print(f"  chalna_url: {chalna_url}")
        for hint in hints:
            print(f"  hint: {hint}")

    payload = _payload(
        "doctor",
        checks=checks,
        chalna_url=chalna_url,
        provider_checks=provider_checks,
        provider_probe_requested=probe_requested,
        provider_probe_checks=provider_probe_checks,
        provider_probes=provider_probes,
        provider_configs=provider_configs,
        requested_providers=requested_providers,
        hints=hints,
    )
    if single_provider:
        only_provider = requested_providers[0]
        payload["provider_config"] = provider_configs[only_provider]
        if probe_requested and only_provider in provider_probes:
            payload["provider_probe"] = provider_probes[only_provider]

    if not ok:
        if args.json:
            raise RuntimeError(json.dumps(payload, ensure_ascii=False, default=_json_default))
        raise RuntimeError("doctor checks failed")

    return payload


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="avid-cli",
        description="AVID - 자동 영상 편집 CLI",
    )
    subparsers = parser.add_subparsers(dest="command", help="사용 가능한 명령")

    p_transcribe = subparsers.add_parser("transcribe", help="음성 인식 (Chalna API)")
    p_transcribe.add_argument("input", type=str, help="입력 영상/오디오 파일")
    p_transcribe.add_argument("-l", "--language", default="ko", help="언어 (기본: ko)")
    p_transcribe.add_argument("--chalna-url", type=str, help="Chalna API URL (기본: CHALNA_API_URL 환경변수 또는 http://localhost:7861)")
    p_transcribe.add_argument("--llm-refine", action="store_true", default=False, help="LLM 텍스트 정제 활성화")
    p_transcribe.add_argument("--context", type=str, default=None, help="전사 정확도 향상을 위한 컨텍스트 텍스트")
    p_transcribe.add_argument("-d", "--output-dir", type=str, help="출력 디렉토리")
    _add_machine_output_flags(p_transcribe)

    p_overview = subparsers.add_parser("transcript-overview", help="스토리 구조 분석 (Pass 1)")
    p_overview.add_argument("input", type=str, help="입력 SRT 자막 파일")
    p_overview.add_argument("-o", "--output", type=str, help="출력 storyline JSON 경로")
    p_overview.add_argument("--content-type", choices=["lecture", "podcast", "auto"], default="auto", help="콘텐츠 유형 (기본: auto)")
    p_overview.add_argument("--provider", choices=["claude", "codex"], default="codex", help="AI 프로바이더 (기본: codex)")
    p_overview.add_argument("--provider-model", type=str, help="provider model override")
    p_overview.add_argument("--provider-effort", type=str, help="provider effort override")
    _add_machine_output_flags(p_overview)

    p_subcut = subparsers.add_parser("subtitle-cut", help="자막 기반 컷 편집")
    p_subcut.add_argument("input", type=str, help="입력 영상 파일")
    p_subcut.add_argument("--srt", type=str, required=True, help="SRT 자막 파일 (필수)")
    p_subcut.add_argument("--segments-json", type=str, help="metadata-preserving transcript segments JSON")
    p_subcut.add_argument("--context", type=str, help="storyline.json 경로 (Pass 1 결과)")
    p_subcut.add_argument("--provider", choices=["claude", "codex"], default="codex", help="AI 프로바이더 (기본: codex)")
    p_subcut.add_argument("--provider-model", type=str, help="provider model override")
    p_subcut.add_argument("--provider-effort", type=str, help="provider effort override")
    p_subcut.add_argument("-o", "--output", type=str, help="출력 FCPXML 경로")
    p_subcut.add_argument("-d", "--output-dir", type=str, help="출력 디렉토리")
    p_subcut.add_argument("--final", action="store_true", help="최종 편집본 (모든 편집 적용, 기본: 검토용 disabled)")
    p_subcut.add_argument("--extra-source", action="append", default=[], help="추가 소스 파일 (반복 가능)")
    p_subcut.add_argument("--offset", action="append", default=[], help="수동 오프셋 ms (--extra-source 순서 대응)")
    p_subcut.add_argument("--edit-intensity", choices=["light", "normal", "heavy"], default="normal", help="컷 편집 강도")
    p_subcut.add_argument("--edit-decision-version", choices=["legacy", "boundary_aware_v1"], default="legacy", help="Edit decision prompt/parser version")
    p_subcut.add_argument("--segmentation-boundary-rule", choices=["word_boundary", "midpoint_gap", "low_energy_gap_v1"], default="word_boundary", help="Segmentation timestamp boundary rule")
    p_subcut.add_argument("--junction-audit", action=argparse.BooleanOptionalAction, default=True, help="Edit Decision 이후 연결부 자동 검토")
    _add_machine_output_flags(p_subcut)

    p_podcast = subparsers.add_parser("podcast-cut", help="팟캐스트 편집 (재미 기준)")
    p_podcast.add_argument("input", type=str, help="입력 오디오/영상 파일")
    p_podcast.add_argument("--srt", type=str, help="SRT 자막 파일 (없으면 chalna로 생성)")
    p_podcast.add_argument("--segments-json", type=str, help="metadata-preserving transcript segments JSON")
    p_podcast.add_argument("--context", type=str, help="storyline.json 경로 (Pass 1 결과)")
    p_podcast.add_argument("--provider", choices=["claude", "codex"], default="codex", help="AI 프로바이더 (기본: codex)")
    p_podcast.add_argument("--provider-model", type=str, help="provider model override")
    p_podcast.add_argument("--provider-effort", type=str, help="provider effort override")
    p_podcast.add_argument(
        "--prompt-profile",
        choices=["podcast", "ai_frontier"],
        default="podcast",
        help="Edit Decision 기본 프롬프트 프로필",
    )
    p_podcast.add_argument("-d", "--output-dir", type=str, help="출력 디렉토리")
    p_podcast.add_argument("--final", action="store_true", help="최종 편집본 (모든 편집 적용, 기본: 검토용 disabled)")
    p_podcast.add_argument("--extra-source", action="append", default=[], help="추가 소스 파일 (반복 가능)")
    p_podcast.add_argument("--offset", action="append", default=[], help="수동 오프셋 ms (--extra-source 순서 대응)")
    p_podcast.add_argument("--edit-intensity", choices=["light", "normal", "heavy"], default="normal", help="컷 편집 강도")
    p_podcast.add_argument("--edit-decision-version", choices=["legacy", "boundary_aware_v1"], default="legacy", help="Edit decision prompt/parser version")
    p_podcast.add_argument("--segmentation-boundary-rule", choices=["word_boundary", "midpoint_gap", "low_energy_gap_v1"], default="word_boundary", help="Segmentation timestamp boundary rule")
    p_podcast.add_argument("--junction-audit", action=argparse.BooleanOptionalAction, default=True, help="Edit Decision 이후 연결부 자동 검토")
    _add_machine_output_flags(p_podcast)

    p_review_segments = subparsers.add_parser("review-segments", help="project JSON 에서 review payload 생성")
    p_review_segments.add_argument("--project-json", required=True, type=str, help="입력 avid project JSON")
    _add_machine_output_flags(p_review_segments)

    p_apply_eval = subparsers.add_parser("apply-evaluation", help="기존 avid project에 human evaluation override 적용")
    p_apply_eval.add_argument("--project-json", required=True, type=str, help="입력 avid project JSON")
    p_apply_eval.add_argument("--evaluation", required=True, type=str, help="evaluation JSON 파일")
    p_apply_eval.add_argument("--output-project-json", required=True, type=str, help="평가 반영 후 저장할 avid project JSON")
    _add_machine_output_flags(p_apply_eval)

    p_export_project = subparsers.add_parser("export-project", help="준비된 avid project를 FCPXML/SRT 로 export")
    p_export_project.add_argument("--project-json", required=True, type=str, help="입력 avid project JSON")
    p_export_project.add_argument("--output-dir", required=True, type=str, help="출력 디렉토리")
    p_export_project.add_argument("-o", "--output", type=str, help="출력 FCPXML 경로")
    p_export_project.add_argument("--silence-mode", choices=["cut", "disabled"], default="cut", help="무음 처리 방식")
    p_export_project.add_argument("--content-mode", choices=["cut", "disabled"], default="disabled", help="콘텐츠 컷 처리 방식")
    p_export_project.add_argument(
        "--multicam-switching",
        choices=["none", "follow_speaker", "conservative_follow_speaker"],
        help="멀티캠 speaker 기반 전환 규칙",
    )
    p_export_project.add_argument(
        "--speaker-source-map",
        type=str,
        help="speaker -> source_key JSON 파일",
    )
    p_export_project.add_argument(
        "--audio-source-key",
        type=str,
        help="오디오를 유지할 source_key (기본: primary)",
    )
    _add_machine_output_flags(p_export_project)

    p_rebuild_multicam = subparsers.add_parser("rebuild-multicam", help="기존 avid project의 extra source 를 재구성")
    p_rebuild_multicam.add_argument("--project-json", required=True, type=str, help="입력 avid project JSON")
    p_rebuild_multicam.add_argument("--source", type=str, help="메인 소스 파일 경로")
    p_rebuild_multicam.add_argument("--source-manifest", type=str, help="오디오 프록시와 미디어 메타데이터 manifest 경로")
    p_rebuild_multicam.add_argument("--extra-source", action="append", default=[], help="추가 소스 파일 (반복 가능)")
    p_rebuild_multicam.add_argument("--offset", action="append", default=[], help="수동 오프셋 ms (--extra-source 순서 대응)")
    p_rebuild_multicam.add_argument("--output-project-json", required=True, type=str, help="재구성 후 저장할 avid project JSON")
    _add_machine_output_flags(p_rebuild_multicam)

    p_clear_extra_sources = subparsers.add_parser("clear-extra-sources", help="기존 avid project의 extra source 를 명시적으로 제거")
    p_clear_extra_sources.add_argument("--project-json", required=True, type=str, help="입력 avid project JSON")
    p_clear_extra_sources.add_argument("--output-project-json", required=True, type=str, help="제거 후 저장할 avid project JSON")
    _add_machine_output_flags(p_clear_extra_sources)

    p_reexport = subparsers.add_parser("reexport", help="기존 avid project를 재-export")
    p_reexport.add_argument("--project-json", required=True, type=str, help="입력 avid project JSON")
    p_reexport.add_argument("--output-dir", required=True, type=str, help="출력 디렉토리")
    p_reexport.add_argument("--source", type=str, help="메인 소스 파일 경로 (extra source sync 시 필요)")
    p_reexport.add_argument("--evaluation", type=str, help="evaluation JSON 파일")
    p_reexport.add_argument("--extra-source", action="append", default=[], help="추가 소스 파일 (반복 가능)")
    p_reexport.add_argument("--offset", action="append", default=[], help="수동 오프셋 ms (--extra-source 순서 대응)")
    p_reexport.add_argument("-o", "--output", type=str, help="출력 FCPXML 경로")
    p_reexport.add_argument("--silence-mode", choices=["cut", "disabled"], default="cut", help="무음 처리 방식")
    p_reexport.add_argument("--content-mode", choices=["cut", "disabled"], default="disabled", help="콘텐츠 컷 처리 방식")
    _add_machine_output_flags(p_reexport)

    p_create_proxy = subparsers.add_parser("create-proxy", help="FCP relink 용 360p proxy 생성")
    p_create_proxy.add_argument("input", type=str, help="입력 원본 미디어")
    p_create_proxy.add_argument("-o", "--output", required=True, type=str, help="출력 proxy 경로")
    p_create_proxy.add_argument(
        "--mode",
        choices=["zero-timecode-proxy", "preserve-timecode-proxy"],
        required=True,
        help="timecode 처리 방식",
    )
    p_create_proxy.add_argument("--height", type=int, default=360, help="출력 높이 (기본: 360)")
    p_create_proxy.add_argument(
        "--encoder",
        choices=["auto", "h264_nvenc", "libx264"],
        default="auto",
        help="비디오 인코더 (기본: auto)",
    )
    _add_machine_output_flags(p_create_proxy)

    p_version = subparsers.add_parser("version", help="avid 버전 정보 출력")
    _add_machine_output_flags(p_version)

    p_doctor = subparsers.add_parser("doctor", help="실행 환경 진단")
    p_doctor.add_argument("--chalna-url", type=str, help="진단할 Chalna API URL")
    p_doctor.add_argument("--provider", choices=["claude", "codex"], action="append", help="진단할 AI provider (기본: claude,codex 둘 다)")
    p_doctor.add_argument("--probe-providers", action="store_true", help="provider binary 확인을 넘어서 실제 Claude/Codex 호출까지 수행")
    p_doctor.add_argument("--provider-model", type=str, help="단일 provider probe 시 model override")
    p_doctor.add_argument("--provider-effort", type=str, help="단일 provider probe 시 effort override")
    _add_machine_output_flags(p_doctor)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    try:
        if args.command == "transcribe":
            payload = _run_handler(args, cmd_transcribe, is_async=True)
        elif args.command == "transcript-overview":
            payload = _run_handler(args, cmd_transcript_overview, is_async=True)
        elif args.command == "subtitle-cut":
            payload = _run_handler(args, cmd_subtitle_cut, is_async=True)
        elif args.command == "podcast-cut":
            payload = _run_handler(args, cmd_podcast_cut, is_async=True)
        elif args.command == "review-segments":
            payload = _run_handler(args, cmd_review_segments, is_async=False)
        elif args.command == "apply-evaluation":
            payload = _run_handler(args, cmd_apply_evaluation, is_async=False)
        elif args.command == "export-project":
            payload = _run_handler(args, cmd_export_project, is_async=True)
        elif args.command == "rebuild-multicam":
            payload = _run_handler(args, cmd_rebuild_multicam, is_async=True)
        elif args.command == "clear-extra-sources":
            payload = _run_handler(args, cmd_clear_extra_sources, is_async=False)
        elif args.command == "reexport":
            payload = _run_handler(args, cmd_reexport, is_async=True)
        elif args.command == "create-proxy":
            payload = _run_handler(args, cmd_create_proxy, is_async=False)
        elif args.command == "version":
            payload = _run_handler(args, cmd_version, is_async=False)
        elif args.command == "doctor":
            payload = _run_handler(args, cmd_doctor, is_async=True)
        else:
            parser.error(f"unknown command: {args.command}")
            return
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)

    _write_machine_output(args, payload)


if __name__ == "__main__":
    main()
