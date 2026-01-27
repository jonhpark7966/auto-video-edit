"""Base interface for transcription providers."""

from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, Field

from avid.models.project import TranscriptSegment


class TranscriptionResult(BaseModel):
    """Result from transcription."""

    text: str = Field(..., description="Full transcription text")
    segments: list[TranscriptSegment] = Field(default_factory=list)
    language: str = Field(default="", description="Detected language")
    confidence: float = Field(default=0.0)


class ITranscriptionProvider(Protocol):
    """Protocol for transcription providers.

    Each provider implements a specific transcription backend
    (e.g., Whisper local, Whisper API, etc.).
    """

    async def transcribe(
        self,
        audio_path: Path,
        language: str | None = None,
        options: dict[str, Any] | None = None,
    ) -> TranscriptionResult:
        """Transcribe audio to text with timestamps.

        Args:
            audio_path: Path to audio file
            language: Optional language code (auto-detect if None)
            options: Optional provider-specific options

        Returns:
            TranscriptionResult with text, segments, and metadata
        """
        ...

    @property
    def name(self) -> str:
        """Provider name identifier."""
        ...

    @property
    def supported_languages(self) -> list[str]:
        """List of supported language codes."""
        ...
