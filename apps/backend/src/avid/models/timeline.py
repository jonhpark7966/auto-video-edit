"""Timeline and editing-related data models."""

from enum import Enum

from pydantic import BaseModel, Field, model_validator

from avid.models.media import MediaFile


class EditType(str, Enum):
    """Type of edit to apply."""

    CUT = "cut"
    SPEEDUP = "speedup"
    MUTE = "mute"


class EditReason(str, Enum):
    """Reason for the edit."""

    SILENCE = "silence"
    DUPLICATE = "duplicate"
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
    """A single editing decision for a time range."""

    range: TimeRange = Field(..., description="Target time range")
    edit_type: EditType = Field(..., description="Type of edit to apply")
    reason: EditReason = Field(..., description="Reason for this edit")
    confidence: float = Field(
        ..., ge=0.0, le=1.0, description="Confidence score for automatic detection"
    )


class Timeline(BaseModel):
    """Complete editing timeline for a media file."""

    source_media: MediaFile = Field(..., description="Source media file")
    edit_decisions: list[EditDecision] = Field(
        default_factory=list, description="List of edit decisions"
    )

    @property
    def duration_ms(self) -> int:
        """Return original source duration."""
        return self.source_media.info.duration_ms

    @property
    def edited_duration_ms(self) -> int:
        """Calculate duration after applying cut edits."""
        cut_duration = sum(
            ed.range.duration_ms
            for ed in self.edit_decisions
            if ed.edit_type == EditType.CUT
        )
        return self.duration_ms - cut_duration

    def get_decisions_at(self, timestamp_ms: int) -> list[EditDecision]:
        """Get all edit decisions that apply to a specific timestamp."""
        return [ed for ed in self.edit_decisions if ed.range.contains(timestamp_ms)]

    def add_decision(self, decision: EditDecision) -> None:
        """Add an edit decision to the timeline."""
        self.edit_decisions.append(decision)

    def remove_decision(self, index: int) -> EditDecision | None:
        """Remove and return an edit decision by index."""
        if 0 <= index < len(self.edit_decisions):
            return self.edit_decisions.pop(index)
        return None
