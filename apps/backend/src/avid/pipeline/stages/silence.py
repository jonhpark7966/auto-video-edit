"""Silence detection pipeline stage."""

import logging
from typing import Any

from avid.errors import PipelineError
from avid.models.pipeline import StageResult
from avid.models.timeline import EditDecision, EditReason, EditType, TimeRange
from avid.pipeline.base import PipelineStage, ProgressCallback
from avid.pipeline.context import PipelineContext
from avid.services.audio_analyzer import AudioAnalyzer

logger = logging.getLogger(__name__)


class SilenceStage(PipelineStage):
    """Pipeline stage for silence detection using FFmpeg and SRT analysis.

    Detects silent regions in audio and converts them to CUT edit decisions.
    Optionally combines FFmpeg-based detection with SRT subtitle gap analysis.
    """

    @property
    def name(self) -> str:
        return "silence"

    @property
    def display_name(self) -> str:
        return "무음 감지"

    @property
    def description(self) -> str:
        return "FFmpeg + SRT 기반 무음 구간 감지"

    async def execute(
        self,
        context: PipelineContext,
        options: dict[str, Any],
        progress_callback: ProgressCallback | None = None,
    ) -> StageResult:
        """Execute silence detection.

        Options:
            min_silence_ms (int): Minimum silence duration in ms (default: 500)
            silence_threshold_db (float): Volume threshold in dB (default: -40.0)
            padding_ms (int): Padding around region boundaries in ms (default: 100)
            tight_mode (bool): Use intersection mode for combined detection (default: True)
            srt_path (str): Optional path to SRT file for gap analysis

        Args:
            context: Pipeline context with media files
            options: Stage-specific configuration
            progress_callback: Optional progress callback

        Returns:
            StageResult with silence detection statistics
        """
        self._report_progress(progress_callback, 0.0, "무음 감지 시작...")

        # Get audio path from primary media
        primary_media = context.get_primary_media()
        if primary_media is None:
            raise PipelineError("No media file available for silence detection")

        audio_path = primary_media.path

        # Get optional SRT path
        srt_path_str = options.get("srt_path")
        srt_path = None
        if srt_path_str:
            from pathlib import Path
            srt_path = Path(srt_path_str)

        self._report_progress(progress_callback, 0.1, "오디오 분석 중...")

        # Create analyzer and run detection
        analyzer = AudioAnalyzer()
        result = await analyzer.detect_silence(
            audio_path=audio_path,
            srt_path=srt_path,
            min_silence_ms=options.get("min_silence_ms", 500),
            silence_threshold_db=options.get("silence_threshold_db", -40.0),
            padding_ms=options.get("padding_ms", 100),
            tight_mode=options.get("tight_mode", True),
        )

        self._report_progress(progress_callback, 0.7, "편집 결정 생성 중...")

        # Convert SilenceRegions to EditDecisions
        edit_decisions: list[EditDecision] = []
        for region in result.silence_regions:
            decision = EditDecision(
                range=TimeRange(
                    start_ms=region.start_ms,
                    end_ms=region.end_ms,
                ),
                edit_type=EditType.CUT,
                reason=EditReason.SILENCE,
                confidence=region.confidence,
            )
            edit_decisions.append(decision)

        # Store edit decisions in context stage data
        context.set_stage_data(
            self.name,
            {
                "edit_decisions": [d.model_dump() for d in edit_decisions],
                "silence_count": result.count,
                "silence_duration_ms": result.silence_duration_ms,
                "total_duration_ms": result.total_duration_ms,
                "silence_ratio": result.silence_ratio,
            },
        )

        self._report_progress(progress_callback, 1.0, "무음 감지 완료")

        logger.info(
            "Silence detection complete: %d regions, %.1f%% silence ratio",
            result.count,
            result.silence_ratio * 100,
        )

        return StageResult.success(
            message=(
                f"무음 구간 {result.count}개 감지 "
                f"(총 {result.silence_duration_ms / 1000:.1f}초, "
                f"{result.silence_ratio * 100:.1f}%)"
            ),
            data={
                "silence_count": result.count,
                "silence_duration_ms": result.silence_duration_ms,
                "total_duration_ms": result.total_duration_ms,
                "silence_ratio": result.silence_ratio,
                "edit_decision_count": len(edit_decisions),
            },
        )

    async def validate(self, context: PipelineContext) -> bool:
        """Validate that primary media exists for silence detection."""
        primary_media = context.get_primary_media()
        if primary_media is None:
            logger.warning("Validation failed: no primary media file")
            return False
        if not primary_media.path.exists():
            logger.warning("Validation failed: media file not found at %s", primary_media.path)
            return False
        return True
