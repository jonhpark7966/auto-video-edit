"""Subtitle-based content cut detection pipeline stage.

This stage uses AI (Claude or Codex) to analyze transcription segments
and detect unnecessary content like duplicates, fumbles, and filler words.
"""

import asyncio
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from avid.models.pipeline import StageResult
from avid.models.project import TranscriptSegment
from avid.models.timeline import EditDecision, EditReason, EditType, TimeRange
from avid.pipeline.base import PipelineStage, ProgressCallback
from avid.pipeline.context import PipelineContext


def _segments_to_srt(segments: list[dict]) -> str:
    """Convert transcription segments to SRT format."""
    def ms_to_srt_time(ms: int) -> str:
        hours = ms // 3600000
        minutes = (ms % 3600000) // 60000
        seconds = (ms % 60000) // 1000
        millis = ms % 1000
        return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"

    lines = []
    for i, seg in enumerate(segments, 1):
        lines.append(str(i))
        lines.append(f"{ms_to_srt_time(seg['start_ms'])} --> {ms_to_srt_time(seg['end_ms'])}")
        lines.append(seg["text"])
        lines.append("")

    return "\n".join(lines)


def _reason_to_edit_reason(reason: str) -> EditReason:
    """Convert analyzer reason to EditReason enum."""
    mapping = {
        "duplicate": EditReason.DUPLICATE,
        "incomplete": EditReason.FILLER,
        "filler": EditReason.FILLER,
        "fumble": EditReason.FILLER,
    }
    return mapping.get(reason, EditReason.MANUAL)


