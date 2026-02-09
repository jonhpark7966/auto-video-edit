"""Audio sync service — detect time offsets between media files via audio cross-correlation."""

from __future__ import annotations

import asyncio
import tempfile
from dataclasses import dataclass
from pathlib import Path

from avid.models.project import Project
from avid.services.media import MediaService


@dataclass
class SyncResult:
    """Result of an audio offset detection."""

    offset_ms: int  # positive = extra starts later than main
    confidence: float  # 0.0–1.0 (derived from standard_score)
    method: str  # e.g. "mfcc"
    standard_score: float  # raw score from audio-offset-finder


class AudioSyncService:
    """Detect audio offsets and register extra sources on a Project."""

    def __init__(self) -> None:
        self._media = MediaService()

    async def find_offset(
        self,
        main_path: Path,
        extra_path: Path,
        trim_s: int = 120,
    ) -> SyncResult:
        """Find the time offset of *extra_path* relative to *main_path*.

        Both inputs can be video or audio files.  If they are video, the
        audio track is extracted to a temporary WAV first.

        Args:
            main_path: Reference media file.
            extra_path: Media file to align.
            trim_s: Only analyse the first *trim_s* seconds (speeds things up).

        Returns:
            SyncResult with the detected offset.
        """
        try:
            from audio_offset_finder.audio_offset_finder import find_offset_between_files
        except ImportError as exc:
            raise RuntimeError(
                "audio-offset-finder is not installed. "
                "Install with: pip install 'avid[sync]'"
            ) from exc

        with tempfile.TemporaryDirectory() as tmpdir:
            main_wav = await self._ensure_wav(main_path, Path(tmpdir), "main")
            extra_wav = await self._ensure_wav(extra_path, Path(tmpdir), "extra")

            result = await asyncio.to_thread(
                find_offset_between_files,
                str(main_wav),
                str(extra_wav),
                trim=trim_s,
            )

        offset_s: float = result["time_offset"]
        score: float = result["standard_score"]

        # Map standard_score → 0..1 confidence (score ≥ 10 → 1.0, ≤ 3 → ~0.3)
        confidence = min(1.0, max(0.0, score / 10.0))

        return SyncResult(
            offset_ms=int(round(offset_s * 1000)),
            confidence=confidence,
            method="mfcc",
            standard_score=score,
        )

    async def add_extra_sources(
        self,
        project: Project,
        main_path: Path,
        extra_sources: list[Path],
        manual_offsets: dict[str, int] | None = None,
    ) -> list[SyncResult]:
        """Detect offsets and add extra sources to the project.

        For each extra source:
        1. Run ``find_offset()`` (unless a manual offset is provided).
        2. Create a MediaFile via ``MediaService``.
        3. Add it to the project (``project.add_source_file()``).
        4. Set ``offset_ms`` on all created tracks.

        Args:
            project: The Project to augment (mutated in-place).
            main_path: Path to the main/reference media file.
            extra_sources: Paths to extra media files.
            manual_offsets: ``{filename: offset_ms}`` overrides.  Keys are
                matched against ``Path.name``.

        Returns:
            One SyncResult per extra source.
        """
        manual_offsets = manual_offsets or {}
        results: list[SyncResult] = []

        for extra_path in extra_sources:
            extra_path = Path(extra_path).resolve()

            # Manual override?
            if extra_path.name in manual_offsets:
                offset_ms = manual_offsets[extra_path.name]
                sync_result = SyncResult(
                    offset_ms=offset_ms,
                    confidence=1.0,
                    method="manual",
                    standard_score=0.0,
                )
            else:
                sync_result = await self.find_offset(main_path, extra_path)

            # Create MediaFile and register with project
            media_file = await self._media.create_media_file(extra_path)
            created_tracks = project.add_source_file(media_file)

            # Apply detected offset to every track of this source
            for track in created_tracks:
                project.set_track_offset(track.id, sync_result.offset_ms)

            results.append(sync_result)
            print(
                f"  Synced {extra_path.name}: offset={sync_result.offset_ms}ms "
                f"confidence={sync_result.confidence:.2f} ({sync_result.method})"
            )

        return results

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _ensure_wav(self, path: Path, tmpdir: Path, prefix: str) -> Path:
        """Return a WAV version of *path*.  Extracts audio if it is a video."""
        audio_exts = {".wav", ".flac", ".ogg", ".mp3", ".m4a", ".aac", ".opus"}
        if path.suffix.lower() in audio_exts:
            return path
        wav_path = tmpdir / f"{prefix}_{path.stem}.wav"
        return await self._media.extract_audio(path, wav_path)
