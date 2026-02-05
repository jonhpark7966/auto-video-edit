"""Pipeline stages module.

Available stages:
- TranscriptionStage: Speech-to-text transcription using Chalna API
- SilenceStage: Silence detection based on subtitle gaps
- SubtitleCutStage: AI-based content analysis (duplicates, fillers, etc.)
- SyncStage: Video/Audio sync (to be implemented)
"""

from avid.pipeline.stages.silence import SilenceStage, detect_silence_from_segments
from avid.pipeline.stages.subtitle_cut import SubtitleCutStage
from avid.pipeline.stages.transcription import TranscriptionStage

__all__ = [
    "TranscriptionStage",
    "SilenceStage",
    "SubtitleCutStage",
    "detect_silence_from_segments",
]