class SubtitleCutStage(PipelineStage):
    """Pipeline stage for AI-based subtitle content analysis.

    This stage:
    1. Retrieves transcription segments from the previous stage
    2. Calls AI (Claude or Codex) to analyze content
    3. Creates EditDecision objects for duplicate/filler content
    """

    @property
    def name(self) -> str:
        return "subtitle_cut"

    @property
    def display_name(self) -> str:
        return "자막 기반 편집 (AI)"

    @property
    def description(self) -> str:
        return "AI를 사용하여 중복, 필러, 불완전한 문장을 감지합니다"

    async def validate(self, context: PipelineContext) -> bool:
        """Validate that transcription data is available."""
        if not context.has_stage_completed("transcribe"):
            return False

        transcription_data = context.get_stage_data("transcribe")
        if not transcription_data:
            return False

        transcription = transcription_data.get("transcription", {})
        segments = transcription.get("segments", [])
        return len(segments) > 0

    async def execute(
        self,
        context: PipelineContext,
        options: dict[str, Any],
        progress_callback: ProgressCallback | None = None,
    ) -> StageResult:
        """Execute subtitle-based content analysis.

        Options:
            provider (str): AI provider - "claude" or "codex" (default: "claude")
            edit_type (str): Default edit type - "disabled" or "cut" (default: "disabled")
            keep_alternatives (bool): Keep alternative takes (default: False)

        Args:
            context: Pipeline context with transcription data.
            options: Stage options.
            progress_callback: Progress callback.

        Returns:
            StageResult with edit decisions and analysis report.
        """
        self._report_progress(progress_callback, 0.0, "자막 분석 준비 중")

        # Get options
        provider = options.get("provider", "claude")
        edit_type_str = options.get("edit_type", "disabled")
        keep_alternatives = options.get("keep_alternatives", False)

        # Convert edit_type string to EditType enum
        edit_type = EditType.CUT if edit_type_str == "cut" else EditType.MUTE

        # Get transcription data from previous stage
        transcription_data = context.get_stage_data("transcribe")
        if not transcription_data:
            return StageResult.failure(
                "전사 데이터를 찾을 수 없습니다. 먼저 '음성 인식' 단계를 실행하세요."
            )

        transcription = transcription_data.get("transcription", {})
        segments = transcription.get("segments", [])

        if not segments:
            return StageResult.failure("전사 세그먼트가 없습니다.")

        self._report_progress(progress_callback, 0.1, "SRT 파일 생성 중")

        # Create temporary SRT file
        srt_content = _segments_to_srt(segments)
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".srt", delete=False, encoding="utf-8"
        ) as f:
            f.write(srt_content)
            srt_path = Path(f.name)

        try:
            self._report_progress(progress_callback, 0.2, f"{provider.upper()}로 분석 중")

            # Run the subtitle-cut skill
            result = await self._run_skill(
                srt_path=srt_path,
                provider=provider,
                keep_alternatives=keep_alternatives,
                context=context,
            )

            self._report_progress(progress_callback, 0.7, "편집 결정 생성 중")

            # Convert analysis to edit decisions
            edit_decisions = self._convert_to_edit_decisions(
                result=result,
                segments=segments,
                edit_type=edit_type,
                context=context,
            )

            self._report_progress(progress_callback, 0.9, "결과 저장 중")

            # Calculate statistics
            cut_count = len(edit_decisions)
            total_cut_ms = sum(ed.range.duration_ms for ed in edit_decisions)

            self._report_progress(progress_callback, 1.0, "자막 분석 완료")

            return StageResult.success(
                message=f"자막 분석 완료: {cut_count}개 편집 결정",
                data={
                    "edit_decisions": [ed.model_dump() for ed in edit_decisions],
                    "analysis_report": result,
                    "cut_count": cut_count,
                    "total_cut_ms": total_cut_ms,
                    "provider": provider,
                    "edit_type": edit_type_str,
                },
            )

        finally:
            # Clean up temp file
            srt_path.unlink(missing_ok=True)

    async def _run_skill(
        self,
        srt_path: Path,
        provider: str,
        keep_alternatives: bool,
        context: PipelineContext,
    ) -> dict:
        """Run the subtitle-cut skill and return analysis result.

        This runs the skill script directly using subprocess.
        """
        # Build skill command
        skill_dir = Path(__file__).parent.parent.parent.parent.parent.parent.parent / "skills" / "subtitle-cut"

        # Get video path if available
        video_path = "dummy.mp4"
        if context.video_file:
            video_path = str(context.video_file.path)

        cmd = [
            "python",
            str(skill_dir / "main.py"),
            str(srt_path),
            video_path,
            "--provider", provider,
            "--report-only",
        ]

        if keep_alternatives:
            cmd.append("--keep-alternatives")

        # Run skill
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=180,
                cwd=str(skill_dir),
            ),
        )

        if result.returncode != 0:
            raise RuntimeError(f"Subtitle-cut skill failed: {result.stderr}")

        # Parse the output - we need to call the analyzer directly for structured output
        return await self._analyze_directly(srt_path, provider, keep_alternatives)

    async def _analyze_directly(
        self,
        srt_path: Path,
        provider: str,
        keep_alternatives: bool,
    ) -> dict:
        """Analyze subtitles directly using the skill's analyzers.

        This imports and calls the analyzer functions directly for structured output.
        """
        import sys

        # Add skills directory to path temporarily
        skill_dir = Path(__file__).parent.parent.parent.parent.parent.parent.parent / "skills" / "subtitle-cut"
        sys.path.insert(0, str(skill_dir))

        try:
            from srt_parser import parse_srt_file
            if provider == "codex":
                from codex_analyzer import analyze_with_codex as analyze
            else:
                from claude_analyzer import analyze_with_claude as analyze

            # Parse SRT
            segments = parse_srt_file(str(srt_path))

            # Run analysis
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: analyze(segments, keep_alternatives=keep_alternatives),
            )

            return {
                "cuts": result.cuts,
                "keeps": result.keeps,
                "raw_response": result.raw_response,
            }

        finally:
            sys.path.remove(str(skill_dir))

    def _convert_to_edit_decisions(
        self,
        result: dict,
        segments: list[dict],
        edit_type: EditType,
        context: PipelineContext,
    ) -> list[EditDecision]:
        """Convert analyzer result to EditDecision objects."""
        # Create segment lookup by index
        segment_map = {}
        for i, seg in enumerate(segments, 1):
            segment_map[i] = seg

        edit_decisions = []

        # Get track IDs if available
        video_track_id = None
        audio_track_ids = []

        if context.video_file:
            # Use simple ID generation based on file path
            import uuid
            file_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, str(context.video_file.path)))
            video_track_id = f"{file_id}_video"
            audio_track_ids = [f"{file_id}_audio"]

        for cut in result.get("cuts", []):
            seg_idx = cut.get("segment_index")
            seg = segment_map.get(seg_idx)
            if not seg:
                continue

            reason = _reason_to_edit_reason(cut.get("reason", "manual"))
            note = cut.get("note", "")

            edit_decision = EditDecision(
                range=TimeRange(
                    start_ms=seg["start_ms"],
                    end_ms=seg["end_ms"],
                ),
                edit_type=edit_type,
                reason=reason,
                confidence=0.9,
                note=note,
                active_video_track_id=video_track_id,
                active_audio_track_ids=audio_track_ids,
                speed_factor=1.0,
            )
            edit_decisions.append(edit_decision)

        return edit_decisions
