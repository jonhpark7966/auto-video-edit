"""Silence detection data models."""

from pydantic import BaseModel, Field

from avid.models.timeline import TimeRange


class SilenceRegion(TimeRange):
    """A detected silent region with metadata."""

    source: str = Field(
        ..., description="Detection source: 'ffmpeg', 'srt', or 'combined'"
    )
    confidence: float = Field(
        default=1.0, ge=0.0, le=1.0, description="Detection confidence"
    )


class SilenceDetectionResult(BaseModel):
    """Result of silence detection analysis."""

    silence_regions: list[SilenceRegion] = Field(
        default_factory=list, description="Detected silence regions"
    )
    ffmpeg_regions: list[SilenceRegion] = Field(
        default_factory=list, description="FFmpeg-only results (debug)"
    )
    srt_gaps: list[SilenceRegion] = Field(
        default_factory=list, description="SRT gap results (debug)"
    )
    total_duration_ms: int = Field(
        default=0, description="Total media duration in ms"
    )

    @property
    def silence_duration_ms(self) -> int:
        """Total duration of all silence regions."""
        return sum(r.duration_ms for r in self.silence_regions)

    @property
    def silence_ratio(self) -> float:
        """Ratio of silence to total duration."""
        if self.total_duration_ms == 0:
            return 0.0
        return self.silence_duration_ms / self.total_duration_ms

    @property
    def count(self) -> int:
        """Number of silence regions."""
        return len(self.silence_regions)
