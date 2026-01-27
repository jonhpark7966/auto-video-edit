"""Codex CLI provider for subtitle analysis."""

import asyncio
import json
import logging
import shutil
import subprocess
from typing import Any

from avid.errors import AIProviderError
from avid.models.ai_analysis import AIAnalysisResult, CutSegment
from avid.models.project import TranscriptSegment

logger = logging.getLogger(__name__)

_CODEX_TIMEOUT_SECONDS = 120

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


class CodexProvider:
    """AI analysis provider using the Codex CLI tool.

    Invokes the ``codex`` binary via subprocess with full-auto approval mode.
    Gracefully handles missing binary by marking itself as unavailable.
    """

    def __init__(self) -> None:
        """Initialize the Codex provider.

        Checks for the ``codex`` binary in PATH using ``shutil.which``.
        """
        self._codex_path = shutil.which("codex")
        self._available = self._codex_path is not None

        if not self._available:
            logger.warning("CodexProvider: 'codex' binary not found in PATH")

    @property
    def name(self) -> str:
        """Provider name identifier."""
        return "codex"

    @property
    def is_available(self) -> bool:
        """Whether the codex binary is available."""
        return self._available

    async def analyze_subtitles(
        self,
        segments: list[TranscriptSegment],
        options: dict[str, Any] | None = None,
    ) -> AIAnalysisResult:
        """Analyze subtitle segments using the Codex CLI.

        Builds a prompt and invokes ``codex --quiet --approval-mode full-auto -p``
        via subprocess, then parses the output for a JSON block.

        Args:
            segments: List of transcript segments to analyze.
            options: Optional settings (unused currently).

        Returns:
            AIAnalysisResult with identified cuts.

        Raises:
            AIProviderError: If the CLI call fails, times out, or output
                cannot be parsed.
        """
        if not self._available:
            raise AIProviderError("Codex provider is not available (binary not found)")

        segments_text = _format_segments(segments)
        prompt = _ANALYSIS_PROMPT.format(segments_text=segments_text)

        cmd = [
            self._codex_path,  # type: ignore[list-item]
            "--quiet",
            "--approval-mode",
            "full-auto",
            "-p",
            prompt,
        ]

        try:
            result = await asyncio.to_thread(
                subprocess.run,
                cmd,
                capture_output=True,
                text=True,
                timeout=_CODEX_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as exc:
            raise AIProviderError(
                f"Codex CLI timed out after {_CODEX_TIMEOUT_SECONDS}s"
            ) from exc
        except OSError as exc:
            raise AIProviderError(f"Codex CLI execution failed: {exc}") from exc

        if result.returncode != 0:
            raise AIProviderError(
                f"Codex CLI returned non-zero exit code {result.returncode}: "
                f"{result.stderr[:500]}"
            )

        return self._parse_response(result.stdout, total_segments=len(segments))

    def _parse_response(
        self, raw_text: str, total_segments: int
    ) -> AIAnalysisResult:
        """Parse Codex CLI output for a JSON block.

        The CLI may emit extra text around the JSON. This method scans for
        the first ``{`` to the last ``}`` to extract the JSON payload.

        Args:
            raw_text: Raw stdout from the Codex CLI.
            total_segments: Total number of segments analyzed.

        Returns:
            Parsed AIAnalysisResult.

        Raises:
            AIProviderError: If no valid JSON block is found.
        """
        text = raw_text.strip()

        # Try to find JSON block in output
        json_start = text.find("{")
        json_end = text.rfind("}")

        if json_start == -1 or json_end == -1 or json_end <= json_start:
            raise AIProviderError(
                f"Codex CLI output contains no JSON block: {text[:500]}"
            )

        json_str = text[json_start : json_end + 1]

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as exc:
            raise AIProviderError(
                f"Codex CLI returned invalid JSON: {exc}\n"
                f"Extracted: {json_str[:500]}"
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
            metadata={"raw_output_length": len(raw_text)},
        )
