"""Job domain models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4


class JobStatus(str, Enum):
    """Status of a job."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class JobType(str, Enum):
    """Type of job."""

    TRANSCRIBE = "transcribe"
    TRANSCRIPT_OVERVIEW = "transcript_overview"
    SUBTITLE_CUT = "subtitle_cut"
    PODCAST_CUT = "podcast_cut"


@dataclass
class JobResult:
    """Result of a completed job."""

    output_files: dict[str, str] = field(default_factory=dict)
    summary: dict[str, Any] = field(default_factory=dict)


@dataclass
class Job:
    """A background processing job."""

    id: str = field(default_factory=lambda: str(uuid4()))
    type: JobType = JobType.TRANSCRIBE
    status: JobStatus = JobStatus.PENDING
    progress: int = 0
    message: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    result: JobResult | None = None
    error: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
