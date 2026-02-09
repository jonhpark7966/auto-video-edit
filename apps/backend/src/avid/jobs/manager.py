"""Job manager with in-memory storage and background execution."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from avid.jobs.models import Job, JobResult, JobStatus, JobType

logger = logging.getLogger(__name__)


class JobManager:
    """Manages background jobs with concurrency control.

    Jobs are stored in-memory (dict). Background execution uses
    asyncio.create_task with a semaphore for concurrency limiting.
    """

    def __init__(self, max_concurrent: int = 2) -> None:
        self._jobs: dict[str, Job] = {}
        self._semaphore = asyncio.Semaphore(max_concurrent)

    def create_job(self, job_type: JobType, params: dict[str, Any]) -> Job:
        """Create a new job and schedule it for background execution.

        Args:
            job_type: Type of job to create.
            params: Job-specific parameters.

        Returns:
            The created Job (status=pending).
        """
        job = Job(type=job_type, params=params)
        self._jobs[job.id] = job
        asyncio.create_task(self._run_job(job))
        return job

    def get_job(self, job_id: str) -> Job | None:
        """Get a job by ID."""
        return self._jobs.get(job_id)

    def list_jobs(self) -> list[Job]:
        """List all jobs, most recent first."""
        return sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)

    async def _run_job(self, job: Job) -> None:
        """Execute a job with semaphore-based concurrency control."""
        async with self._semaphore:
            job.status = JobStatus.PROCESSING
            job.message = "Starting..."
            try:
                result = await self._execute(job)
                job.status = JobStatus.COMPLETED
                job.progress = 100
                job.message = "Complete"
                job.result = result
            except Exception as e:
                logger.exception("Job %s failed", job.id)
                job.status = JobStatus.FAILED
                job.error = str(e)
                job.message = "Failed"
            finally:
                job.completed_at = datetime.now(timezone.utc)

    async def _execute(self, job: Job) -> JobResult:
        """Dispatch to the appropriate executor based on job type."""
        executors = {
            JobType.TRANSCRIBE: self._exec_transcribe,
            JobType.TRANSCRIPT_OVERVIEW: self._exec_transcript_overview,
            JobType.SUBTITLE_CUT: self._exec_subtitle_cut,
            JobType.PODCAST_CUT: self._exec_podcast_cut,
        }
        executor = executors[job.type]
        return await executor(job)

    # ------------------------------------------------------------------
    # Executors — each calls the existing service layer
    # ------------------------------------------------------------------

    async def _exec_transcribe(self, job: Job) -> JobResult:
        from avid.services.transcription import ChalnaTranscriptionService

        p = job.params
        input_path = Path(p["input_path"])
        language = p.get("language", "ko")

        # Extract audio from video if needed
        audio_path = input_path
        temp_audio: Path | None = None
        video_exts = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".flv", ".wmv"}
        if input_path.suffix.lower() in video_exts:
            from avid.services.media import MediaService

            media_svc = MediaService()
            temp_audio = input_path.parent / f"{input_path.stem}_audio.wav"
            job.message = "Extracting audio..."
            job.progress = 5
            audio_path = await media_svc.extract_audio(input_path, temp_audio)

        service = ChalnaTranscriptionService()

        def _progress(pct: float, msg: str) -> None:
            job.progress = int(pct * 90) + 10  # 10-100 range
            job.message = msg

        job.message = "Transcribing..."
        job.progress = 10
        result = await service.transcribe_async(
            audio_path=audio_path,
            language=language,
            use_alignment=p.get("use_alignment", True),
            use_llm_refinement=p.get("use_llm_refinement", True),
            progress_callback=_progress,
        )

        # Clean up temp audio
        if temp_audio and temp_audio.exists():
            temp_audio.unlink()

        # Write SRT
        output_srt = input_path.parent / f"{input_path.stem}.srt"
        lines = []
        for i, seg in enumerate(result.segments, 1):
            start_ms = int(seg.start * 1000)
            end_ms = int(seg.end * 1000)
            lines.append(
                f"{i}\n{_ms_to_srt(start_ms)} --> {_ms_to_srt(end_ms)}\n{seg.text}\n"
            )
        output_srt.write_text("\n".join(lines), encoding="utf-8")

        return JobResult(
            output_files={"srt": str(output_srt)},
            summary={
                "segments": len(result.segments),
                "language": result.language,
            },
        )

    async def _exec_transcript_overview(self, job: Job) -> JobResult:
        from avid.services.transcript_overview import TranscriptOverviewService

        p = job.params
        srt_path = Path(p["srt_path"])
        content_type = p.get("content_type", "auto")
        provider = p.get("provider", "codex")

        service = TranscriptOverviewService()
        job.message = "Analyzing transcript structure..."
        job.progress = 10

        output_path = await service.analyze(
            srt_path=srt_path,
            content_type=content_type,
            provider=provider,
        )

        job.progress = 90
        job.message = "Loading storyline..."
        storyline = service.load_storyline(output_path)

        chapters = storyline.get("chapters", [])
        return JobResult(
            output_files={"storyline": str(output_path)},
            summary={
                "chapters": len(chapters),
                "narrative_arc": storyline.get("narrative_arc", ""),
            },
        )

    async def _exec_subtitle_cut(self, job: Job) -> JobResult:
        from avid.export.fcpxml import FCPXMLExporter
        from avid.export.report import generate_edit_report_json
        from avid.services.subtitle_cut import SubtitleCutService

        p = job.params
        srt_path = Path(p["srt_path"])
        video_path = Path(p["video_path"])
        context_path = Path(p["context_path"]) if p.get("context_path") else None
        provider = p.get("provider", "codex")
        export_mode = p.get("export_mode", "review")

        output_dir = video_path.parent / f"{video_path.stem}_subtitle_cut_output"
        output_dir.mkdir(parents=True, exist_ok=True)

        service = SubtitleCutService()
        job.message = "Analyzing subtitles..."
        job.progress = 10

        project, project_path = await service.analyze(
            srt_path=srt_path,
            video_path=video_path,
            output_dir=output_dir,
            storyline_path=context_path,
            provider=provider,
        )

        job.progress = 70
        job.message = "Exporting FCPXML..."

        exporter = FCPXMLExporter()
        fcpxml_path = output_dir / f"{video_path.stem}.final.fcpxml"
        content_mode = "cut" if export_mode == "final" else "disabled"
        show_disabled = export_mode != "final"

        fcpxml_result, srt_result = await exporter.export(
            project,
            fcpxml_path,
            show_disabled_cuts=show_disabled,
            silence_mode="cut",
            content_mode=content_mode,
        )

        output_files: dict[str, str] = {
            "project": str(project_path),
            "fcpxml": str(fcpxml_result),
        }
        if srt_result:
            output_files["srt"] = str(srt_result)

        # Generate report
        report_data = generate_edit_report_json(project)

        return JobResult(
            output_files=output_files,
            summary={
                "total_decisions": len(project.edit_decisions),
                "by_reason": report_data.get("summary", {}).get("by_reason", {}),
            },
        )

    async def _exec_podcast_cut(self, job: Job) -> JobResult:
        from avid.export.report import generate_edit_report_json
        from avid.services.podcast_cut import PodcastCutService

        p = job.params
        audio_path = Path(p["audio_path"])
        srt_path = Path(p["srt_path"]) if p.get("srt_path") else None
        context_path = Path(p["context_path"]) if p.get("context_path") else None
        provider = p.get("provider", "codex")
        export_mode = p.get("export_mode", "review")

        output_dir = audio_path.parent / f"{audio_path.stem}_podcast_cut_output"
        output_dir.mkdir(parents=True, exist_ok=True)

        service = PodcastCutService()
        job.message = "Processing podcast..."
        job.progress = 10

        project, outputs = await service.process(
            audio_path=audio_path,
            output_dir=output_dir,
            srt_path=srt_path,
            skip_transcription=srt_path is not None,
            export_mode=export_mode,
            storyline_path=context_path,
            provider=provider,
        )

        output_files = {k: str(v) for k, v in outputs.items()}
        report_data = generate_edit_report_json(project)

        return JobResult(
            output_files=output_files,
            summary={
                "total_decisions": len(project.edit_decisions),
                "by_reason": report_data.get("summary", {}).get("by_reason", {}),
            },
        )


def _ms_to_srt(ms: int) -> str:
    """Format milliseconds as SRT timestamp."""
    h = ms // 3600000
    ms %= 3600000
    m = ms // 60000
    ms %= 60000
    s = ms // 1000
    rest = ms % 1000
    return f"{h:02d}:{m:02d}:{s:02d},{rest:03d}"
