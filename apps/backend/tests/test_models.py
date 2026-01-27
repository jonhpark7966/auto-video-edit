"""Tests for new data models."""

import pytest

from avid.models.silence import SilenceDetectionResult, SilenceRegion
from avid.models.ai_analysis import AIAnalysisResult, CutSegment


class TestSilenceRegion:
    def test_create(self) -> None:
        region = SilenceRegion(start_ms=1000, end_ms=2000, source="ffmpeg")
        assert region.duration_ms == 1000
        assert region.source == "ffmpeg"
        assert region.confidence == 1.0

    def test_overlaps(self) -> None:
        r1 = SilenceRegion(start_ms=1000, end_ms=3000, source="ffmpeg")
        r2 = SilenceRegion(start_ms=2000, end_ms=4000, source="srt")
        assert r1.overlaps(r2)
        assert r2.overlaps(r1)

    def test_no_overlap(self) -> None:
        r1 = SilenceRegion(start_ms=1000, end_ms=2000, source="ffmpeg")
        r2 = SilenceRegion(start_ms=3000, end_ms=4000, source="srt")
        assert not r1.overlaps(r2)

    def test_invalid_range(self) -> None:
        with pytest.raises(ValueError):
            SilenceRegion(start_ms=2000, end_ms=1000, source="ffmpeg")


class TestSilenceDetectionResult:
    def test_empty(self) -> None:
        result = SilenceDetectionResult()
        assert result.count == 0
        assert result.silence_duration_ms == 0
        assert result.silence_ratio == 0.0

    def test_with_regions(self) -> None:
        result = SilenceDetectionResult(
            silence_regions=[
                SilenceRegion(start_ms=1000, end_ms=2000, source="combined"),
                SilenceRegion(start_ms=5000, end_ms=6000, source="combined"),
            ],
            total_duration_ms=10000,
        )
        assert result.count == 2
        assert result.silence_duration_ms == 2000
        assert result.silence_ratio == 0.2


class TestCutSegment:
    def test_create(self) -> None:
        cut = CutSegment(segment_index=3, reason="duplicate", provider="claude")
        assert cut.segment_index == 3
        assert cut.reason == "duplicate"
        assert cut.confidence == 1.0


class TestAIAnalysisResult:
    def test_empty(self) -> None:
        result = AIAnalysisResult()
        assert result.cut_count == 0
        assert result.cut_indices == set()

    def test_with_cuts(self) -> None:
        result = AIAnalysisResult(
            cuts=[
                CutSegment(segment_index=1, reason="filler", provider="claude"),
                CutSegment(segment_index=5, reason="duplicate", provider="claude"),
            ],
            provider="claude",
        )
        assert result.cut_count == 2
        assert result.cut_indices == {1, 5}
