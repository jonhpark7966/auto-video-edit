import wave
from pathlib import Path

import numpy as np

from avid.services.audio_sync import AudioSyncService


def _write_wav(path: Path, data: np.ndarray, sample_rate: int) -> None:
    clipped = np.clip(data, -0.95, 0.95)
    pcm = (clipped * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm.tobytes())


def test_pcm_drift_estimate_recovers_linear_speed(tmp_path: Path) -> None:
    sample_rate = 8000
    duration_s = 160
    offset_s = 2.0
    speed = 1.0012
    rng = np.random.default_rng(42)

    main = rng.normal(0, 0.25, duration_s * sample_rate).astype(np.float32)

    extra_duration_s = int((duration_s - offset_s) * speed) + 2
    extra_t = np.arange(extra_duration_s * sample_rate, dtype=np.float64) / sample_rate
    main_t_for_extra = (extra_t + offset_s) / speed
    main_times = np.arange(len(main), dtype=np.float64) / sample_rate
    extra = np.interp(main_t_for_extra, main_times, main, left=0.0, right=0.0).astype(np.float32)

    main_path = tmp_path / "main.wav"
    extra_path = tmp_path / "extra.wav"
    _write_wav(main_path, main, sample_rate)
    _write_wav(extra_path, extra, sample_rate)

    estimate = AudioSyncService()._pcm_drift_estimate(
        str(main_path),
        str(extra_path),
        initial_offset_ms=int(offset_s * 1000),
        snippet_s=1,
        num_points=7,
        search_window_s=4,
        residual_threshold_s=0.05,
    )

    assert estimate is not None
    assert estimate["status"] == "ok"
    assert estimate["inlier_count"] >= 5
    assert estimate["retime_speed"] == estimate["raw_retime_speed"]
    assert abs(estimate["retime_speed"] - speed) < 0.0002
    assert estimate["drift_ms"] < -100
