"""Claude AI provider for subtitle analysis."""

import json
import logging
import os
from typing import Any

import anthropic

from avid.errors import AIProviderError
from avid.models.ai_analysis import AIAnalysisResult, CutSegment
from avid.models.project import TranscriptSegment

logger = logging.getLogger(__name__)

_ANALYSIS_PROMPT = """\
You are a video editor analyzing Korean subtitle segments for quality issues.

Analyze the following numbered subtitle segments and identify segments that should be CUT from the final video.

Look for:
1. **Duplicate segments** - Repeated or near-identical content (speaker re-stating the same thing)
2. **Incomplete sentences** - Cut off mid-sentence, trailing off without completing a thought
3. **Filler words** - Segments consisting primarily of filler words like "음", "어", "그", "아", "그래서", "이제", "뭐", "약간"

Subtitle segments:
{segments_text}

Respond with ONLY a JSON object in this exact format (no markdown, no extra text):
{{"cuts": [{{"index": <segment_number>, "reason": "duplicate|filler|incomplete"}}]}}

If no segments should be cut, respond with: {{"cuts": []}}
"""


def _format_segments(segments: list[TranscriptSegment]) -> str:
    """Format transcript segments as a numbered list with timestamps.

    Args:
        segments: List of transcript segments.

    Returns:
        Formatted string with numbered segments.
    """
    lines: list[str] = []
    for i, seg in enumerate(segments):
        start_sec = seg.start_ms / 1000.0
        end_sec = seg.end_ms / 1000.0
        lines.append(f"[{i}] ({start_sec:.1f}s - {end_sec:.1f}s): {seg.text}")
    return "\n".join(lines)


class ClaudeProvider:
    """AI analysis provider using the Anthropic Claude API.

    Uses the anthropic Python SDK to send subtitle segments for analysis.
    Gracefully handles missing API keys by marking itself as unavailable
    rather than crashing.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "claude-sonnet-4-20250514",
    ) -> None:
        """Initialize the Claude provider.

        Args:
            api_key: Anthropic API key. Falls back to ANTHROPIC_API_KEY env var.
            model: Claude model to use for analysis.
        """
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self._model = model
        self._available = bool(self._api_key)

        if self._available:
            self._client = anthropic.AsyncAnthropic(api_key=self._api_key)
        else:
            self._client = None
            logger.warning("ClaudeProvider: No API key found, provider unavailable")

    @property
    def name(self) -> str:
        """Provider name identifier."""
        return "claude"

    @property
    def is_available(self) -> bool:
        """Whether the Claude API key is configured."""
        return self._available

    async def analyze_subtitles(
        self,
        segments: list[TranscriptSegment],
        options: dict[str, Any] | None = None,
    ) -> AIAnalysisResult:
        """Analyze subtitle segments using Claude API.

        Sends segments to Claude with a structured prompt asking for
        duplicate, incomplete, and filler word detection.

        Args:
            segments: List of transcript segments to analyze.
            options: Optional settings (unused currently).

        Returns:
            AIAnalysisResult with identified cuts.

        Raises:
            AIProviderError: If the API call fails or response cannot be parsed.
        """
        if not self._available or self._client is None:
            raise AIProviderError("Claude provider is not available (no API key)")

        segments_text = _format_segments(segments)
        prompt = _ANALYSIS_PROMPT.format(segments_text=segments_text)

        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}],
            )
        except anthropic.APIError as exc:
            raise AIProviderError(f"Claude API error: {exc}") from exc

        # Extract text content from response
        raw_text = ""
        for block in response.content:
            if block.type == "text":
                raw_text += block.text

        return self._parse_response(raw_text, total_segments=len(segments))

    def _parse_response(
        self, raw_text: str, total_segments: int
    ) -> AIAnalysisResult:
        """Parse Claude's JSON response into an AIAnalysisResult.

        Args:
            raw_text: Raw text response from Claude.
            total_segments: Total number of segments analyzed.

        Returns:
            Parsed AIAnalysisResult.

        Raises:
            AIProviderError: If the response cannot be parsed as valid JSON.
        """
        # Try to extract JSON from the response (handle markdown code blocks)
        text = raw_text.strip()
        if text.startswith("```"):
            # Strip markdown code fences
            lines = text.split("\n")
            # Remove first line (```json or ```) and last line (```)
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines).strip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise AIProviderError(
                f"Claude returned invalid JSON: {exc}\nRaw response: {raw_text[:500]}"
            ) from exc

        raw_cuts = data.get("cuts", [])
        cut_segments: list[CutSegment] = []
        cut_indices: set[int] = set()

        for item in raw_cuts:
            idx = item.get("index")
            reason = item.get("reason", "unknown")
            if idx is not None and 0 <= idx < total_segments:
                cut_segments.append(
                    CutSegment(
                        segment_index=idx,
                        reason=reason,
                        confidence=1.0,
                        provider=self.name,
                    )
                )
                cut_indices.add(idx)

        keeps = [i for i in range(total_segments) if i not in cut_indices]

        return AIAnalysisResult(
            cuts=cut_segments,
            keeps=keeps,
            provider=self.name,
            metadata={"model": self._model, "raw_response_length": len(raw_text)},
        )
