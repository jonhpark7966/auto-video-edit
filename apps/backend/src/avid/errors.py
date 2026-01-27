"""Custom exceptions for AVID."""


class AVIDError(Exception):
    """Base exception for AVID."""

    pass


class FFmpegError(AVIDError):
    """FFmpeg execution failed."""

    pass


class SRTParseError(AVIDError):
    """SRT file parsing failed."""

    pass


class AIProviderError(AVIDError):
    """AI provider call failed."""

    pass


class TranscriptionError(AVIDError):
    """Transcription failed."""

    pass


class PipelineError(AVIDError):
    """Pipeline execution failed."""

    pass
