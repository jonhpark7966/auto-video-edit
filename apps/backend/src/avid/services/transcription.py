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
