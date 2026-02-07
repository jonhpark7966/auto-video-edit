"""Job management endpoints."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from avid.api.deps import get_job_manager
from avid.api.schemas import (
    JobCreateResponse,
    JobListItem,
    JobResultResponse,
    JobStatusResponse,
    OverviewRequest,
    PodcastCutRequest,
    SubtitleCutRequest,
    TranscribeRequest,
)
from avid.jobs.manager import JobManager
from avid.jobs.models import JobType

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])


def _validate_file(path_str: str, label: str) -> None:
    """Raise 422 if the file does not exist."""
    if not Path(path_str).exists():
        raise HTTPException(status_code=422, detail=f"{label} not found: {path_str}")


# ------------------------------------------------------------------
# POST — create jobs (202 Accepted)
# ------------------------------------------------------------------


@router.post("/transcribe", response_model=JobCreateResponse, status_code=202)
async def create_transcribe_job(
    req: TranscribeRequest,
    mgr: JobManager = Depends(get_job_manager),
) -> JobCreateResponse:
    _validate_file(req.input_path, "input_path")
    job = mgr.create_job(JobType.TRANSCRIBE, req.model_dump())
    return JobCreateResponse(job_id=job.id, status=job.status.value, type=job.type.value)


@router.post("/transcript-overview", response_model=JobCreateResponse, status_code=202)
async def create_overview_job(
    req: OverviewRequest,
    mgr: JobManager = Depends(get_job_manager),
) -> JobCreateResponse:
    _validate_file(req.srt_path, "srt_path")
    job = mgr.create_job(JobType.TRANSCRIPT_OVERVIEW, req.model_dump())
    return JobCreateResponse(job_id=job.id, status=job.status.value, type=job.type.value)


@router.post("/subtitle-cut", response_model=JobCreateResponse, status_code=202)
async def create_subtitle_cut_job(
    req: SubtitleCutRequest,
    mgr: JobManager = Depends(get_job_manager),
) -> JobCreateResponse:
    _validate_file(req.video_path, "video_path")
    _validate_file(req.srt_path, "srt_path")
    if req.context_path:
        _validate_file(req.context_path, "context_path")
    job = mgr.create_job(JobType.SUBTITLE_CUT, req.model_dump())
    return JobCreateResponse(job_id=job.id, status=job.status.value, type=job.type.value)


@router.post("/podcast-cut", response_model=JobCreateResponse, status_code=202)
async def create_podcast_cut_job(
    req: PodcastCutRequest,
    mgr: JobManager = Depends(get_job_manager),
) -> JobCreateResponse:
    _validate_file(req.audio_path, "audio_path")
    if req.srt_path:
        _validate_file(req.srt_path, "srt_path")
    if req.context_path:
        _validate_file(req.context_path, "context_path")
    job = mgr.create_job(JobType.PODCAST_CUT, req.model_dump())
    return JobCreateResponse(job_id=job.id, status=job.status.value, type=job.type.value)


# ------------------------------------------------------------------
# GET — query jobs
# ------------------------------------------------------------------


@router.get("", response_model=list[JobListItem])
async def list_jobs(
    mgr: JobManager = Depends(get_job_manager),
) -> list[JobListItem]:
    return [
        JobListItem(
            job_id=j.id,
            type=j.type.value,
            status=j.status.value,
            created_at=j.created_at,
        )
        for j in mgr.list_jobs()
    ]


@router.get("/{job_id}", response_model=JobStatusResponse)
async def get_job(
    job_id: str,
    mgr: JobManager = Depends(get_job_manager),
) -> JobStatusResponse:
    job = mgr.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    result_resp = None
    if job.result is not None:
        result_resp = JobResultResponse(
            output_files=job.result.output_files,
            summary=job.result.summary,
        )

    return JobStatusResponse(
        job_id=job.id,
        type=job.type.value,
        status=job.status.value,
        progress=job.progress,
        message=job.message,
        result=result_resp,
        error=job.error,
        created_at=job.created_at,
        completed_at=job.completed_at,
    )


@router.get("/{job_id}/files/{name}")
async def download_job_file(
    job_id: str,
    name: str,
    mgr: JobManager = Depends(get_job_manager),
) -> FileResponse:
    job = mgr.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.result is None:
        raise HTTPException(status_code=404, detail="Job has no results yet")

    file_path_str = job.result.output_files.get(name)
    if file_path_str is None:
        raise HTTPException(
            status_code=404,
            detail=f"File '{name}' not found. Available: {list(job.result.output_files)}",
        )

    file_path = Path(file_path_str)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"File no longer exists: {file_path}")

    return FileResponse(path=file_path, filename=file_path.name)
