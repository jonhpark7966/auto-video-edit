"""Silence detection pipeline stage based on subtitle gaps.

This stage detects silence regions by analyzing gaps between transcription
segments, replacing the FFmpeg-based audio analysis approach.
"""

from typing import Any

from avid.models.pipeline import StageResult
from avid.models.project import TranscriptSegment
from avid.models.timeline import EditDecision, EditReason, EditType, TimeRange
from avid.pipeline.base import PipelineStage, ProgressCallback
from avid.pipeline.context import PipelineContext


def detect_silence_from_segments(
    segments: list[TranscriptSegment],
    min_silence_ms: int = 500,
    total_duration_ms: int = 0,
) -> list[EditDecision]:
    """Detect silence regions based on gaps between subtitle segments.

    This function analyzes the gaps between transcription segments and marks
    gaps longer than the threshold as silence regions to be cut.

    Args:
        segments: List of transcription segments with start_ms and end_ms.
        min_silence_ms: Minimum gap duration to consider as silence (default: 500ms).
        total_duration_ms: Total media duration in milliseconds (for trailing silence).

    Returns:
        List of EditDecision objects for silence cuts.
    """
    if not segments:
        return []

    edit_decisions: list[EditDecision] = []

    # Sort segments by start time
    sorted_segments = sorted(segments, key=lambda s: s.start_ms)

    # 1. Check gap from video start to first subtitle
    first_segment = sorted_segments[0]
    if first_segment.start_ms >= min_silence_ms:
        edit_decisions.append(
            EditDecision(
                range=TimeRange(start_ms=0, end_ms=first_segment.start_ms),
                edit_type=EditType.CUT,
                reason=EditReason.SILENCE,
                confidence=1.0,
            )
        )

    # 2. Check gaps between consecutive subtitles
    for i in range(len(sorted_segments) - 1):
        current_segment = sorted_segments[i]
        next_segment = sorted_segments[i + 1]

        gap_start = current_segment.end_ms
        gap_end = next_segment.start_ms
        gap_duration = gap_end - gap_start

        if gap_duration >= min_silence_ms:
            edit_decisions.append(
                EditDecision(
                    range=TimeRange(start_ms=gap_start, end_ms=gap_end),
                    edit_type=EditType.CUT,
                    reason=EditReason.SILENCE,
                    confidence=1.0,
                )
            )

    # 3. Check gap from last subtitle to video end
    if total_duration_ms > 0:
        last_segment = sorted_segments[-1]
        trailing_gap = total_duration_ms - last_segment.end_ms

        if trailing_gap >= min_silence_ms:
            edit_decisions.append(
                EditDecision(
                    range=TimeRange(
                        start_ms=last_segment.end_ms,
                        end_ms=total_duration_ms,
                    ),
                    edit_type=EditType.CUT,
                    reason=EditReason.SILENCE,
                    confidence=1.0,
                )
            )

    return edit_decisions


class SilenceStage(PipelineStage):
    """Pipeline stage for detecting silence based on transcription gaps.

    This stage:
    1. Retrieves transcription segments from the previous stage
    2. Analyzes gaps between segments
    3. Creates EditDecision objects for gaps exceeding the threshold
    """

    @property
    def name(self) -> str:
        return "silence"

    @property
    def display_name(self) -> str:
        return "무음 구간 감지"

    @property
    def description(self) -> str:
        return "자막 간격을 기반으로 무음 구간을 감지합니다"

    async def validate(self, context: PipelineContext) -> bool:
        """Validate that transcription data is available."""
        # Check if transcription stage has completed
        if not context.has_stage_completed("transcribe"):
            return False

        # Check if there are segments
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
        """Execute silence detection based on subtitle gaps.

        Options:
            min_silence_ms (int): Minimum silence duration in milliseconds (default: 500)

        Args:
            context: Pipeline context with transcription data.
            options: Stage options.
            progress_callback: Progress callback.

        Returns:
            StageResult with silence detection data.
        """
        self._report_progress(progress_callback, 0.0, "무음 구간 분석 준비 중")

        # Get options
        min_silence_ms = options.get("min_silence_ms", 500)

        # Get transcription data from previous stage
        transcription_data = context.get_stage_data("transcribe")
        if not transcription_data:
            return StageResult.failure(
                "전사 데이터를 찾을 수 없습니다. 먼저 '음성 인식' 단계를 실행하세요."
            )

        transcription = transcription_data.get("transcription", {})
        raw_segments = transcription.get("segments", [])

        if not raw_segments:
            return StageResult.failure("전사 세그먼트가 없습니다.")

        self._report_progress(progress_callback, 0.2, "세그먼트 분석 중")

        # Convert to TranscriptSegment objects
        segments = [
            TranscriptSegment(
                start_ms=seg["start_ms"],
                end_ms=seg["end_ms"],
                text=seg["text"],
                confidence=seg.get("confidence", 1.0),
            )
            for seg in raw_segments
        ]

        # Get total duration from primary media
        total_duration_ms = 0
        primary = context.get_primary_media()
        if primary and primary.info:
            total_duration_ms = primary.info.duration_ms

        self._report_progress(progress_callback, 0.4, "무음 구간 감지 중")

        # Detect silence regions
        edit_decisions = detect_silence_from_segments(
            segments=segments,
            min_silence_ms=min_silence_ms,
            total_duration_ms=total_duration_ms,
        )

        self._report_progress(progress_callback, 0.8, "결과 저장 중")

        # Calculate statistics
        total_silence_ms = sum(ed.range.duration_ms for ed in edit_decisions)
        silence_ratio = (
            (total_silence_ms / total_duration_ms * 100)
            if total_duration_ms > 0
            else 0
        )

        self._report_progress(progress_callback, 1.0, "무음 구간 감지 완료")

        return StageResult.success(
            message=f"무음 구간 {len(edit_decisions)}개 감지 ({silence_ratio:.1f}%)",
            data={
                "edit_decisions": [ed.model_dump() for ed in edit_decisions],
                "silence_count": len(edit_decisions),
                "total_silence_ms": total_silence_ms,
                "silence_ratio_percent": round(silence_ratio, 2),
                "min_silence_ms": min_silence_ms,
            },
        )
