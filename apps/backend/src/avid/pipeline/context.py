"""Pipeline execution context."""

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from avid.models.media import MediaFile
from avid.models.timeline import Timeline


class PipelineContext(BaseModel):
    """Shared context for pipeline execution.

    This context is passed between stages and accumulates
    results as the pipeline progresses.
    """

    video_file: MediaFile | None = Field(None, description="Input video file")
    audio_file: MediaFile | None = Field(None, description="Input audio file (for separate audio)")
    srt_path: Path | None = Field(None, description="Input SRT subtitle file path")

    timeline: Timeline | None = Field(None, description="Current editing timeline")
    transcription: dict[str, Any] | None = Field(None, description="Transcription result")

    working_dir: Path = Field(..., description="Working directory for temp files")
    output_dir: Path = Field(..., description="Output directory")

    stage_data: dict[str, dict[str, Any]] = Field(
        default_factory=dict, description="Data from completed stages"
    )

    def get_primary_media(self) -> MediaFile | None:
        """Get the primary media file (video or audio)."""
        return self.video_file or self.audio_file

    def set_stage_data(self, stage_name: str, data: dict[str, Any]) -> None:
        """Store data from a completed stage."""
        self.stage_data[stage_name] = data

    def get_stage_data(self, stage_name: str) -> dict[str, Any] | None:
        """Retrieve data from a completed stage."""
        return self.stage_data.get(stage_name)

    def has_stage_completed(self, stage_name: str) -> bool:
        """Check if a stage has completed and stored data."""
        return stage_name in self.stage_data
