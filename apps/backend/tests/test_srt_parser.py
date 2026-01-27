"""Tests for SRT parser."""

import tempfile
from pathlib import Path

import pytest

from avid.errors import SRTParseError
from avid.services.srt_parser import SRTParser

SAMPLE_SRT = """\
1
00:00:01,000 --> 00:00:03,500
안녕하세요

2
00:00:05,000 --> 00:00:08,200
오늘 이야기할 주제는

3
00:00:08,500 --> 00:00:12,000
자동 영상 편집입니다
"""

SAMPLE_SRT_WITH_GAPS = """\
1
00:00:01,000 --> 00:00:03,000
첫 번째 자막

2
00:00:06,000 --> 00:00:09,000
두 번째 자막 (3초 갭)

3
00:00:09,100 --> 00:00:12,000
세 번째 자막 (100ms 갭)
"""


@pytest.fixture
def parser() -> SRTParser:
    return SRTParser()


@pytest.fixture
def sample_srt_path(tmp_path: Path) -> Path:
    srt_file = tmp_path / "test.srt"
    srt_file.write_text(SAMPLE_SRT, encoding="utf-8")
    return srt_file


@pytest.fixture
def gap_srt_path(tmp_path: Path) -> Path:
    srt_file = tmp_path / "gaps.srt"
    srt_file.write_text(SAMPLE_SRT_WITH_GAPS, encoding="utf-8")
    return srt_file


def test_parse_valid_srt(parser: SRTParser, sample_srt_path: Path) -> None:
    segments = parser.parse(sample_srt_path)
    assert len(segments) == 3
    assert segments[0].text == "안녕하세요"
    assert segments[0].start_ms == 1000
    assert segments[0].end_ms == 3500
    assert segments[1].text == "오늘 이야기할 주제는"
    assert segments[2].text == "자동 영상 편집입니다"


def test_parse_timestamps(parser: SRTParser, sample_srt_path: Path) -> None:
    segments = parser.parse(sample_srt_path)
    assert segments[1].start_ms == 5000
    assert segments[1].end_ms == 8200
    assert segments[2].start_ms == 8500
    assert segments[2].end_ms == 12000


def test_parse_sorted_by_start_time(parser: SRTParser, sample_srt_path: Path) -> None:
    segments = parser.parse(sample_srt_path)
    for i in range(len(segments) - 1):
        assert segments[i].start_ms <= segments[i + 1].start_ms


def test_parse_file_not_found(parser: SRTParser) -> None:
    with pytest.raises(FileNotFoundError):
        parser.parse(Path("/nonexistent/file.srt"))


def test_parse_empty_file(parser: SRTParser, tmp_path: Path) -> None:
    empty = tmp_path / "empty.srt"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(SRTParseError):
        parser.parse(empty)


def test_parse_bom(parser: SRTParser, tmp_path: Path) -> None:
    bom_file = tmp_path / "bom.srt"
    bom_file.write_text("\ufeff" + SAMPLE_SRT, encoding="utf-8")
    segments = parser.parse(bom_file)
    assert len(segments) == 3


def test_parse_html_tags(parser: SRTParser, tmp_path: Path) -> None:
    srt_content = "1\n00:00:01,000 --> 00:00:03,000\n<b>볼드 텍스트</b>\n"
    srt_file = tmp_path / "html.srt"
    srt_file.write_text(srt_content, encoding="utf-8")
    segments = parser.parse(srt_file)
    assert segments[0].text == "볼드 텍스트"


def test_detect_gaps(parser: SRTParser, gap_srt_path: Path) -> None:
    gaps = parser.detect_gaps(gap_srt_path, min_gap_ms=500)
    assert len(gaps) == 1
    assert gaps[0].start_ms == 3000
    assert gaps[0].end_ms == 6000
    assert gaps[0].source == "srt"


def test_detect_gaps_small_threshold(parser: SRTParser, gap_srt_path: Path) -> None:
    gaps = parser.detect_gaps(gap_srt_path, min_gap_ms=50)
    assert len(gaps) == 2


def test_detect_gaps_large_threshold(parser: SRTParser, gap_srt_path: Path) -> None:
    gaps = parser.detect_gaps(gap_srt_path, min_gap_ms=5000)
    assert len(gaps) == 0
