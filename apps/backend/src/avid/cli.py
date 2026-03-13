"""AVID command-line interface with subcommands.

Usage:
    avid-cli transcribe <video> [-l ko] [--chalna-url URL]
    avid-cli transcript-overview <srt> [-o storyline.json] [--provider codex] [--content-type auto]
    avid-cli subtitle-cut <video> --srt sub.srt [--provider codex] [--context storyline.json] [-o output.fcpxml]
    avid-cli podcast-cut <audio> [--srt sub.srt] [--provider codex] [--context storyline.json] [-d output_dir]
    avid-cli apply-evaluation --project-json project.avid.json --evaluation evaluation.json --output-project-json out.avid.json
    avid-cli reexport --project-json project.avid.json --output-dir out
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
    extra_sources, extra_offsets = _parse_extra_sources(args)

    print(f"자막 분석 시작: {srt_path.name}")
    print(f"  비디오: {video_path.name}")
    print(f"  프로바이더: {provider_config['provider']}")
    print(f"  모델: {provider_config['model']}")
    print(f"  effort: {provider_config['effort']}")
    print(f"  모드: {export_mode} ({'모든 편집 적용' if export_mode == 'final' else '검토용 disabled'})")
    if context_path:
        print(f"  컨텍스트: {context_path.name}")
    if extra_sources:
        print(f"  추가 소스: {len(extra_sources)}개")

    project, project_path = await service.analyze(
        srt_path=srt_path,
        video_path=video_path,
        output_dir=output_dir,
        storyline_path=context_path,
        provider=args.provider,
        provider_model=args.provider_model,
        provider_effort=args.provider_effort,
        extra_sources=extra_sources,
        extra_offsets=extra_offsets,
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
    if srt_result:
        artifacts["srt"] = str(srt_result)

    return _payload(
        "subtitle-cut",
        artifacts=artifacts,
        stats={"edit_decisions": len(project.edit_decisions)},
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
    export_mode = "final" if args.final else "review"
    extra_sources, extra_offsets = _parse_extra_sources(args)

    print(f"팟캐스트 편집 시작: {audio_path.name}")
    print(f"  프로바이더: {provider_config['provider']}")
    print(f"  모델: {provider_config['model']}")
    print(f"  effort: {provider_config['effort']}")
    if srt_path:
        print(f"  SRT: {srt_path.name}")
        print(f"  (자막 생성 건너뜀)")
    else:
        print(f"  chalna로 자막 생성 예정")
    if context_path:
        print(f"  컨텍스트: {context_path.name}")
    if extra_sources:
        print(f"  추가 소스: {len(extra_sources)}개")
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
        provider_model=args.provider_model,
        provider_effort=args.provider_effort,
        extra_sources=extra_sources,
        extra_offsets=extra_offsets,
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

    return _payload(
        "podcast-cut",
        artifacts=artifacts,
        stats={"edit_decisions": len(project.edit_decisions)},
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


def _apply_evaluation_to_project(project, eval_segments: list[dict[str, Any]]) -> tuple[int, int]:
    from avid.models.timeline import EditDecision, EditReason, EditType, TimeRange

    video_tracks = project.get_video_tracks()
    primary_video_track_id = video_tracks[0].id if video_tracks else None
    audio_tracks = project.get_audio_tracks()
    primary_audio_track_ids = None
    if video_tracks:
        primary_source_id = video_tracks[0].source_file_id
        primary_audio_track_ids = [
            t.id for t in audio_tracks if t.source_file_id == primary_source_id
        ]

    human_overrides = []
    for seg in eval_segments:
        human = seg.get("human")
        if human:
            human_overrides.append((seg["start_ms"], seg["end_ms"], human["action"]))

    if not human_overrides:
        return 0, 0

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
            ))
            cuts_added += 1

    new_decisions.sort(key=lambda ed: ed.range.start_ms)
    project.edit_decisions = new_decisions

    changes = abs(original_count - len(new_decisions)) + cuts_added
    return len(human_overrides), changes


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


def _resolve_source_path_or_exit(source_path: str) -> Path:
    resolved_path = Path(source_path).resolve()
    if not resolved_path.exists():
        print(f"오류: 메인 소스 파일을 찾을 수 없습니다: {resolved_path}", file=sys.stderr)
        sys.exit(1)
    return resolved_path


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
    fcpxml_path = Path(output_path).resolve() if output_path else output_dir / f"{base_name}_subtitle_cut.fcpxml"

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

    eval_segments = _load_evaluation_segments(evaluation_path)
    override_count, changes_applied = _apply_evaluation_to_project(project, eval_segments)
    saved_project_json = project.save(output_project_json)

    print(f"평가 적용 완료: {saved_project_json}")

    return _payload(
        "apply-evaluation",
        artifacts={"project_json": str(saved_project_json)},
        stats={
            "applied_evaluation_segments": override_count,
            "applied_changes": changes_applied,
        },
    )


async def cmd_export_project(args: argparse.Namespace) -> dict[str, Any]:
    project_json_path, project = _load_project_or_exit(args.project_json)
    output_dir = Path(args.output_dir).resolve()

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
    from avid.services.audio_sync import AudioSyncService

    project_json_path, project = _load_project_or_exit(args.project_json)
    source_path = _resolve_source_path_or_exit(args.source)
    output_project_json = Path(args.output_project_json).resolve()
    output_project_json.parent.mkdir(parents=True, exist_ok=True)

    extra_sources, extra_offsets = _parse_extra_sources(args)
    if not extra_sources:
        print("오류: rebuild-multicam 에는 최소 한 개 이상의 --extra-source 가 필요합니다", file=sys.stderr)
        sys.exit(1)

    stripped_sources = _strip_extra_sources(project)
    sync_service = AudioSyncService()
    await sync_service.add_extra_sources(
        project,
        source_path,
        extra_sources,
        extra_offsets or {},
    )
    saved_project_json = project.save(output_project_json)

    print(f"멀티캠 재구성 완료: {saved_project_json}")

    return _payload(
        "rebuild-multicam",
        artifacts={"project_json": str(saved_project_json)},
        stats={
            "extra_sources": len(extra_sources),
            "stripped_extra_sources": stripped_sources,
        },
    )


async def cmd_reexport(args: argparse.Namespace) -> dict[str, Any]:
    from avid.services.audio_sync import AudioSyncService

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
    if args.evaluation:
        evaluation_path = Path(args.evaluation).resolve()
        if not evaluation_path.exists():
            print(f"오류: evaluation JSON을 찾을 수 없습니다: {evaluation_path}", file=sys.stderr)
            sys.exit(1)
        eval_segments = _load_evaluation_segments(evaluation_path)
        override_count, changes_applied = _apply_evaluation_to_project(project, eval_segments)

    stripped_sources = _strip_extra_sources(project)
    extra_sources, extra_offsets = _parse_extra_sources(args)

    source_path = None
    if args.source:
        source_path = _resolve_source_path_or_exit(args.source)

    if extra_sources:
        if source_path is None:
            print("오류: --extra-source 를 사용할 때는 --source 가 필요합니다", file=sys.stderr)
            sys.exit(1)
        sync_service = AudioSyncService()
        await sync_service.add_extra_sources(
            project,
            source_path,
            extra_sources,
            extra_offsets or {},
        )

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

    print(f"재-export 완료: {artifacts['fcpxml']}")

    return _payload(
        "reexport",
        artifacts=artifacts,
        stats={
            "applied_evaluation_segments": override_count,
            "applied_changes": changes_applied,
            "extra_sources": len(extra_sources or []),
            "stripped_extra_sources": stripped_sources,
        },
    )


def cmd_version(_args: argparse.Namespace) -> dict[str, Any]:
    return _payload("version")


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
    p_subcut.add_argument("--context", type=str, help="storyline.json 경로 (Pass 1 결과)")
    p_subcut.add_argument("--provider", choices=["claude", "codex"], default="codex", help="AI 프로바이더 (기본: codex)")
    p_subcut.add_argument("--provider-model", type=str, help="provider model override")
    p_subcut.add_argument("--provider-effort", type=str, help="provider effort override")
    p_subcut.add_argument("-o", "--output", type=str, help="출력 FCPXML 경로")
    p_subcut.add_argument("-d", "--output-dir", type=str, help="출력 디렉토리")
    p_subcut.add_argument("--final", action="store_true", help="최종 편집본 (모든 편집 적용, 기본: 검토용 disabled)")
    p_subcut.add_argument("--extra-source", action="append", default=[], help="추가 소스 파일 (반복 가능)")
    p_subcut.add_argument("--offset", action="append", default=[], help="수동 오프셋 ms (--extra-source 순서 대응)")
    _add_machine_output_flags(p_subcut)

    p_podcast = subparsers.add_parser("podcast-cut", help="팟캐스트 편집 (재미 기준)")
    p_podcast.add_argument("input", type=str, help="입력 오디오/영상 파일")
    p_podcast.add_argument("--srt", type=str, help="SRT 자막 파일 (없으면 chalna로 생성)")
    p_podcast.add_argument("--context", type=str, help="storyline.json 경로 (Pass 1 결과)")
    p_podcast.add_argument("--provider", choices=["claude", "codex"], default="codex", help="AI 프로바이더 (기본: codex)")
    p_podcast.add_argument("--provider-model", type=str, help="provider model override")
    p_podcast.add_argument("--provider-effort", type=str, help="provider effort override")
    p_podcast.add_argument("-d", "--output-dir", type=str, help="출력 디렉토리")
    p_podcast.add_argument("--final", action="store_true", help="최종 편집본 (모든 편집 적용, 기본: 검토용 disabled)")
    p_podcast.add_argument("--extra-source", action="append", default=[], help="추가 소스 파일 (반복 가능)")
    p_podcast.add_argument("--offset", action="append", default=[], help="수동 오프셋 ms (--extra-source 순서 대응)")
    _add_machine_output_flags(p_podcast)

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
    _add_machine_output_flags(p_export_project)

    p_rebuild_multicam = subparsers.add_parser("rebuild-multicam", help="기존 avid project의 extra source 를 재구성")
    p_rebuild_multicam.add_argument("--project-json", required=True, type=str, help="입력 avid project JSON")
    p_rebuild_multicam.add_argument("--source", required=True, type=str, help="메인 소스 파일 경로")
    p_rebuild_multicam.add_argument("--extra-source", action="append", default=[], help="추가 소스 파일 (반복 가능)")
    p_rebuild_multicam.add_argument("--offset", action="append", default=[], help="수동 오프셋 ms (--extra-source 순서 대응)")
    p_rebuild_multicam.add_argument("--output-project-json", required=True, type=str, help="재구성 후 저장할 avid project JSON")
    _add_machine_output_flags(p_rebuild_multicam)

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
        elif args.command == "apply-evaluation":
            payload = _run_handler(args, cmd_apply_evaluation, is_async=False)
        elif args.command == "export-project":
            payload = _run_handler(args, cmd_export_project, is_async=True)
        elif args.command == "rebuild-multicam":
            payload = _run_handler(args, cmd_rebuild_multicam, is_async=True)
        elif args.command == "reexport":
            payload = _run_handler(args, cmd_reexport, is_async=True)
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
