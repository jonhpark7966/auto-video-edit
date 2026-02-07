"""Request and response schemas for the AVID API."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# ------------------------------------------------------------------
# Job creation requests
# ------------------------------------------------------------------


class TranscribeRequest(BaseModel):
    input_path: str = Field(..., description="Path to video/audio file")
    language: str = Field("ko", description="Language code")


class OverviewRequest(BaseModel):
    srt_path: str = Field(..., description="Path to SRT file")
    content_type: str = Field("auto", description="Content type hint (auto/lecture/podcast)")
    provider: str = Field("codex", description="AI provider (codex/claude)")


class SubtitleCutRequest(BaseModel):
    video_path: str = Field(..., description="Path to video file")
    srt_path: str = Field(..., description="Path to SRT file")
    context_path: str | None = Field(None, description="Path to storyline.json")
    provider: str = Field("codex", description="AI provider")
    export_mode: str = Field("review", description="Export mode (review/final)")


class PodcastCutRequest(BaseModel):
    audio_path: str = Field(..., description="Path to audio/video file")
    srt_path: str | None = Field(None, description="Path to existing SRT file")
    context_path: str | None = Field(None, description="Path to storyline.json")
    provider: str = Field("codex", description="AI provider")
    export_mode: str = Field("review", description="Export mode (review/final)")


# ------------------------------------------------------------------
# Eval request
# ------------------------------------------------------------------


class EvalRequest(BaseModel):
    predicted_path: str = Field(..., description="Path to predicted FCPXML")
    ground_truth_path: str = Field(..., description="Path to ground truth FCPXML")
    threshold_ms: int = Field(200, description="Overlap threshold in ms")


# ------------------------------------------------------------------
# Job responses
# ------------------------------------------------------------------


class JobCreateResponse(BaseModel):
    job_id: str
    status: str
    type: str


class JobResultResponse(BaseModel):
    output_files: dict[str, str] = Field(default_factory=dict)
    summary: dict[str, Any] = Field(default_factory=dict)


class JobStatusResponse(BaseModel):
    job_id: str
    type: str
    status: str
    progress: int = 0
    message: str = ""
    result: JobResultResponse | None = None
    error: str | None = None
    created_at: datetime
    completed_at: datetime | None = None


class JobListItem(BaseModel):
    job_id: str
    type: str
    status: str
    created_at: datetime


# ------------------------------------------------------------------
# Eval response
# ------------------------------------------------------------------


class EvalResponse(BaseModel):
    total_gt_cuts: int
    total_pred_cuts: int
    matched_cuts: int
    missed_cuts: int
    extra_cuts: int
    precision: float
    recall: float
    f1: float
    gt_cut_duration_ms: int
    pred_cut_duration_ms: int
    overlap_duration_ms: int
    timeline_overlap_ratio: float


# ------------------------------------------------------------------
# Media info response
# ------------------------------------------------------------------


class MediaInfoResponse(BaseModel):
    duration_ms: int
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    sample_rate: int | None = None
