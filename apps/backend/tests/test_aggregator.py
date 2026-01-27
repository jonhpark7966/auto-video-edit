"""Tests for AI result aggregator."""

from avid.models.ai_analysis import AIAnalysisResult, CutSegment
from avid.services.ai_analysis.aggregator import AIResultAggregator


def _make_result(provider: str, cut_indices: list[int]) -> AIAnalysisResult:
    return AIAnalysisResult(
        cuts=[
            CutSegment(segment_index=i, reason="duplicate", provider=provider)
            for i in cut_indices
        ],
        provider=provider,
    )


class TestAIResultAggregator:
    def setup_method(self) -> None:
        self.aggregator = AIResultAggregator()

    def test_empty_results(self) -> None:
        result = self.aggregator.aggregate({})
        assert result.cut_count == 0

    def test_single_provider(self) -> None:
        results = {"claude": _make_result("claude", [1, 3, 5])}
        aggregated = self.aggregator.aggregate(results, decision_maker="claude")
        assert aggregated.cut_count == 3
        assert aggregated.cut_indices == {1, 3, 5}

    def test_two_providers_full_agreement(self) -> None:
        results = {
            "claude": _make_result("claude", [1, 3]),
            "codex": _make_result("codex", [1, 3]),
        }
        aggregated = self.aggregator.aggregate(results, decision_maker="claude")
        assert aggregated.cut_count == 2
        assert aggregated.cut_indices == {1, 3}
        for cut in aggregated.cuts:
            assert cut.confidence == 1.0

    def test_two_providers_partial_agreement(self) -> None:
        results = {
            "claude": _make_result("claude", [1, 3, 5]),
            "codex": _make_result("codex", [1, 7]),
        }
        aggregated = self.aggregator.aggregate(results, decision_maker="claude")
        # claude is decision_maker, so 1, 3, 5 all included (claude agrees)
        # codex only adds 7 which needs majority (only 1/2 = 50%, not >50%)
        assert 1 in aggregated.cut_indices
        assert 3 in aggregated.cut_indices
        assert 5 in aggregated.cut_indices
        assert 7 not in aggregated.cut_indices

    def test_decision_maker_priority(self) -> None:
        results = {
            "claude": _make_result("claude", [10]),
            "codex": _make_result("codex", [20]),
        }
        aggregated = self.aggregator.aggregate(results, decision_maker="claude")
        # 10: claude agrees → included
        # 20: only codex (1/2 = 50%, not >50%) → NOT included
        assert 10 in aggregated.cut_indices
        assert 20 not in aggregated.cut_indices

    def test_confidence_reflects_agreement(self) -> None:
        results = {
            "claude": _make_result("claude", [1, 2]),
            "codex": _make_result("codex", [1]),
        }
        aggregated = self.aggregator.aggregate(results, decision_maker="claude")
        cuts_by_index = {c.segment_index: c for c in aggregated.cuts}
        assert cuts_by_index[1].confidence == 1.0  # both agree
        assert cuts_by_index[2].confidence == 0.5  # only claude
