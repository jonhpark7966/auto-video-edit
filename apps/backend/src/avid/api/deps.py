"""FastAPI dependencies."""

from __future__ import annotations

from avid.jobs.manager import JobManager

_job_manager: JobManager | None = None


def init_job_manager(max_concurrent: int = 2) -> JobManager:
    """Initialize the global JobManager (called at app startup)."""
    global _job_manager
    _job_manager = JobManager(max_concurrent=max_concurrent)
    return _job_manager


def get_job_manager() -> JobManager:
    """Dependency that provides the JobManager instance."""
    if _job_manager is None:
        raise RuntimeError("JobManager not initialized — call init_job_manager() first")
    return _job_manager
