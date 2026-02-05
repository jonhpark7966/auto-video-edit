"""Whisper-based audio transcription service."""

import asyncio
import subprocess
import shutil
from pathlib import Path

from avid.services.media import MediaService


class TranscriptionService:
    """Transcribe audio/video to SRT using Whisper CLI."""

    def __init__(self):
        self._media_service = MediaService()

    def is_available(self) -> bool:
        """Check if whisper CLI is installed."""
        return shutil.which("whisper") is not None

    async def transcribe(
        self,
        input_path: Path,
        language: str = "ko",
        model: str = "base",
        output_dir: Path | None = None,
    ) -> Path:
        """Transcribe audio/video to SRT file.

        Args:
            input_path: Path to video or audio file
            language: Language code (ko, en, ja, etc.)
            model: Whisper model name (tiny, base, small, medium, large)
            output_dir: Output directory (defaults to input file's directory)

        Returns:
            Path to generated .srt file

        Raises:
            RuntimeError: If whisper is not installed or transcription fails
        """
        if not self.is_available():
            raise RuntimeError(
                "whisper CLI not found. Install: pip install openai-whisper"
            )

        input_path = Path(input_path).resolve()
        if not input_path.exists():
            raise FileNotFoundError(f"Input file not found: {input_path}")

        if output_dir is None:
            output_dir = input_path.parent
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # If video, extract audio first to wav
        audio_path = input_path
        temp_audio = None
        if input_path.suffix.lower() in (".mp4", ".mov", ".avi", ".mkv", ".webm"):
            temp_audio = output_dir / f"{input_path.stem}_temp_audio.wav"
            audio_path = await self._media_service.extract_audio(
                input_path, temp_audio, sample_rate=16000
            )

        try:
            # Run whisper CLI
            cmd = [
                "whisper",
                str(audio_path),
                "--language", language,
                "--model", model,
                "--output_format", "srt",
                "--output_dir", str(output_dir),
            ]

            result = await asyncio.to_thread(
                subprocess.run,
                cmd,
                capture_output=True,
                text=True,
                timeout=600,  # 10 min timeout
            )

            if result.returncode != 0:
                raise RuntimeError(f"Whisper failed: {result.stderr}")

        finally:
            # Clean up temp audio
            if temp_audio and temp_audio.exists():
                temp_audio.unlink()

        # Find generated SRT
        srt_path = output_dir / f"{audio_path.stem}.srt"
        if not srt_path.exists():
            # whisper sometimes uses original filename
            srt_path = output_dir / f"{input_path.stem}.srt"

        if not srt_path.exists():
            raise RuntimeError(f"Whisper did not produce SRT file in {output_dir}")

        return srt_path


import asyncio
import os
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import httpx


