"""AI analysis data models."""

from typing import Any

from pydantic import BaseModel, Field


class CutSegment(BaseModel):
    """A segment identified for cutting by AI analysis."""

    segment_index: int = Field(..., description="Index of the subtitle segment")
    reason: str = Field(..., description="Reason for cut (duplicate, filler, incomplete)")
    confidence: float = Field(
        default=1.0, ge=0.0, le=1.0, description="AI confidence"
    )
    provider: str = Field(default="", description="Which AI provider identified this")


class AIAnalysisResult(BaseModel):
    """Result from a single AI provider or aggregated result."""

    cuts: list[CutSegment] = Field(
        default_factory=list, description="Segments to cut"
    )
    keeps: list[int] = Field(
        default_factory=list, description="Segment indices to keep"
    )
    provider: str = Field(default="", description="Provider name")
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Additional metadata"
    )

    @property
    def cut_count(self) -> int:
        """Number of segments to cut."""
        return len(self.cuts)

    @property
    def cut_indices(self) -> set[int]:
        """Set of segment indices to cut."""
        return {c.segment_index for c in self.cuts}
