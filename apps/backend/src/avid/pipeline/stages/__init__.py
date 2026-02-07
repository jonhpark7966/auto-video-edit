"""Pipeline stages module.

Available stages:
- TranscriptionStage: Speech-to-text transcription using Chalna API
- SubtitleCutStage: AI-based content analysis (duplicates, fillers, etc.)
- SyncStage: Video/Audio sync (to be implemented)
"""

from avid.pipeline.stages.subtitle_cut import SubtitleCutStage
from avid.pipeline.stages.transcription import TranscriptionStage

__all__ = [
    "TranscriptionStage",
    "SubtitleCutStage",
]
