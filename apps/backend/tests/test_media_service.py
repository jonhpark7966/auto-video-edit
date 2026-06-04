import asyncio
import json
import subprocess

from avid.services.media import MediaService


def test_get_media_info_extracts_audio_channels_and_sources(monkeypatch, tmp_path):
    def fake_run(cmd, capture_output, text):
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout=json.dumps(
                {
                    "format": {"duration": "12.5"},
                    "streams": [
                        {
                            "codec_type": "video",
                            "width": 1920,
                            "height": 1080,
                            "r_frame_rate": "30000/1001",
                        },
                        {
                            "codec_type": "audio",
                            "sample_rate": "48000",
                            "channels": 1,
                        },
                        {
                            "codec_type": "audio",
                            "sample_rate": "48000",
                            "channels": 2,
                        },
                    ],
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    info = asyncio.run(MediaService().get_media_info(tmp_path / "source.mov"))

    assert info.duration_ms == 12_500
    assert info.sample_rate == 48_000
    assert info.audio_channels == 3
    assert info.audio_sources == 2
    assert info.has_audio is True


def test_get_media_info_prefers_video_frame_duration(monkeypatch, tmp_path):
    def fake_run(cmd, capture_output, text):
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout=json.dumps(
                {
                    "format": {"duration": "305.017"},
                    "streams": [
                        {
                            "codec_type": "video",
                            "width": 1920,
                            "height": 1080,
                            "r_frame_rate": "60/1",
                            "nb_frames": "18300",
                        },
                        {
                            "codec_type": "audio",
                            "sample_rate": "44100",
                            "channels": 2,
                        },
                    ],
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    info = asyncio.run(MediaService().get_media_info(tmp_path / "source.mp4"))

    assert info.duration_ms == 305_000
    assert info.fps == 60.0


def test_get_media_info_omits_ambiguous_audio_rate(monkeypatch, tmp_path):
    def fake_run(cmd, capture_output, text):
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout=json.dumps(
                {
                    "format": {"duration": "5"},
                    "streams": [
                        {
                            "codec_type": "audio",
                            "sample_rate": "44100",
                            "channels": 2,
                        },
                        {
                            "codec_type": "audio",
                            "sample_rate": "48000",
                            "channels": 2,
                        },
                    ],
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    info = asyncio.run(MediaService().get_media_info(tmp_path / "source.mov"))

    assert info.sample_rate is None
    assert info.audio_channels == 4
    assert info.audio_sources == 2
    assert info.has_audio is True
