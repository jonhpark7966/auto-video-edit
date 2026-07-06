from pathlib import Path
from fractions import Fraction

import pytest

from avid.services import media as media_service
from avid.services import proxy


def test_timecode_extraction_prefers_video_then_data_then_format():
    payload = {
        "format": {"tags": {"timecode": "01:00:00:00"}},
        "streams": [
            {"codec_type": "data", "tags": {"timecode": "02:00:00:00"}},
            {"codec_type": "video", "tags": {"timecode": "03:00:00:00"}},
        ],
    }

    parsed = media_service._parse_timecode_start("21:01:07:00", Fraction(60, 1))

    assert media_service._extract_timecode(payload) == "03:00:00:00"
    assert media_service._extract_timecode_info(payload) == ("03:00:00:00", "video")
    assert parsed == (4_540_020, "4540020/60")


def test_media_timecode_info_classifies_tmcd_as_fcpxml_compatible():
    payload = {
        "streams": [
            {
                "codec_type": "data",
                "codec_tag_string": "tmcd",
                "tags": {"timecode": "02:00:00:00"},
            },
        ],
    }

    assert media_service._extract_timecode(payload) == "02:00:00:00"
    assert media_service._extract_timecode_info(payload) == ("02:00:00:00", "tmcd")


def test_media_timecode_info_classifies_rtmd_as_raw_only():
    payload = {
        "streams": [
            {
                "codec_type": "data",
                "codec_tag_string": "rtmd",
                "tags": {"timecode": "05:56:31:16"},
            },
        ],
    }

    assert media_service._extract_timecode(payload) == "05:56:31:16"
    assert media_service._extract_timecode_info(payload) == ("05:56:31:16", "rtmd")


def test_media_timecode_info_classifies_format_timecode_as_raw_only():
    payload = {"format": {"tags": {"timecode": "01:00:00:00"}}, "streams": []}

    assert media_service._extract_timecode(payload) == "01:00:00:00"
    assert media_service._extract_timecode_info(payload) == ("01:00:00:00", "format")


def test_proxy_zero_timecode_command_strips_metadata(monkeypatch, tmp_path):
    monkeypatch.setattr(proxy, "probe_timecode", lambda _path: "21:01:07:00")

    cmd = proxy.build_proxy_command(
        tmp_path / "input.mov",
        tmp_path / "output.mp4",
        mode="zero-timecode-proxy",
        encoder="libx264",
    )

    assert "-map_metadata" in cmd
    assert "-1" in cmd
    assert "-write_tmcd" in cmd
    assert "0" in cmd
    assert "-metadata:s:v:0" not in cmd


def test_proxy_preserve_timecode_command_writes_video_timecode(monkeypatch, tmp_path):
    monkeypatch.setattr(proxy, "probe_timecode", lambda _path: "21:01:07:00")

    cmd = proxy.build_proxy_command(
        tmp_path / "input.mov",
        tmp_path / "output.mp4",
        mode="preserve-timecode-proxy",
        encoder="libx264",
    )

    assert "-map_metadata" in cmd
    assert "0" in cmd
    assert "-metadata:s:v:0" in cmd
    assert "timecode=21:01:07:00" in cmd
    assert "-write_tmcd" in cmd
    assert "1" in cmd


def test_proxy_extracts_rtmd_only_timecode_from_data_stream():
    payload = {
        "streams": [
            {"codec_type": "video", "tags": {}},
            {
                "codec_type": "data",
                "codec_tag_string": "rtmd",
                "tags": {"timecode": "05:56:31:16"},
            },
        ]
    }

    assert proxy._extract_timecode(payload) == "05:56:31:16"


def test_proxy_validation_preserves_fps_channels_and_zero_timecode(monkeypatch, tmp_path):
    input_path = tmp_path / "input.mp4"
    output_path = tmp_path / "output.mp4"
    input_probe = {
        "streams": [
            {"codec_type": "video", "r_frame_rate": "30000/1001"},
            {"codec_type": "audio", "channels": 2},
        ]
    }
    output_probe = {
        "streams": [
            {"codec_type": "video", "r_frame_rate": "30000/1001"},
            {"codec_type": "audio", "channels": 2},
        ]
    }

    def fake_probe(path: Path):
        return input_probe if path == input_path else output_probe

    monkeypatch.setattr(proxy, "probe_media", fake_probe)

    result = proxy.validate_proxy(
        input_path,
        output_path,
        mode="zero-timecode-proxy",
    )

    assert result["input_fps"] == "30000/1001"
    assert result["output_fps"] == "30000/1001"
    assert result["input_audio_channels"] == 2
    assert result["output_audio_channels"] == 2
    assert result["input_timecode"] is None
    assert result["output_timecode"] is None
    assert result["output_has_timecode"] is False
    assert result["output_has_tmcd"] is False
    assert result["output_tmcd_timecode"] is None


