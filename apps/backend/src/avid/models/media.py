"""Media-related data models."""

from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, Field


class MediaInfo(BaseModel):
    """Media file metadata."""

    duration_ms: int = Field(..., description="Total duration in milliseconds")
    width: int | None = Field(None, description="Video width in pixels")
    height: int | None = Field(None, description="Video height in pixels")
    fps: float | None = Field(None, description="Frames per second")
    sample_rate: int | None = Field(None, description="Audio sample rate in Hz")

    @property
    def duration_seconds(self) -> float:
        """Return duration in seconds."""
        return self.duration_ms / 1000.0

    @property
    def resolution(self) -> str | None:
        """Return resolution string (e.g., '1920x1080')."""
        if self.width and self.height:
            return f"{self.width}x{self.height}"
        return None


class MediaFile(BaseModel):
    """Media file reference with metadata."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    path: Path = Field(..., description="File path")
    original_name: str = Field(..., description="Original file name")
    info: MediaInfo = Field(..., description="Media metadata")

    @property
    def extension(self) -> str:
        """Return file extension without dot."""
        return self.path.suffix.lstrip(".")

    @property
    def is_video(self) -> bool:
        """Check if this is a video file (has dimensions)."""
        return self.info.width is not None and self.info.height is not None

    @property
    def is_audio_only(self) -> bool:
        """Check if this is an audio-only file."""
        return not self.is_video and self.info.sample_rate is not None
