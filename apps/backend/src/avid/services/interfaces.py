"""Service interfaces (Protocols) for AVID.

These protocols define the contracts that service implementations must follow.
This allows for easy swapping of implementations and better testability.
"""

from pathlib import Path
from typing import Any, Protocol

from avid.models.media import MediaFile, MediaInfo
from avid.models.timeline import TimeRange


class IMediaService(Protocol):
    """Interface for media operations (FFmpeg wrapper)."""

    async def get_media_info(self, path: Path) -> MediaInfo:
        """Extract media information from a file.

        Args:
            path: Path to the media file

        Returns:
            MediaInfo with duration, resolution, fps, etc.
        """
        ...

    async def extract_audio(
        self,
        input_path: Path,
        output_path: Path,
        sample_rate: int = 16000,
    ) -> Path:
        """Extract audio from a video file.

        Args:
            input_path: Path to input video
            output_path: Path for output audio
            sample_rate: Target sample rate

        Returns:
            Path to the extracted audio file
        """
        ...

    async def trim_media(
        self,
        input_path: Path,
        output_path: Path,
        start_ms: int,
        end_ms: int,
    ) -> Path:
        """Trim media to a specific time range.

        Args:
            input_path: Path to input file
            output_path: Path for output file
            start_ms: Start time in milliseconds
            end_ms: End time in milliseconds

        Returns:
            Path to the trimmed file
        """
        ...


class ITranscriptionService(Protocol):
    """Interface for speech-to-text transcription (Whisper wrapper)."""

    async def transcribe(
        self,
        audio_path: Path,
        language: str | None = None,
    ) -> dict[str, Any]:
        """Transcribe audio to text with timestamps.

        Args:
            audio_path: Path to audio file
            language: Optional language code (auto-detect if None)

        Returns:
            Dictionary with:
            - text: Full transcription text
            - segments: List of {start, end, text} segments
            - language: Detected or specified language
        """
        ...


class IAudioAnalyzer(Protocol):
    """Interface for audio analysis operations."""

    async def detect_silence(
        self,
        audio_path: Path,
        min_silence_ms: int = 500,
        silence_threshold_db: float = -40.0,
    ) -> list[TimeRange]:
        """Detect silent sections in audio.

        Args:
            audio_path: Path to audio file
            min_silence_ms: Minimum silence duration to detect
            silence_threshold_db: Volume threshold for silence

        Returns:
            List of TimeRange objects for silent sections
        """
        ...

    async def get_volume_levels(
        self,
        audio_path: Path,
        window_ms: int = 100,
    ) -> list[tuple[int, float]]:
        """Get volume levels over time.

        Args:
            audio_path: Path to audio file
            window_ms: Analysis window size in milliseconds

        Returns:
            List of (timestamp_ms, volume_db) tuples
        """
        ...


class ITextAnalyzer(Protocol):
    """Interface for text analysis operations."""

    def detect_duplicates(
        self,
        segments: list[dict[str, Any]],
        similarity_threshold: float = 0.8,
    ) -> list[tuple[int, int]]:
        """Detect duplicate or similar text segments.

        Args:
            segments: List of transcript segments with text
            similarity_threshold: Minimum similarity to consider duplicate

        Returns:
            List of (original_index, duplicate_index) tuples
        """
        ...

    def detect_filler_words(
        self,
        segments: list[dict[str, Any]],
        filler_patterns: list[str] | None = None,
    ) -> list[int]:
        """Detect filler words in segments.

        Args:
            segments: List of transcript segments
            filler_patterns: Custom filler patterns (default: common fillers)

        Returns:
            List of segment indices containing filler words
        """
        ...