def test_proxy_validation_preserve_requires_matching_timecode_and_tmcd(monkeypatch, tmp_path):
    input_path = tmp_path / "input.mp4"
    output_path = tmp_path / "output.mp4"
    input_probe = {
        "streams": [
            {"codec_type": "video", "r_frame_rate": "30000/1001"},
            {"codec_type": "audio", "channels": 2},
            {
                "codec_type": "data",
                "codec_tag_string": "rtmd",
                "tags": {"timecode": "05:56:31:16"},
            },
        ]
    }
    output_probe = {
        "streams": [
            {
                "codec_type": "video",
                "r_frame_rate": "30000/1001",
                "tags": {"timecode": "05:56:31:16"},
            },
            {"codec_type": "audio", "channels": 2},
            {
                "codec_type": "data",
                "codec_tag_string": "tmcd",
                "tags": {"timecode": "05:56:31:16"},
            },
        ]
    }

    def fake_probe(path: Path):
        return input_probe if path == input_path else output_probe

    monkeypatch.setattr(proxy, "probe_media", fake_probe)

    result = proxy.validate_proxy(
        input_path,
        output_path,
        mode="preserve-timecode-proxy",
    )

    assert result["input_timecode"] == "05:56:31:16"
    assert result["output_timecode"] == "05:56:31:16"
    assert result["output_has_timecode"] is True
    assert result["output_has_tmcd"] is True
    assert result["output_tmcd_timecode"] == "05:56:31:16"


def test_proxy_validation_preserve_rejects_missing_tmcd(monkeypatch, tmp_path):
    input_path = tmp_path / "input.mp4"
    output_path = tmp_path / "output.mp4"
    input_probe = {
        "streams": [
            {"codec_type": "video", "r_frame_rate": "30000/1001"},
            {"codec_type": "audio", "channels": 2},
            {
                "codec_type": "data",
                "codec_tag_string": "rtmd",
                "tags": {"timecode": "05:56:31:16"},
            },
        ]
    }
    output_probe = {
        "streams": [
            {
                "codec_type": "video",
                "r_frame_rate": "30000/1001",
                "tags": {"timecode": "05:56:31:16"},
            },
            {"codec_type": "audio", "channels": 2},
        ]
    }

    def fake_probe(path: Path):
        return input_probe if path == input_path else output_probe

    monkeypatch.setattr(proxy, "probe_media", fake_probe)

    with pytest.raises(RuntimeError, match="missing a tmcd"):
        proxy.validate_proxy(
            input_path,
            output_path,
            mode="preserve-timecode-proxy",
        )


def test_proxy_validation_preserve_rejects_timecode_mismatch(monkeypatch, tmp_path):
    input_path = tmp_path / "input.mp4"
    output_path = tmp_path / "output.mp4"
    input_probe = {
        "streams": [
            {"codec_type": "video", "r_frame_rate": "30000/1001"},
            {"codec_type": "audio", "channels": 2},
            {
                "codec_type": "data",
                "codec_tag_string": "rtmd",
                "tags": {"timecode": "05:56:31:16"},
            },
        ]
    }
    output_probe = {
        "streams": [
            {
                "codec_type": "video",
                "r_frame_rate": "30000/1001",
                "tags": {"timecode": "05:56:32:00"},
            },
            {"codec_type": "audio", "channels": 2},
            {
                "codec_type": "data",
                "codec_tag_string": "tmcd",
                "tags": {"timecode": "05:56:32:00"},
            },
        ]
    }

    def fake_probe(path: Path):
        return input_probe if path == input_path else output_probe

    monkeypatch.setattr(proxy, "probe_media", fake_probe)

    with pytest.raises(RuntimeError, match="timecode mismatch"):
        proxy.validate_proxy(
            input_path,
            output_path,
            mode="preserve-timecode-proxy",
        )


def test_proxy_validation_preserve_rejects_tmcd_timecode_mismatch(monkeypatch, tmp_path):
    input_path = tmp_path / "input.mp4"
    output_path = tmp_path / "output.mp4"
    input_probe = {
        "streams": [
            {"codec_type": "video", "r_frame_rate": "30000/1001"},
            {"codec_type": "audio", "channels": 2},
            {
                "codec_type": "data",
                "codec_tag_string": "rtmd",
                "tags": {"timecode": "05:56:31:16"},
            },
        ]
    }
    output_probe = {
        "streams": [
            {
                "codec_type": "video",
                "r_frame_rate": "30000/1001",
                "tags": {"timecode": "05:56:31:16"},
            },
            {"codec_type": "audio", "channels": 2},
            {
                "codec_type": "data",
                "codec_tag_string": "tmcd",
                "tags": {"timecode": "05:56:32:00"},
            },
        ]
    }

    def fake_probe(path: Path):
        return input_probe if path == input_path else output_probe

    monkeypatch.setattr(proxy, "probe_media", fake_probe)

    with pytest.raises(RuntimeError, match="tmcd timecode mismatch"):
        proxy.validate_proxy(
            input_path,
            output_path,
            mode="preserve-timecode-proxy",
        )
