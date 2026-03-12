"""Audio sync service — detect time offsets between media files via audio cross-correlation."""

from __future__ import annotations

import asyncio
import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from avid.models.project import Project
from avid.services.media import MediaService

logger = logging.getLogger(__name__)


@dataclass
class SyncResult:
    """Result of an audio offset detection."""

    offset_ms: int  # positive = extra starts later than main
    confidence: float  # 0.0–1.0 (derived from standard_score)
    method: str  # e.g. "mfcc", "pcm_verified"
    standard_score: float  # raw score from audio-offset-finder


class AudioSyncService:
    """Detect audio offsets and register extra sources on a Project."""

    def __init__(self) -> None:
        self._media = MediaService()

    async def find_offset(
        self,
        main_path: Path,
        extra_path: Path,
        trim_s: int = 900,
    ) -> SyncResult:
        """Find the time offset of *extra_path* relative to *main_path*.

        Uses a two-step approach:
        1. MFCC-based initial offset detection (audio-offset-finder)
        2. Multi-point raw PCM cross-correlation verification

        If MFCC and PCM disagree, the PCM result (verified at multiple
        points) is used because MFCC can find false spectral peaks.

        Args:
            main_path: Reference media file.
            extra_path: Media file to align.
            trim_s: Analyse the first *trim_s* seconds.

        Returns:
            SyncResult with the detected offset.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            main_wav = await self._ensure_wav(main_path, Path(tmpdir), "main")
            extra_wav = await self._ensure_wav(extra_path, Path(tmpdir), "extra")

            # Step 1: MFCC-based initial offset
            mfcc_result = await self._mfcc_offset(main_wav, extra_wav, trim_s)
            logger.info(
                "MFCC offset: %dms (score=%.2f)",
                mfcc_result.offset_ms, mfcc_result.standard_score,
            )

            # Step 2: Multi-point PCM verification
            pcm_result = await asyncio.to_thread(
                self._pcm_multipoint_offset,
                str(main_wav), str(extra_wav),
                mfcc_result.offset_ms, trim_s,
            )

            if pcm_result is not None:
                diff_ms = abs(pcm_result.offset_ms - mfcc_result.offset_ms)
                if diff_ms > 1000:
                    logger.warning(
                        "MFCC offset (%dms) disagrees with PCM (%dms) "
                        "by %dms — using PCM result",
                        mfcc_result.offset_ms, pcm_result.offset_ms, diff_ms,
                    )
                    return pcm_result
                else:
                    logger.info(
                        "MFCC and PCM agree (diff=%dms) — using MFCC",
                        diff_ms,
                    )

            return mfcc_result

    async def _mfcc_offset(
        self, main_wav: Path, extra_wav: Path, trim_s: int,
    ) -> SyncResult:
        """Run audio-offset-finder (MFCC-based)."""
        try:
            from audio_offset_finder.audio_offset_finder import find_offset_between_files
        except ImportError as exc:
            raise RuntimeError(
                "audio-offset-finder is not installed. "
                "Install with: pip install 'avid[sync]'"
            ) from exc

        result = await asyncio.to_thread(
            find_offset_between_files,
            str(main_wav), str(extra_wav),
            trim=trim_s,
        )

        offset_s: float = result["time_offset"]
        score: float = result["standard_score"]
        confidence = min(1.0, max(0.0, score / 10.0))

        return SyncResult(
            offset_ms=int(round(offset_s * 1000)),
            confidence=confidence,
            method="mfcc",
            standard_score=score,
        )

    def _pcm_multipoint_offset(
        self,
        main_wav_path: str,
        extra_wav_path: str,
        initial_offset_ms: int,
        trim_s: int,
        snippet_s: int = 5,
        num_points: int = 8,
        search_window_s: int = 30,
    ) -> SyncResult | None:
        """Verify/correct offset by raw PCM cross-correlation at multiple points.

        Picks *num_points* evenly-spaced positions across the main audio,
        extracts *snippet_s*-second snippets, and cross-correlates each
        against the extra audio in a ±search_window_s window around the
        expected position.

        Returns a SyncResult if a consistent offset is found, or None if
        verification is inconclusive.
        """
        import wave
        from scipy import signal as sig

        def read_mono_16k(path: str) -> tuple[np.ndarray, int]:
            with wave.open(path, "r") as wf:
                sr = wf.getframerate()
                data = np.frombuffer(
                    wf.readframes(wf.getnframes()), dtype=np.int16,
                ).astype(np.float32)
            return data, sr

        main, sr = read_mono_16k(main_wav_path)
        extra, _ = read_mono_16k(extra_wav_path)

        main_dur_s = len(main) / sr
        extra_dur_s = len(extra) / sr
        initial_offset_s = initial_offset_ms / 1000.0

        # Pick test points evenly across the main audio
        # Skip first 10% and last 10% to avoid silence at edges
        margin = max(60, main_dur_s * 0.1)
        usable_start = margin
        usable_end = min(main_dur_s, trim_s) - snippet_s - 10
        if usable_end <= usable_start:
            return None

        test_points = np.linspace(usable_start, usable_end, num_points)

        offsets: list[float] = []
        correlations: list[float] = []

        for main_t in test_points:
            # Extract snippet from main
            snip_start = int(main_t * sr)
            snip_end = int((main_t + snippet_s) * sr)
            if snip_end > len(main):
                continue
            snippet = main[snip_start:snip_end]
            snip_max = np.max(np.abs(snippet))
            if snip_max < 100:  # skip near-silence
                continue
            snippet = snippet / snip_max

            # Search window in extra around expected position
            expected_extra_t = main_t - initial_offset_s
            search_start = max(0, expected_extra_t - search_window_s)
            search_end = min(extra_dur_s - snippet_s, expected_extra_t + search_window_s)
            if search_end <= search_start:
                continue

            s_start_idx = int(search_start * sr)
            s_end_idx = int(search_end * sr)
            search_signal = extra[s_start_idx:s_end_idx]
            s_max = np.max(np.abs(search_signal))
            if s_max < 100:
                continue
            search_signal = search_signal / s_max

            corr = sig.correlate(search_signal, snippet, mode="valid")
            peak_idx = np.argmax(np.abs(corr))
            peak_val = np.abs(corr[peak_idx])
            peak_extra_t = search_start + peak_idx / sr

            offset = main_t - peak_extra_t
            offsets.append(offset)
            correlations.append(peak_val)

        if len(offsets) < 3:
            logger.warning("PCM verification: too few valid points (%d)", len(offsets))
            return None

        # Use median to reject outliers
        offsets_arr = np.array(offsets)
        median_offset = float(np.median(offsets_arr))

        # Count inliers (within 0.5s of median)
        inliers = np.abs(offsets_arr - median_offset) < 0.5
        inlier_count = int(np.sum(inliers))
        inlier_ratio = inlier_count / len(offsets)

        # Refine with inlier mean
        if inlier_count >= 2:
            refined_offset = float(np.mean(offsets_arr[inliers]))
        else:
            refined_offset = median_offset

        logger.info(
            "PCM multi-point: offset=%.1fms, %d/%d inliers (%.0f%%)",
            refined_offset * 1000, inlier_count, len(offsets),
            inlier_ratio * 100,
        )

        if inlier_ratio < 0.5:
            logger.warning("PCM verification: low inlier ratio (%.0f%%)", inlier_ratio * 100)
            return None

        confidence = min(1.0, inlier_ratio)

        return SyncResult(
            offset_ms=int(round(refined_offset * 1000)),
            confidence=confidence,
            method="pcm_verified",
            standard_score=float(np.mean(np.array(correlations)[inliers])),
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
