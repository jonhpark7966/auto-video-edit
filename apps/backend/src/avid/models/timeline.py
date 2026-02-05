"""Timeline and editing-related data models."""

from enum import Enum

from pydantic import BaseModel, Field, model_validator


class EditType(str, Enum):
    """Type of edit to apply."""

    CUT = "cut"
    SPEEDUP = "speedup"
    MUTE = "mute"


class EditReason(str, Enum):
    """Reason for the edit."""

    SILENCE = "silence"
    DUPLICATE = "duplicate"
    FILLER = "filler"
    MANUAL = "manual"


class TimeRange(BaseModel):
    """Time range in milliseconds."""

    start_ms: int = Field(..., ge=0, description="Start time in milliseconds")
    end_ms: int = Field(..., ge=0, description="End time in milliseconds")

    @model_validator(mode="after")
    def validate_range(self) -> "TimeRange":
        """Ensure end is after start."""
        if self.end_ms <= self.start_ms:
            raise ValueError("end_ms must be greater than start_ms")
        return self

    @property
    def duration_ms(self) -> int:
        """Return duration in milliseconds."""
        return self.end_ms - self.start_ms

    @property
    def duration_seconds(self) -> float:
        """Return duration in seconds."""
        return self.duration_ms / 1000.0

    def overlaps(self, other: "TimeRange") -> bool:
        """Check if this range overlaps with another."""
        return self.start_ms < other.end_ms and other.start_ms < self.end_ms

    def contains(self, timestamp_ms: int) -> bool:
        """Check if a timestamp falls within this range."""
        return self.start_ms <= timestamp_ms < self.end_ms


class EditDecision(BaseModel):
    """A single editing decision for a time range on the unified timeline.

    This represents what happens at a specific time range:
    - Which video track is active (or None for cut)
    - Which audio tracks are active
    - Speed factor for speedup
    - Reason for the edit (silence, duplicate, manual, etc.)
    """

    range: TimeRange = Field(..., description="Target time range on unified timeline")
    edit_type: EditType = Field(..., description="Type of edit to apply")
    reason: EditReason = Field(..., description="Reason for this edit")
    confidence: float = Field(
        default=1.0, ge=0.0, le=1.0, description="Confidence score for automatic detection"
    )
    note: str | None = Field(
        default=None,
        description="Detailed edit reason (e.g., 'segment 7의 인트로가 더 완성도 높음')",
    )

    # Active tracks for this segment
    active_video_track_id: str | None = Field(
        default=None, description="Active video track ID (None = no video / cut)"
    )
    active_audio_track_ids: list[str] = Field(
        default_factory=list, description="Active audio track IDs (can mix multiple)"
    )

    # Speed control
    speed_factor: float = Field(
        default=1.0, gt=0.0, description="Speed factor (1.0 = normal, 2.0 = 2x speed)"
    )
