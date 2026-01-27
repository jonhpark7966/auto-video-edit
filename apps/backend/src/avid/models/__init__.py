"""Data models for AVID."""

from avid.models.ai_analysis import AIAnalysisResult, CutSegment
from avid.models.media import MediaFile, MediaInfo
from avid.models.pipeline import PipelineConfig, StageResult
from avid.models.project import Project, Transcription, TranscriptSegment
from avid.models.silence import SilenceDetectionResult, SilenceRegion
from avid.models.timeline import EditDecision, EditReason, EditType, TimeRange
from avid.models.track import Track, TrackType

__all__ = [
    # Media
    "MediaInfo",
    "MediaFile",
    # Track
    "Track",
    "TrackType",
    # Timeline
    "TimeRange",
    "EditType",
    "EditReason",
    "EditDecision",
    # Project
    "Project",
    "Transcription",
    "TranscriptSegment",
    # Pipeline
    "StageResult",
    "PipelineConfig",
    # Silence
    "SilenceRegion",
    "SilenceDetectionResult",
    # AI Analysis
    "AIAnalysisResult",
    "CutSegment",
]
