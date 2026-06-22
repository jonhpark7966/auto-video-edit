from avid.services.subtitle_cut import _parse_srt


def test_subtitle_srt_parser_preserves_speaker_label(tmp_path):
    srt_path = tmp_path / "sample.srt"
    srt_path.write_text(
        "1\n00:00:01,000 --> 00:00:02,000\n[speaker_0] 안녕하세요\n\n"
        "2\n00:00:02,000 --> 00:00:03,000\nspeaker_1: 반갑습니다\n",
        encoding="utf-8",
    )

    segments = _parse_srt(srt_path)

    assert segments[0]["speaker"] == "speaker_0"
    assert segments[0]["text"] == "안녕하세요"
    assert segments[1]["speaker"] == "speaker_1"
    assert segments[1]["text"] == "반갑습니다"
