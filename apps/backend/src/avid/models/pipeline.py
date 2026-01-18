"""Pipeline-related data models."""

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class StageStatus(str, Enum):
    """Status of a pipeline stage execution."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class StageResult(BaseModel):
    """Result of a pipeline stage execution."""

    status: StageStatus = Field(..., description="Execution status")
    message: str | None = Field(None, description="Status message or error description")
    data: dict[str, Any] | None = Field(None, description="Stage output data")

    @classmethod
    def success(cls, message: str | None = None, data: dict[str, Any] | None = None) -> "StageResult":
        """Create a successful result."""
        return cls(status=StageStatus.COMPLETED, message=message, data=data)

    @classmethod
    def failure(cls, message: str, data: dict[str, Any] | None = None) -> "StageResult":
        """Create a failed result."""
        return cls(status=StageStatus.FAILED, message=message, data=data)

    @classmethod
    def skipped(cls, message: str | None = None) -> "StageResult":
        """Create a skipped result."""
        return cls(status=StageStatus.SKIPPED, message=message, data=None)


class PipelineConfig(BaseModel):
    """Configuration for a pipeline execution."""

    stages: list[str] = Field(
        default_factory=list, description="List of stage names to execute"
    )
    stage_options: dict[str, dict[str, Any]] = Field(
        default_factory=dict, description="Options for each stage"
    )

    def get_stage_options(self, stage_name: str) -> dict[str, Any]:
        """Get options for a specific stage."""
        return self.stage_options.get(stage_name, {})
