"""Audio sync service — detect time offsets between media files via audio cross-correlation."""

from __future__ import annotations

import asyncio
import logging
import sys
import tempfile
from dataclasses import dataclass, field
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
    source_name: str | None = None
    retime_speed: float | None = None
    diagnostics: dict[str, object] = field(default_factory=dict)


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

            diagnostics: dict[str, object] = {
                "main_path": str(main_path),
                "extra_path": str(extra_path),
                "trim_s": trim_s,
                "mfcc": self._result_payload(mfcc_result),
                "pcm": self._result_payload(pcm_result) if pcm_result else None,
                "warnings": [],
            }

            if pcm_result is not None:
                diff_ms = abs(pcm_result.offset_ms - mfcc_result.offset_ms)
                diagnostics["difference_ms"] = diff_ms
                if diff_ms > 1000:
                    warning = (
                        f"MFCC({mfcc_result.offset_ms}ms)와 PCM({pcm_result.offset_ms}ms) 결과가 "
                        f"{diff_ms}ms 차이납니다. 소스에 스킵/불연속이 있을 수 있습니다. "
                        "현재는 PCM 결과를 사용합니다."
                    )
                    logger.warning(
                        "MFCC offset (%dms) disagrees with PCM (%dms) "
                        "by %dms — using PCM result",
                        mfcc_result.offset_ms, pcm_result.offset_ms, diff_ms,
                    )
                    diagnostics["warnings"] = [warning]
                    return await self._attach_drift_estimate(
                        SyncResult(
                            offset_ms=pcm_result.offset_ms,
                            confidence=pcm_result.confidence,
                            method=pcm_result.method,
                            standard_score=pcm_result.standard_score,
                            source_name=extra_path.name,
                            diagnostics={
                                **diagnostics,
                                "selected_method": pcm_result.method,
                                "selected_offset_ms": pcm_result.offset_ms,
                            },
                        ),
                        main_wav,
                        extra_wav,
                    )
                else:
                    logger.info(
                        "MFCC and PCM agree (diff=%dms) — using MFCC",
                        diff_ms,
                    )
                    diagnostics["selected_method"] = mfcc_result.method
                    diagnostics["selected_offset_ms"] = mfcc_result.offset_ms
                    return await self._attach_drift_estimate(
                        SyncResult(
                            offset_ms=mfcc_result.offset_ms,
                            confidence=mfcc_result.confidence,
                            method=mfcc_result.method,
                            standard_score=mfcc_result.standard_score,
                            source_name=extra_path.name,
                            diagnostics=diagnostics,
                        ),
                        main_wav,
                        extra_wav,
                    )

            diagnostics["selected_method"] = mfcc_result.method
            diagnostics["selected_offset_ms"] = mfcc_result.offset_ms
            return await self._attach_drift_estimate(
                SyncResult(
                    offset_ms=mfcc_result.offset_ms,
                    confidence=mfcc_result.confidence,
                    method=mfcc_result.method,
                    standard_score=mfcc_result.standard_score,
                    source_name=extra_path.name,
                    diagnostics=diagnostics,
                ),
                main_wav,
                extra_wav,
            )

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
            diagnostics={
                "trim_s": trim_s,
            },
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
        from scipy import signal as sig
        from scipy.io import wavfile as scipy_wav

        def read_mono_16k(path: str) -> tuple[np.ndarray, int]:
            sr, data = scipy_wav.read(path)
            # Convert to float32 regardless of source dtype
            if data.dtype == np.int16:
                data = data.astype(np.float32)
            elif data.dtype == np.int32:
                data = data.astype(np.float32) / 32768.0
            elif data.dtype == np.float32 or data.dtype == np.float64:
                data = data.astype(np.float32) * 32767.0
            # If stereo, take first channel
            if data.ndim > 1:
                data = data[:, 0]
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
            diagnostics={
                "initial_offset_ms": initial_offset_ms,
                "snippet_s": snippet_s,
                "num_points": num_points,
                "search_window_s": search_window_s,
                "candidate_offsets_ms": [int(round(offset * 1000)) for offset in offsets],
                "median_offset_ms": int(round(median_offset * 1000)),
                "refined_offset_ms": int(round(refined_offset * 1000)),
                "inlier_count": inlier_count,
                "total_points": len(offsets),
                "inlier_ratio": inlier_ratio,
            },
        )

    async def estimate_drift(
        self,
        main_path: Path,
        extra_path: Path,
        initial_offset_ms: int,
    ) -> dict[str, object] | None:
        """Estimate linear drift from multi-point audio alignment."""
        with tempfile.TemporaryDirectory() as tmpdir:
            main_wav = await self._ensure_wav(main_path, Path(tmpdir), "main")
            extra_wav = await self._ensure_wav(extra_path, Path(tmpdir), "extra")
            return await asyncio.to_thread(
                self._pcm_drift_estimate,
                str(main_wav),
                str(extra_wav),
                initial_offset_ms,
            )

    async def _attach_drift_estimate(
        self,
        result: SyncResult,
        main_wav: Path,
        extra_wav: Path,
    ) -> SyncResult:
        """Attach audio-drift retime diagnostics to a selected sync result."""
        drift = await asyncio.to_thread(
            self._pcm_drift_estimate,
            str(main_wav),
            str(extra_wav),
            result.offset_ms,
        )
        if drift is None:
            result.diagnostics["drift"] = None
            return result

        result.diagnostics["drift"] = drift
        retime_speed = drift.get("retime_speed")
        if isinstance(retime_speed, (float, int)):
            result.retime_speed = float(retime_speed)
        return result

    def _pcm_drift_estimate(
        self,
        main_wav_path: str,
        extra_wav_path: str,
        initial_offset_ms: int,
        snippet_s: int = 5,
        num_points: int = 11,
        search_window_s: int = 30,
        residual_threshold_s: float = 0.75,
    ) -> dict[str, object] | None:
        """Estimate drift slope using raw PCM cross-correlation.

        The returned ``retime_speed`` maps main/multicam timeline seconds to
        extra source seconds. Values above 1.0 mean the extra angle should be
        played faster to keep lips aligned with main audio.
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

        # Cover the whole overlapping range, including the tail. Avoid only
        # short edge regions where silence and partial snippets are common.
        edge_margin_s = min(120.0, max(30.0, main_dur_s * 0.03))
        usable_start = max(edge_margin_s, initial_offset_s + edge_margin_s)
        usable_end = min(main_dur_s, initial_offset_s + extra_dur_s) - snippet_s - edge_margin_s
        if usable_end <= usable_start:
            logger.warning("PCM drift estimate: no usable overlap")
            return None

        test_points = np.linspace(usable_start, usable_end, num_points)
        samples: list[dict[str, float]] = []

        for main_t in test_points:
            snip_start = int(main_t * sr)
            snip_end = int((main_t + snippet_s) * sr)
            if snip_end > len(main):
                continue

            snippet = main[snip_start:snip_end]
            snippet = snippet - float(np.mean(snippet))
            snip_max = float(np.max(np.abs(snippet)))
            if snip_max < 100:
                continue
            snippet = snippet / snip_max

            expected_extra_t = main_t - initial_offset_s
            search_start = max(0.0, expected_extra_t - search_window_s)
            search_end = min(extra_dur_s - snippet_s, expected_extra_t + search_window_s)
            if search_end <= search_start:
                continue

            s_start_idx = int(search_start * sr)
            s_end_idx = int((search_end + snippet_s) * sr)
            search_signal = extra[s_start_idx:s_end_idx]
            search_signal = search_signal - float(np.mean(search_signal))
            s_max = float(np.max(np.abs(search_signal)))
            if s_max < 100:
                continue
            search_signal = search_signal / s_max

            corr = sig.correlate(search_signal, snippet, mode="valid")
            peak_idx = int(np.argmax(np.abs(corr)))
            peak_val = float(np.abs(corr[peak_idx]) / max(1, len(snippet)))
            peak_extra_t = search_start + peak_idx / sr
            offset_s = main_t - peak_extra_t
            samples.append({
                "main_s": float(main_t),
                "extra_s": float(peak_extra_t),
                "offset_ms": float(offset_s * 1000),
                "correlation": peak_val,
            })

        if len(samples) < 4:
            logger.warning("PCM drift estimate: too few valid points (%d)", len(samples))
            return {
                "status": "insufficient_points",
                "initial_offset_ms": initial_offset_ms,
                "samples": samples,
                "valid_points": len(samples),
            }

        offset_seconds = np.array(
            [sample["offset_ms"] / 1000.0 for sample in samples], dtype=np.float64,
        )
        median_offset = float(np.median(offset_seconds))
        median_abs_dev = float(np.median(np.abs(offset_seconds - median_offset)))
        mad_threshold_s = max(residual_threshold_s, median_abs_dev * 6.0)
        prefit_inliers = np.abs(offset_seconds - median_offset) <= mad_threshold_s
        if int(np.sum(prefit_inliers)) >= 4:
            fit_samples = [
                sample for sample, is_inlier in zip(samples, prefit_inliers, strict=True) if is_inlier
            ]
        else:
            fit_samples = samples

        main_times = np.array([sample["main_s"] for sample in fit_samples], dtype=np.float64)
        extra_times = np.array([sample["extra_s"] for sample in fit_samples], dtype=np.float64)

        slope, intercept = np.polyfit(main_times, extra_times, 1)
        residuals = extra_times - (slope * main_times + intercept)
        inliers = np.abs(residuals) <= residual_threshold_s
        inlier_count = int(np.sum(inliers))

        if inlier_count >= 4 and inlier_count < len(fit_samples):
            slope, intercept = np.polyfit(main_times[inliers], extra_times[inliers], 1)
            residuals = extra_times - (slope * main_times + intercept)
            inliers = np.abs(residuals) <= residual_threshold_s
            inlier_count = int(np.sum(inliers))

        inlier_ratio = inlier_count / len(samples)
        if inlier_count < 4 or inlier_ratio < 0.5:
            logger.warning(
                "PCM drift estimate: low inlier ratio (%d/%d)",
                inlier_count, len(samples),
            )
            return {
                "status": "low_inlier_ratio",
                "initial_offset_ms": initial_offset_ms,
                "samples": samples,
                "valid_points": len(samples),
                "prefit_inlier_count": len(fit_samples),
                "median_offset_ms": median_offset * 1000,
                "median_abs_dev_ms": median_abs_dev * 1000,
                "inlier_count": inlier_count,
                "inlier_ratio": inlier_ratio,
                "raw_retime_speed": float(slope),
                "intercept_s": float(intercept),
            }

        first_main = float(np.min(main_times[inliers]))
        last_main = float(np.max(main_times[inliers]))
        first_offset = float((first_main - (slope * first_main + intercept)) * 1000)
        last_offset = float((last_main - (slope * last_main + intercept)) * 1000)
        drift_ms = last_offset - first_offset
        span_s = last_main - first_main

        # Ignore tiny slopes; they create XML noise without visible benefit.
        if abs(drift_ms) < 50 or abs(slope - 1.0) < 0.00001:
            status = "no_significant_drift"
            retime_speed: float | None = None
        elif abs(slope - 1.0) > 0.005:
            status = "speed_out_of_range"
            retime_speed = None
        else:
            status = "ok"
            retime_speed = float(slope)

        final_inlier_ids = {id(sample) for sample in np.array(fit_samples, dtype=object)[inliers]}
        for sample in samples:
            expected_extra = slope * sample["main_s"] + intercept
            sample["prefit_inlier"] = bool(
                abs((sample["offset_ms"] / 1000.0) - median_offset) <= mad_threshold_s
            )
            sample["inlier"] = id(sample) in final_inlier_ids
            sample["residual_ms"] = float((sample["extra_s"] - expected_extra) * 1000)

        return {
            "status": status,
            "initial_offset_ms": initial_offset_ms,
            "retime_speed": retime_speed,
            "raw_retime_speed": float(slope),
            "speed_delta_percent": float((slope - 1.0) * 100),
            "intercept_s": float(intercept),
            "span_s": span_s,
            "first_offset_ms": first_offset,
            "last_offset_ms": last_offset,
            "drift_ms": drift_ms,
            "valid_points": len(samples),
            "prefit_inlier_count": len(fit_samples),
            "median_offset_ms": median_offset * 1000,
            "median_abs_dev_ms": median_abs_dev * 1000,
            "inlier_count": inlier_count,
            "inlier_ratio": inlier_ratio,
            "snippet_s": snippet_s,
            "num_points": num_points,
            "search_window_s": search_window_s,
            "residual_threshold_s": residual_threshold_s,
            "samples": samples,
        }

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
                    source_name=extra_path.name,
                    diagnostics={
                        "selected_method": "manual",
                        "selected_offset_ms": offset_ms,
                        "manual_override": True,
                    },
                )
                drift = await self.estimate_drift(main_path, extra_path, offset_ms)
                sync_result.diagnostics["drift"] = drift
                if drift and isinstance(drift.get("retime_speed"), (float, int)):
                    sync_result.retime_speed = float(drift["retime_speed"])
            else:
                sync_result = await self.find_offset(main_path, extra_path)

            # Create MediaFile and register with project
            media_file = await self._media.create_media_file(extra_path)
            created_tracks = project.add_source_file(media_file)

            # Apply detected offset and drift correction to every track of this source
            for track in created_tracks:
                project.set_track_offset(track.id, sync_result.offset_ms)
                if sync_result.retime_speed is not None:
                    track.sync_drift_retime_speed = sync_result.retime_speed

            results.append(sync_result)
            print(
                f"  Synced {extra_path.name}: offset={sync_result.offset_ms}ms "
                f"confidence={sync_result.confidence:.2f} ({sync_result.method})"
            )
            for warning in sync_result.diagnostics.get("warnings", []):
                print(f"  Warning {extra_path.name}: {warning}", file=sys.stderr)

        return results

    @staticmethod
    def _result_payload(result: SyncResult | None) -> dict[str, object] | None:
        if result is None:
            return None
        return {
            "offset_ms": result.offset_ms,
            "confidence": result.confidence,
            "method": result.method,
            "standard_score": result.standard_score,
            "source_name": result.source_name,
            "retime_speed": result.retime_speed,
            "diagnostics": result.diagnostics,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _ensure_wav(self, path: Path, tmpdir: Path, prefix: str) -> Path:
        """Return a WAV version of *path*.  Extracts audio if it is a video."""
        if path.suffix.lower() == ".wav":
            return path
        wav_path = tmpdir / f"{prefix}_{path.stem}.wav"
        return await self._media.extract_audio(path, wav_path)
