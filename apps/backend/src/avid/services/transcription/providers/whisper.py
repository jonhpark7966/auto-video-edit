"""Whisper-based transcription provider."""

import asyncio
import logging
from pathlib import Path
from typing import Any

from avid.errors import TranscriptionError
from avid.models.project import TranscriptSegment
from avid.services.transcription.base import TranscriptionResult

logger = logging.getLogger(__name__)

# Common languages supported by Whisper
_SUPPORTED_LANGUAGES = [
    "ko", "en", "ja", "zh", "es", "fr", "de", "it", "pt", "ru",
    "ar", "hi", "th", "vi", "id", "tr", "pl", "nl", "sv",
]


class WhisperProvider:
    """Transcription provider using OpenAI Whisper.

    Supports lazy model loading — the model is loaded on first
    transcription request to avoid unnecessary memory usage.
    """

    def __init__(self, model_name: str = "base") -> None:
        """Initialize WhisperProvider.

        Args:
            model_name: Whisper model size (tiny, base, small, medium, large)
        """
        self.model_name = model_name
        self._model: Any = None

    def _load_model(self) -> None:
        """Load the Whisper model lazily."""
        if self._model is not None:
            return

        try:
            import whisper

            logger.info("Loading Whisper model: %s", self.model_name)
            self._model = whisper.load_model(self.model_name)
            logger.info("Whisper model '%s' loaded successfully", self.model_name)
        except ImportError as e:
            raise TranscriptionError(
                f"whisper package not installed. "
                f"Install with: pip install openai-whisper"
            ) from e
        except Exception as e:
            raise TranscriptionError(
                f"Failed to load Whisper model '{self.model_name}': {e}"
            ) from e

    async def transcribe(
        self,
        audio_path: Path,
        language: str | None = None,
        options: dict[str, Any] | None = None,
    ) -> TranscriptionResult:
        """Transcribe audio using Whisper.

        Args:
            audio_path: Path to the audio file
            language: Optional language code (auto-detect if None)
            options: Optional Whisper-specific options (e.g., task, temperature)

        Returns:
            TranscriptionResult with text, segments, and metadata

        Raises:
            TranscriptionError: If transcription fails
        """
        audio_path = Path(audio_path)
        if not audio_path.exists():
            raise TranscriptionError(f"Audio file not found: {audio_path}")

        # Lazy-load the model
        self._load_model()

        # Build Whisper options
        whisper_opts: dict[str, Any] = {}
        if language is not None:
            whisper_opts["language"] = language
        if options:
            whisper_opts.update(options)

        try:
            logger.info(
                "Transcribing '%s' with Whisper (%s), language=%s",
                audio_path.name,
                self.model_name,
                language or "auto",
            )
            result = await asyncio.to_thread(
                self._model.transcribe, str(audio_path), **whisper_opts
            )
        except Exception as e:
            raise TranscriptionError(
                f"Whisper transcription failed for '{audio_path.name}': {e}"
            ) from e

        return self._convert_result(result)

    @property
    def name(self) -> str:
        """Provider name identifier."""
        return f"whisper-{self.model_name}"

    @property
    def supported_languages(self) -> list[str]:
        """List of supported language codes."""
        return list(_SUPPORTED_LANGUAGES)

    @staticmethod
    def _convert_result(whisper_result: dict[str, Any]) -> TranscriptionResult:
        """Convert Whisper output dict to TranscriptionResult.

        Whisper output format:
            {
                "text": "full text...",
                "segments": [
                    {"start": 0.0, "end": 2.5, "text": "...", "avg_logprob": -0.3, ...},
                    ...
                ],
                "language": "ko"
            }
        """
        segments: list[TranscriptSegment] = []
        total_logprob = 0.0
        segment_count = 0

        for seg in whisper_result.get("segments", []):
            start_ms = int(seg["start"] * 1000)
            end_ms = int(seg["end"] * 1000)
            text = seg.get("text", "").strip()

            # Whisper confidence from avg_logprob (convert log-prob to 0-1)
            avg_logprob = seg.get("avg_logprob", -1.0)
            # Rough heuristic: logprob of 0 = perfect, -1 = poor
            confidence = max(0.0, min(1.0, 1.0 + avg_logprob))

            if text and end_ms > start_ms:
                segments.append(
                    TranscriptSegment(
                        start_ms=start_ms,
                        end_ms=end_ms,
                        text=text,
                        confidence=confidence,
                    )
                )
                total_logprob += avg_logprob
                segment_count += 1

        # Overall confidence
        overall_confidence = 0.0
        if segment_count > 0:
            avg_logprob = total_logprob / segment_count
            overall_confidence = max(0.0, min(1.0, 1.0 + avg_logprob))

        return TranscriptionResult(
            text=whisper_result.get("text", "").strip(),
            segments=segments,
            language=whisper_result.get("language", ""),
            confidence=overall_confidence,
        )
