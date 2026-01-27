"""Multi-provider result aggregation for AI analysis."""

from collections import Counter

from avid.models.ai_analysis import AIAnalysisResult, CutSegment


class AIResultAggregator:
    """Aggregates AI analysis results from multiple providers.

    Uses a voting strategy: a segment is included in the final cut list if
    the designated decision-maker agrees OR a majority of providers agree.
    """

    def aggregate(
        self,
        results: dict[str, AIAnalysisResult],
        decision_maker: str = "claude",
    ) -> AIAnalysisResult:
        """Aggregate results from multiple AI providers.

        For each segment index flagged by any provider, the segment is
        included in the final cut list when:
        - The decision_maker provider flagged it, OR
        - A majority (>50%) of providers flagged it.

        Confidence is computed as the ratio of agreeing providers to
        total providers.

        Args:
            results: Mapping of provider name to its analysis result.
            decision_maker: Name of the provider whose opinion takes
                priority. Defaults to ``"claude"``.

        Returns:
            Aggregated AIAnalysisResult with voting metadata.
        """
        if not results:
            return AIAnalysisResult(
                provider="aggregated",
                metadata={"strategy": "empty", "providers": []},
            )

        # Single provider → return directly with metadata
        if len(results) == 1:
            provider_name, result = next(iter(results.items()))
            return AIAnalysisResult(
                cuts=result.cuts,
                keeps=result.keeps,
                provider="aggregated",
                metadata={
                    "strategy": "single_provider",
                    "providers": [provider_name],
                    "decision_maker": decision_maker,
                },
            )

        total_providers = len(results)
        majority_threshold = total_providers / 2.0

        # Collect all unique segment indices flagged across providers
        all_cut_indices: set[int] = set()
        for result in results.values():
            all_cut_indices.update(result.cut_indices)

        # Decision-maker cuts
        dm_cuts: set[int] = set()
        if decision_maker in results:
            dm_cuts = results[decision_maker].cut_indices

        # For each flagged index, count agreements and collect reasons
        index_votes: Counter[int] = Counter()
        index_reasons: dict[int, str] = {}
        index_agreeing_providers: dict[int, list[str]] = {}

        for provider_name, result in results.items():
            for cut in result.cuts:
                idx = cut.segment_index
                index_votes[idx] += 1
                # Keep the first reason encountered (or decision-maker's reason)
                if idx not in index_reasons or provider_name == decision_maker:
                    index_reasons[idx] = cut.reason
                if idx not in index_agreeing_providers:
                    index_agreeing_providers[idx] = []
                index_agreeing_providers[idx].append(provider_name)

        # Build final cut list
        final_cuts: list[CutSegment] = []
        final_cut_indices: set[int] = set()

        for idx in sorted(all_cut_indices):
            vote_count = index_votes[idx]
            dm_agrees = idx in dm_cuts
            majority_agrees = vote_count > majority_threshold

            if dm_agrees or majority_agrees:
                confidence = vote_count / total_providers
                final_cuts.append(
                    CutSegment(
                        segment_index=idx,
                        reason=index_reasons.get(idx, "unknown"),
                        confidence=confidence,
                        provider="aggregated",
                    )
                )
                final_cut_indices.add(idx)

        # Compute keeps: find max segment index across all results
        all_keep_indices: set[int] = set()
        for result in results.values():
            all_keep_indices.update(result.keeps)
            for cut in result.cuts:
                all_keep_indices.add(cut.segment_index)

        max_index = max(all_keep_indices) if all_keep_indices else -1
        keeps = [i for i in range(max_index + 1) if i not in final_cut_indices]

        return AIAnalysisResult(
            cuts=final_cuts,
            keeps=keeps,
            provider="aggregated",
            metadata={
                "strategy": "voting",
                "decision_maker": decision_maker,
                "providers": list(results.keys()),
                "total_providers": total_providers,
                "per_segment_votes": {
                    str(idx): {
                        "votes": index_votes[idx],
                        "agreeing": index_agreeing_providers.get(idx, []),
                    }
                    for idx in sorted(final_cut_indices)
                },
            },
        )
