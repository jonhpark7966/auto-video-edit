"""Transcription pipeline stage using Whisper."""

import logging
from pathlib import Path
from typing import Any

from avid.errors import PipelineError
from avid.models.pipeline import StageResult
from avid.pipeline.base import PipelineStage, ProgressCallback
from avid.pipeline.context import PipelineContext
from avid.services.transcription import TranscriptionService

logger = logging.getLogger(__name__)


class TranscribeStage(PipelineStage):
    """Pipeline stage for speech recognition using Whisper.

    Transcribes audio from the primary media file and stores
    the result in the pipeline context for downstream stages.
    """

    @property
    def name(self) -> str:
        return "transcribe"

    @property
    def display_name(self) -> str:
        return "음성 인식"

    @property
    def description(self) -> str:
        return "Whisper 기반 음성 인식"

    async def execute(
        self,
        context: PipelineContext,
        options: dict[str, Any],
        progress_callback: ProgressCallback | None = None,
    ) -> StageResult:
        """Execute speech transcription.

        Options:
            provider (str): Transcription provider name (default: "whisper-base")
            language (str): Language code for transcription (default: None = auto-detect)
            export_srt (bool): Whether to export SRT file (default: True)
            whisper_options (dict): Additional Whisper-specific options

        Args:
            context: Pipeline context with media files
            options: Stage-specific configuration
            progress_callback: Optional progress callback

        Returns:
            StageResult with transcription statistics
        """
        self._report_progress(progress_callback, 0.0, "음성 인식 시작...")

        # Get audio path from primary media
        primary_media = context.get_primary_media()
        if primary_media is None:
            raise PipelineError("No media file available for transcription")

        audio_path = primary_media.path

        self._report_progress(progress_callback, 0.1, "Whisper 모델 로딩 중...")

        # Create transcription service
        provider_name = options.get("provider", "whisper-base")
        language = options.get("language")
        whisper_options = options.get("whisper_options")

        service = TranscriptionService(default_provider=provider_name)

        self._report_progress(progress_callback, 0.2, "음성 인식 진행 중...")

        result = await service.transcribe(
            audio_path=audio_path,
            provider_name=provider_name,
            language=language,
            options=whisper_options,
        )

        self._report_progress(progress_callback, 0.8, "결과 저장 중...")

        # Store transcription result in context
        context.transcription = {
            "text": result.text,
            "segments": [seg.model_dump() for seg in result.segments],
            "language": result.language,
            "confidence": result.confidence,
        }

        # Optionally export SRT
        srt_path: str | None = None
        export_srt = options.get("export_srt", True)
        if export_srt and result.segments:
            srt_output = context.output_dir / f"{audio_path.stem}.srt"
            exported = service.export_srt(result, srt_output)
            srt_path = str(exported)
            logger.info("SRT exported to: %s", srt_path)

        # Store stage data
        context.set_stage_data(
            self.name,
            {
                "segments": [seg.model_dump() for seg in result.segments],
                "text": result.text,
                "language": result.language,
                "confidence": result.confidence,
                "segment_count": len(result.segments),
                "srt_path": srt_path,
                "provider": provider_name,
            },
        )

        self._report_progress(progress_callback, 1.0, "음성 인식 완료")

        logger.info(
            "Transcription complete: %d segments, language=%s, confidence=%.2f",
            len(result.segments),
            result.language,
            result.confidence,
        )

        return StageResult.success(
            message=(
                f"음성 인식 완료: {len(result.segments)}개 세그먼트, "
                f"언어={result.language or 'auto'}, "
                f"신뢰도={result.confidence:.1%}"
            ),
            data={
                "segment_count": len(result.segments),
                "language": result.language,
                "confidence": result.confidence,
                "text_length": len(result.text),
                "srt_path": srt_path,
            },
        )

    async def validate(self, context: PipelineContext) -> bool:
        """Validate that audio/media file exists for transcription."""
        primary_media = context.get_primary_media()
        if primary_media is None:
            logger.warning("Validation failed: no primary media file")
            return False
        if not primary_media.path.exists():
            logger.warning("Validation failed: media file not found at %s", primary_media.path)
            return False
        return True