class ChalnaTranscriptionError(Exception):
    """Exception raised for Chalna API errors."""

    def __init__(self, message: str, status_code: int | None = None, details: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.details = details


class ChalnaStatus(str, Enum):
    """Status of a Chalna transcription job."""

    PENDING = "pending"
    VALIDATING = "validating"
    LOADING = "loading"
    TRANSCRIBING = "transcribing"
    ALIGNING = "aligning"
    REFINING = "refining"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class ChalnaSegment:
    """A single transcription segment from Chalna API.

    Chalna returns times in seconds (float, ms precision).
    """

    start: float  # seconds
    end: float  # seconds
    text: str


@dataclass
class ChalnaResult:
    """Result from Chalna transcription API."""

    task_id: str
    status: ChalnaStatus
    segments: list[ChalnaSegment]
    language: str
    full_text: str
    progress_history: list[str]


# Progress callback type: (progress: float 0-1, status: str) -> None
ProgressCallback = Callable[[float, str], None]


# Progress weights for each stage (sum to 1.0)
STAGE_PROGRESS: dict[str, tuple[float, float]] = {
    # stage: (start_progress, end_progress)
    "validating": (0.0, 0.05),
    "loading": (0.05, 0.15),
    "transcribing": (0.15, 0.70),
    "aligning": (0.70, 0.90),
    "refining": (0.90, 1.0),
}

STAGE_DISPLAY_NAMES: dict[str, str] = {
    "validating": "파일 검증 중",
    "loading": "모델 로딩 중",
    "transcribing": "음성 전사 중",
    "aligning": "타임스탬프 정렬 중",
    "refining": "텍스트 정제 중",
}


class ChalnaTranscriptionService:
    """Client for Chalna transcription API.

    Handles async transcription requests with polling and progress tracking.
    """

    def __init__(
        self,
        base_url: str | None = None,
        timeout: float = 30.0,
        poll_interval: float = 1.0,
        max_poll_time: float = 3600.0,  # 1 hour max
    ):
        """Initialize the Chalna transcription service.

        Args:
            base_url: Chalna API base URL. Defaults to CHALNA_API_URL env var
                      or http://localhost:7861.
            timeout: HTTP request timeout in seconds.
            poll_interval: Polling interval for async status in seconds.
            max_poll_time: Maximum time to wait for transcription in seconds.
        """
        self.base_url = (
            base_url
            or os.environ.get("CHALNA_API_URL")
            or "http://localhost:7861"
        ).rstrip("/")
        self.timeout = timeout
        self.poll_interval = poll_interval
        self.max_poll_time = max_poll_time

    async def health_check(self) -> bool:
        """Check if the Chalna API is available.

        Returns:
            True if the API is healthy, False otherwise.
        """
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.get(f"{self.base_url}/health")
                return response.status_code == 200
            except httpx.RequestError:
                return False

    async def transcribe_async(
        self,
        audio_path: Path,
        language: str = "ko",
        use_alignment: bool = True,
        use_llm_refinement: bool = False,
        context: str | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> ChalnaResult:
        """Transcribe audio using Chalna's async API with polling.

        Args:
            audio_path: Path to the audio file.
            language: Language code (default: "ko" for Korean).
            use_alignment: Whether to use Qwen2-based timestamp alignment.
            use_llm_refinement: Whether to use LLM text refinement.
            context: Optional context to improve transcription accuracy.
            progress_callback: Optional callback for progress updates.

        Returns:
            ChalnaResult with transcription segments.

        Raises:
            ChalnaTranscriptionError: If transcription fails.
        """
        audio_path = Path(audio_path)
        if not audio_path.exists():
            raise ChalnaTranscriptionError(f"Audio file not found: {audio_path}")

        # Submit transcription request
        task_id = await self._submit_transcription(
            audio_path=audio_path,
            language=language,
            use_alignment=use_alignment,
            use_llm_refinement=use_llm_refinement,
            context=context,
        )

        if progress_callback:
            progress_callback(0.0, "전사 작업 시작됨")

        # Poll for completion
        result = await self._poll_until_complete(task_id, progress_callback)

        return result

    async def _submit_transcription(
        self,
        audio_path: Path,
        language: str,
        use_alignment: bool,
        use_llm_refinement: bool,
        context: str | None,
    ) -> str:
        """Submit a transcription request to the async endpoint.

        Returns:
            Task ID for polling.
        """
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            with open(audio_path, "rb") as f:
                files = {"file": (audio_path.name, f, "audio/mpeg")}
                data = {
                    "language": language,
                    "use_alignment": str(use_alignment).lower(),
                    "use_llm_refinement": str(use_llm_refinement).lower(),
                    "output_format": "json",  # Request JSON format for segments
                }
                if context:
                    data["context"] = context

                try:
                    response = await client.post(
                        f"{self.base_url}/transcribe/async",
                        files=files,
                        data=data,
                    )
                except httpx.RequestError as e:
                    raise ChalnaTranscriptionError(
                        f"Failed to connect to Chalna API: {e}"
                    ) from e

                if response.status_code != 200:
                    raise ChalnaTranscriptionError(
                        f"Chalna API returned error: {response.text}",
                        status_code=response.status_code,
                    )

                result = response.json()
                # Chalna API returns job_id, not task_id
                job_id = result.get("job_id") or result.get("task_id")
                if not job_id:
                    raise ChalnaTranscriptionError(
                        "Chalna API did not return a job_id",
                        details=result,
                    )

                return job_id

    async def _poll_until_complete(
        self,
        task_id: str,
        progress_callback: ProgressCallback | None,
    ) -> ChalnaResult:
        """Poll the status endpoint until transcription is complete.

        Args:
            task_id: The task ID to poll.
            progress_callback: Optional callback for progress updates.

        Returns:
            ChalnaResult when complete.

        Raises:
            ChalnaTranscriptionError: If polling fails or times out.
        """
        start_time = asyncio.get_event_loop().time()
        last_status: str | None = None

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            while True:
                elapsed = asyncio.get_event_loop().time() - start_time
                if elapsed > self.max_poll_time:
                    raise ChalnaTranscriptionError(
                        f"Transcription timed out after {self.max_poll_time}s"
                    )

                try:
                    response = await client.get(
                        f"{self.base_url}/jobs/{task_id}"
                    )
                except httpx.RequestError as e:
                    raise ChalnaTranscriptionError(
                        f"Failed to check transcription status: {e}"
                    ) from e

                if response.status_code != 200:
                    raise ChalnaTranscriptionError(
                        f"Status check failed: {response.text}",
                        status_code=response.status_code,
                    )

                data = response.json()
                status = data.get("status", "unknown")
                progress_history = data.get("progress_history", [])

                # Report progress if status changed
                if progress_callback and status != last_status:
                    progress, display_name = self._get_progress_for_status(status)
                    progress_callback(progress, display_name)
                    last_status = status

                if status == "completed":
                    return self._parse_completed_result(task_id, data)

                if status == "failed":
                    error_msg = data.get("error", "Unknown error")
                    raise ChalnaTranscriptionError(
                        f"Transcription failed: {error_msg}",
                        details=data,
                    )

                await asyncio.sleep(self.poll_interval)

    def _get_progress_for_status(self, status: str) -> tuple[float, str]:
        """Get progress value and display name for a status.

        Args:
            status: The current status string.

        Returns:
            Tuple of (progress 0-1, display_name).
        """
        if status in STAGE_PROGRESS:
            _, end_progress = STAGE_PROGRESS[status]
            display_name = STAGE_DISPLAY_NAMES.get(status, status)
            return end_progress, display_name

        if status == "completed":
            return 1.0, "완료"

        if status == "pending":
            return 0.0, "대기 중"

        return 0.0, status

    def _parse_completed_result(self, task_id: str, data: dict[str, Any]) -> ChalnaResult:
        """Parse the completed transcription result.

        Args:
            task_id: The task ID.
            data: Response data from the status endpoint.

        Returns:
            ChalnaResult with parsed segments.
        """
        import json as json_module

        result_data = data.get("result", {})

        # result might be a JSON string (when output_format=json)
        if isinstance(result_data, str):
            try:
                result_data = json_module.loads(result_data)
            except json_module.JSONDecodeError:
                result_data = {}

        raw_segments = result_data.get("segments", [])

        segments = [
            ChalnaSegment(
                start=seg.get("start_time", seg.get("start", 0.0)),
                end=seg.get("end_time", seg.get("end", 0.0)),
                text=seg.get("text", "").strip(),
            )
            for seg in raw_segments
        ]

        return ChalnaResult(
            task_id=task_id,
            status=ChalnaStatus.COMPLETED,
            segments=segments,
            language=result_data.get("language", "ko"),
            full_text=result_data.get("text", ""),
            progress_history=data.get("progress_history", []),
        )


def seconds_to_ms(seconds: float) -> int:
    """Convert seconds (float) to milliseconds (int).

    This is the standard conversion at the service boundary:
    Chalna uses seconds with ms precision, AVID uses milliseconds.

    Args:
        seconds: Time in seconds (float, ms precision).

    Returns:
        Time in milliseconds (int).
    """
    return int(seconds * 1000)


def ms_to_seconds(ms: int) -> float:
    """Convert milliseconds (int) to seconds (float).

    Args:
        ms: Time in milliseconds (int).

    Returns:
        Time in seconds (float).
    """
    return ms / 1000.0
