"""Subtitle analysis pipeline stage using multi-AI providers."""

import logging
from typing import Any

from avid.errors import PipelineError
from avid.models.pipeline import StageResult
from avid.models.project import TranscriptSegment
from avid.models.timeline import EditDecision, EditReason, EditType, TimeRange
from avid.pipeline.base import PipelineStage, ProgressCallback
from avid.pipeline.context import PipelineContext
from avid.services.ai_analysis import AIAnalysisService

logger = logging.getLogger(__name__)


class SubtitleAnalysisStage(PipelineStage):
    """Pipeline stage for multi-AI subtitle analysis.

    Analyzes transcription segments using AI providers to identify
    segments that should be cut (duplicates, filler words, etc.).
    """

    @property
    def name(self) -> str:
        return "subtitle_analysis"

    @property
    def display_name(self) -> str:
        return "자막 분석"

    @property
    def description(self) -> str:
        return "멀티 AI 기반 자막 분석"

    async def execute(
        self,
        context: PipelineContext,
        options: dict[str, Any],
        progress_callback: ProgressCallback | None = None,
    ) -> StageResult:
        """Execute subtitle analysis.

        Options:
            providers (list[str]): AI providers to use (e.g., ["claude", "codex"])
            decision_maker (str): Decision strategy (e.g., "majority", "any", "all")

        Args:
            context: Pipeline context with transcription data
            options: Stage-specific configuration
            progress_callback: Optional progress callback

        Returns:
            StageResult with analysis statistics
        """
        self._report_progress(progress_callback, 0.0, "자막 분석 시작...")

        # Get transcription segments from context
        segments = self._get_segments(context)
        if not segments:
            return StageResult.success(
                message="분석할 자막 세그먼트가 없습니다",
                data={"cut_count": 0, "segment_count": 0},
            )

        self._report_progress(progress_callback, 0.1, f"세그먼트 {len(segments)}개 분석 중...")

        # Create AI analysis service and run analysis
        service = AIAnalysisService()
        analysis_result = await service.analyze(
            segments=segments,
            options=options,
        )

        self._report_progress(progress_callback, 0.7, "편집 결정 생성 중...")

        # Convert CutSegments to EditDecisions
        edit_decisions: list[EditDecision] = []
        for cut in analysis_result.cuts:
            # Find the corresponding segment for timing
            if 0 <= cut.segment_index < len(segments):
                seg = segments[cut.segment_index]

                # Map cut reason string to EditReason
                reason = self._map_reason(cut.reason)

                decision = EditDecision(
                    range=TimeRange(
                        start_ms=seg.start_ms,
                        end_ms=seg.end_ms,
                    ),
                    edit_type=EditType.CUT,
                    reason=reason,
                    confidence=cut.confidence,
                )
                edit_decisions.append(decision)

        # Group cuts by reason for stats
        reason_counts: dict[str, int] = {}
        for cut in analysis_result.cuts:
            reason_counts[cut.reason] = reason_counts.get(cut.reason, 0) + 1

        # Store results in context
        context.set_stage_data(
            self.name,
            {
                "edit_decisions": [d.model_dump() for d in edit_decisions],
                "cut_count": analysis_result.cut_count,
                "keep_count": len(analysis_result.keeps),
                "provider": analysis_result.provider,
                "reason_counts": reason_counts,
            },
        )

        self._report_progress(progress_callback, 1.0, "자막 분석 완료")

        logger.info(
            "Subtitle analysis complete: %d cuts from %d segments",
            analysis_result.cut_count,
            len(segments),
        )

        return StageResult.success(
            message=(
                f"자막 분석 완료: {analysis_result.cut_count}개 컷 발견 "
                f"(세그먼트 {len(segments)}개 중)"
            ),
            data={
                "cut_count": analysis_result.cut_count,
                "segment_count": len(segments),
                "keep_count": len(analysis_result.keeps),
                "reason_counts": reason_counts,
                "edit_decision_count": len(edit_decisions),
            },
        )

    async def validate(self, context: PipelineContext) -> bool:
        """Validate that transcription data or SRT exists in context."""
        # Check for transcription data from a previous transcribe stage
        if context.transcription is not None:
            return True

        # Check for transcribe stage data
        transcribe_data = context.get_stage_data("transcribe")
        if transcribe_data and transcribe_data.get("segments"):
            return True

        logger.warning("Validation failed: no transcription or SRT data available")
        return False

    @staticmethod
    def _get_segments(context: PipelineContext) -> list[TranscriptSegment]:
        """Extract TranscriptSegment list from context.

        Checks multiple sources:
        1. context.transcription dict (from TranscribeStage)
        2. context stage_data["transcribe"]["segments"]
        """
        # Try context.transcription dict
        if context.transcription is not None:
            raw_segments = context.transcription.get("segments", [])
            segments: list[TranscriptSegment] = []
            for seg in raw_segments:
                if isinstance(seg, TranscriptSegment):
                    segments.append(seg)
                elif isinstance(seg, dict):
                    segments.append(TranscriptSegment.model_validate(seg))
            return segments

        # Try stage data from transcribe stage
        transcribe_data = context.get_stage_data("transcribe")
        if transcribe_data:
            raw_segments = transcribe_data.get("segments", [])
            segments = []
            for seg in raw_segments:
                if isinstance(seg, TranscriptSegment):
                    segments.append(seg)
                elif isinstance(seg, dict):
                    segments.append(TranscriptSegment.model_validate(seg))
            return segments

        return []

    @staticmethod
    def _map_reason(reason_str: str) -> EditReason:
        """Map AI analysis cut reason string to EditReason enum.

        Args:
            reason_str: Reason string from AI provider

        Returns:
            Corresponding EditReason enum value
        """
        reason_lower = reason_str.lower()
        if "duplicate" in reason_lower or "중복" in reason_lower:
            return EditReason.DUPLICATE
        if "filler" in reason_lower or "필러" in reason_lower:
            return EditReason.FILLER
        if "silence" in reason_lower or "무음" in reason_lower:
            return EditReason.SILENCE
        # Default to MANUAL for unrecognized reasons
        return EditReason.MANUAL
