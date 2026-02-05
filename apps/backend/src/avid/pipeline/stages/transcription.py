"""Transcription pipeline stage using Chalna API.

This stage handles speech-to-text transcription using the Chalna API,
with support for Qwen2-based alignment and optional LLM refinement.
"""

from pathlib import Path
from typing import Any

from avid.models.pipeline import StageResult
from avid.models.project import Transcription, TranscriptSegment
from avid.pipeline.base import PipelineStage, ProgressCallback
from avid.pipeline.context import PipelineContext
from avid.services.transcription import (
    ChalnaTranscriptionError,
    ChalnaTranscriptionService,
    seconds_to_ms,
)


class TranscriptionStage(PipelineStage):
    """Pipeline stage for transcribing audio using Chalna API.

    This stage:
    1. Extracts audio from video if needed
    2. Sends audio to Chalna API for transcription
    3. Converts results to AVID's Transcription model
    4. Stores segments with millisecond timestamps
    """

    @property
    def name(self) -> str:
        return "transcribe"

    @property
    def display_name(self) -> str:
        return "음성 인식 (Chalna)"

    @property
    def description(self) -> str:
        return "Chalna API를 사용하여 음성을 텍스트로 변환합니다"

    async def validate(self, context: PipelineContext) -> bool:
        """Validate that we have audio to transcribe."""
        primary = context.get_primary_media()
        if not primary:
            return False
        return True

    async def execute(
        self,
        context: PipelineContext,
        options: dict[str, Any],
        progress_callback: ProgressCallback | None = None,
    ) -> StageResult:
        """Execute transcription using Chalna API.

        Options:
            language (str): Language code, default "ko"
            use_alignment (bool): Use Qwen2-based alignment, default True
            use_llm_refinement (bool): Use LLM text refinement, default False
            context (str): Optional context for better transcription
            chalna_url (str): Optional Chalna API URL override

        Args:
            context: Pipeline context with media files.
            options: Stage options.
            progress_callback: Progress callback.

        Returns:
            StageResult with transcription data.
        """
        self._report_progress(progress_callback, 0.0, "전사 준비 중")

        # Get options
        language = options.get("language", "ko")
        use_alignment = options.get("use_alignment", True)
        use_llm_refinement = options.get("use_llm_refinement", False)
        transcription_context = options.get("context")
        chalna_url = options.get("chalna_url")

        # Get audio file path
        audio_path = self._get_audio_path(context)
        if not audio_path:
            return StageResult.failure("오디오 파일을 찾을 수 없습니다")

        # Create Chalna service
        service = ChalnaTranscriptionService(base_url=chalna_url)

        # Check API health
        self._report_progress(progress_callback, 0.02, "Chalna API 연결 확인 중")
        if not await service.health_check():
            return StageResult.failure(
                f"Chalna API에 연결할 수 없습니다: {service.base_url}"
            )

        # Create progress callback wrapper that scales progress
        def chalna_progress(progress: float, status: str) -> None:
            # Scale Chalna progress (0-1) to our range (0.05-0.95)
            scaled = 0.05 + progress * 0.90
            self._report_progress(progress_callback, scaled, status)

        # Run transcription
        try:
            result = await service.transcribe_async(
                audio_path=Path(audio_path),
                language=language,
                use_alignment=use_alignment,
                use_llm_refinement=use_llm_refinement,
                context=transcription_context,
                progress_callback=chalna_progress,
            )
        except ChalnaTranscriptionError as e:
            return StageResult.failure(f"전사 실패: {e}")

        self._report_progress(progress_callback, 0.95, "결과 변환 중")

        # Convert to AVID Transcription model
        segments = [
            TranscriptSegment(
                start_ms=seconds_to_ms(seg.start),
                end_ms=seconds_to_ms(seg.end),
                text=seg.text,
                confidence=1.0,  # Chalna doesn't provide per-segment confidence
            )
            for seg in result.segments
            if seg.text.strip()  # Skip empty segments
        ]

        # Get source track ID
        primary = context.get_primary_media()
        source_track_id = f"{primary.id}_audio" if primary else "unknown"

        transcription = Transcription(
            source_track_id=source_track_id,
            language=result.language,
            segments=segments,
        )

        # Store in context
        context.transcription = {
            "language": transcription.language,
            "segments": [
                {
                    "start_ms": seg.start_ms,
                    "end_ms": seg.end_ms,
                    "text": seg.text,
                    "confidence": seg.confidence,
                }
                for seg in transcription.segments
            ],
            "full_text": transcription.full_text,
        }

        self._report_progress(progress_callback, 1.0, "전사 완료")

        # Return data includes transcription for downstream stages
        return StageResult.success(
            message=f"전사 완료: {len(segments)}개 세그먼트",
            data={
                "transcription": transcription.model_dump(),
                "segment_count": len(segments),
                "language": result.language,
                "full_text": transcription.full_text[:200] + "..."
                if len(transcription.full_text) > 200
                else transcription.full_text,
            },
        )

    def _get_audio_path(self, context: PipelineContext) -> str | None:
        """Get the audio file path from context.

        Prefers separate audio file over video's audio track.

        Args:
            context: Pipeline context.

        Returns:
            Path to audio file or None.
        """
        # Prefer separate audio file if provided
        if context.audio_file and context.audio_file.path:
            return str(context.audio_file.path)

        # Otherwise use video file (Chalna can extract audio)
        if context.video_file and context.video_file.path:
            return str(context.video_file.path)

        return None
