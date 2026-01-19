"""Track-related data models."""

from enum import Enum

from pydantic import BaseModel, Field


class TrackType(str, Enum):
    """Type of media track."""

    VIDEO = "video"
    AUDIO = "audio"


class Track(BaseModel):
    """A single track extracted from a source file.

    When a video file is imported, it becomes two tracks:
    - One video track
    - One audio track (if audio exists)

    Audio-only files become a single audio track.
    """

    id: str = Field(..., description="Unique track identifier (e.g., 'v1_video', 'v1_audio')")
    source_file_id: str = Field(..., description="ID of the source MediaFile")
    track_type: TrackType = Field(..., description="Type of track (video/audio)")
    offset_ms: int = Field(default=0, description="Sync offset in milliseconds")

    @property
    def is_video(self) -> bool:
        """Check if this is a video track."""
        return self.track_type == TrackType.VIDEO

    @property
    def is_audio(self) -> bool:
        """Check if this is an audio track."""
        return self.track_type == TrackType.AUDIO
