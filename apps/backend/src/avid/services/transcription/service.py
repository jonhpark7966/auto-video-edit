"""Transcription service with provider management."""

import logging
from pathlib import Path
from typing import Any

from avid.errors import TranscriptionError
from avid.services.transcription.base import TranscriptionResult
from avid.services.transcription.providers.whisper import WhisperProvider

logger = logging.getLogger(__name__)

# Available Whisper model sizes
_WHISPER_MODEL_SIZES = ["tiny", "base", "small", "medium", "large"]


class TranscriptionService:
    """Transcription service with pluggable providers.

    Manages multiple transcription providers and provides a unified
    interface for transcription, provider selection, and SRT export.
    """

    def __init__(self, default_provider: str = "whisper-base") -> None:
        """Initialize the transcription service.

        Automatically registers WhisperProvider instances for all model sizes.

        Args:
            default_provider: Name of the default provider to use
        """
        self._providers: dict[str, WhisperProvider] = {}
        self._default_provider = default_provider

        # Auto-register Whisper providers for each model size
        for model_size in _WHISPER_MODEL_SIZES:
            provider = WhisperProvider(model_name=model_size)
            self._providers[provider.name] = provider

        logger.info(
            "TranscriptionService initialized with %d providers, default=%s",
            len(self._providers),
            self._default_provider,
        )

    async def transcribe(
        self,
        audio_path: Path,
        provider_name: str | None = None,
        language: str | None = None,
        options: dict[str, Any] | None = None,
    ) -> TranscriptionResult:
        """Transcribe audio using the specified or default provider.

        Args:
            audio_path: Path to the audio file
            provider_name: Provider name (e.g., "whisper-base"). Uses default if None.
            language: Optional language code (auto-detect if None)
            options: Optional provider-specific options

        Returns:
            TranscriptionResult with text, segments, and metadata

        Raises:
            TranscriptionError: If provider not found or transcription fails
        """
        name = provider_name or self._default_provider
        provider = self._providers.get(name)

        if provider is None:
            available = ", ".join(self._providers.keys())
            raise TranscriptionError(
                f"Unknown transcription provider '{name}'. "
                f"Available: {available}"
            )

        logger.info(
            "Transcribing '%s' with provider '%s'",
            audio_path.name if isinstance(audio_path, Path) else audio_path,
            name,
        )

        return await provider.transcribe(audio_path, language=language, options=options)

    def list_providers(self) -> list[str]:
        """List all registered provider names.

        Returns:
            List of provider name strings
        """
        return list(self._providers.keys())

    @staticmethod
    def export_srt(result: TranscriptionResult, output_path: Path) -> Path:
        """Export transcription result as an SRT subtitle file.

        Args:
            result: TranscriptionResult to export
            output_path: Path for the output SRT file

        Returns:
            Path to the written SRT file

        Raises:
            TranscriptionError: If export fails
        """
        output_path = Path(output_path)
        if not output_path.suffix:
            output_path = output_path.with_suffix(".srt")

        try:
            lines: list[str] = []
            for i, segment in enumerate(result.segments, start=1):
                start_srt = _ms_to_srt_time(segment.start_ms)
                end_srt = _ms_to_srt_time(segment.end_ms)
                lines.append(str(i))
                lines.append(f"{start_srt} --> {end_srt}")
                lines.append(segment.text)
                lines.append("")  # blank line between entries

            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text("\n".join(lines), encoding="utf-8")

            logger.info(
                "Exported SRT with %d segments to '%s'",
                len(result.segments),
                output_path,
            )
            return output_path

        except Exception as e:
            raise TranscriptionError(f"Failed to export SRT: {e}") from e


def _ms_to_srt_time(ms: int) -> str:
    """Convert milliseconds to SRT time format (HH:MM:SS,mmm).

    Args:
        ms: Time in milliseconds

    Returns:
        SRT-formatted time string
    """
    hours = ms // 3_600_000
    ms %= 3_600_000
    minutes = ms // 60_000
    ms %= 60_000
    seconds = ms // 1_000
    milliseconds = ms % 1_000
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"
