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
    audio_channels: int | None = Field(None, description="Total number of audio channels")
    audio_sources: int | None = Field(None, description="Number of audio streams/sources")
    video_frame_count: int | None = Field(None, description="Video stream frame count")
    frame_duration: str | None = Field(
        None,
        description="Video frame duration as rational seconds, e.g. 1001/30000",
    )
    video_duration: str | None = Field(None, description="Video duration as rational seconds")
    audio_sample_rate: int | None = Field(None, description="Audio stream sample rate in Hz")
    audio_sample_count: int | None = Field(None, description="Audio stream sample count")
    start_time: str | None = Field(None, description="Container or stream start time")
    time_base: str | None = Field(None, description="Video stream time base")
    timecode: str | None = Field(None, description="Embedded source timecode, e.g. 21:01:07:00")
    timecode_rate: str | None = Field(None, description="Timecode rate as a rational, e.g. 30000/1001")
    timecode_start_frames: int | None = Field(None, description="Source timecode start as labelled frames")
    timecode_start_seconds: str | None = Field(None, description="Source timecode start as rational seconds")

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

    @property
    def has_audio(self) -> bool:
        """Check if metadata indicates an audio stream is present."""
        return (
            self.sample_rate is not None
            or (self.audio_channels or 0) > 0
            or (self.audio_sources or 0) > 0
        )


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
        return not self.is_video and self.info.has_audio
