"""Base interface for AI analysis providers."""

from typing import Any, Protocol

from avid.models.ai_analysis import AIAnalysisResult
from avid.models.project import TranscriptSegment


class IAIProvider(Protocol):
    """Protocol defining the contract for AI analysis providers.

    Each provider must be able to analyze subtitle segments and report
    its name and availability status.
    """

    async def analyze_subtitles(
        self,
        segments: list[TranscriptSegment],
        options: dict[str, Any] | None = None,
    ) -> AIAnalysisResult:
        """Analyze subtitle segments for cuts.

        Args:
            segments: List of transcript segments to analyze.
            options: Optional provider-specific options.

        Returns:
            AIAnalysisResult with identified cuts.
        """
        ...

    @property
    def name(self) -> str:
        """Provider name identifier."""
        ...

    @property
    def is_available(self) -> bool:
        """Whether this provider is currently available."""
        ...
