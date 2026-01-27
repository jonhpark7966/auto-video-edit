"""AI Analysis orchestration service."""

import asyncio
import logging
from typing import Any

from avid.errors import AIProviderError
from avid.models.ai_analysis import AIAnalysisResult
from avid.models.project import TranscriptSegment
from avid.services.ai_analysis.aggregator import AIResultAggregator
from avid.services.ai_analysis.base import IAIProvider
from avid.services.ai_analysis.providers.claude import ClaudeProvider
from avid.services.ai_analysis.providers.codex import CodexProvider

logger = logging.getLogger(__name__)


class AIAnalysisService:
    """Orchestrates multi-provider AI subtitle analysis.

    Manages multiple AI providers, runs them in parallel, and aggregates
    their results using a voting strategy. Providers that are unavailable
    or fail at runtime are handled gracefully (logged and skipped) as long
    as at least one provider succeeds.
    """

    def __init__(self, providers: list[IAIProvider] | None = None) -> None:
        """Initialize the AI analysis service.

        If no providers are supplied, auto-discovers available providers
        by attempting to create ClaudeProvider and CodexProvider and
        keeping those that report themselves as available.

        Args:
            providers: Optional explicit list of AI providers to use.
        """
        if providers is not None:
            self._providers = {p.name: p for p in providers}
        else:
            self._providers = self._auto_discover()

        self._aggregator = AIResultAggregator()

        available = [n for n, p in self._providers.items() if p.is_available]
        logger.info(
            "AIAnalysisService initialized with %d provider(s): %s",
            len(available),
            ", ".join(available) if available else "(none)",
        )

    @staticmethod
    def _auto_discover() -> dict[str, IAIProvider]:
        """Auto-discover available AI providers.

        Returns:
            Dictionary mapping provider name to provider instance,
            including only those that are available.
        """
        candidates: list[IAIProvider] = [
            ClaudeProvider(),
            CodexProvider(),
        ]
        return {p.name: p for p in candidates if p.is_available}

    async def analyze(
        self,
        segments: list[TranscriptSegment],
        provider_names: list[str] | None = None,
        decision_maker: str = "claude",
        options: dict[str, Any] | None = None,
    ) -> AIAnalysisResult:
        """Run AI analysis across selected providers and aggregate results.

        Invokes providers in parallel using ``asyncio.gather``. If some
        providers fail, logs warnings and continues with successful
        results. If all providers fail, raises ``AIProviderError``.

        Args:
            segments: Transcript segments to analyze.
            provider_names: Optional list of provider names to use.
                If None, uses all available providers.
            decision_maker: Name of the provider whose opinion takes
                priority in the aggregation vote. Defaults to ``"claude"``.
            options: Optional provider-specific options passed through
                to each provider.

        Returns:
            Aggregated AIAnalysisResult from all successful providers.

        Raises:
            AIProviderError: If no providers are available or all
                providers fail.
        """
        # Select providers
        if provider_names:
            selected = {
                name: self._providers[name]
                for name in provider_names
                if name in self._providers
            }
            if not selected:
                raise AIProviderError(
                    f"None of the requested providers are available: "
                    f"{provider_names}. Available: {list(self._providers.keys())}"
                )
        else:
            selected = {
                name: p
                for name, p in self._providers.items()
                if p.is_available
            }

        if not selected:
            raise AIProviderError(
                "No AI providers available. Configure at least one provider "
                "(set ANTHROPIC_API_KEY or install the codex CLI)."
            )

        logger.info(
            "Running AI analysis with %d provider(s): %s",
            len(selected),
            ", ".join(selected.keys()),
        )

        # Run providers in parallel
        async def _run_provider(
            name: str, provider: IAIProvider
        ) -> tuple[str, AIAnalysisResult | None, Exception | None]:
            """Run a single provider, capturing any exception.

            Args:
                name: Provider name.
                provider: Provider instance.

            Returns:
                Tuple of (name, result_or_None, exception_or_None).
            """
            try:
                result = await provider.analyze_subtitles(segments, options)
                return (name, result, None)
            except Exception as exc:
                return (name, None, exc)

        tasks = [
            _run_provider(name, provider)
            for name, provider in selected.items()
        ]
        outcomes = await asyncio.gather(*tasks)

        # Separate successes and failures
        successful: dict[str, AIAnalysisResult] = {}
        errors: dict[str, str] = {}

        for name, result, error in outcomes:
            if result is not None:
                successful[name] = result
                logger.info(
                    "Provider '%s' completed: %d cuts identified",
                    name,
                    result.cut_count,
                )
            else:
                error_msg = str(error)
                errors[name] = error_msg
                logger.warning("Provider '%s' failed: %s", name, error_msg)

        # All failed → raise
        if not successful:
            error_details = "; ".join(
                f"{name}: {msg}" for name, msg in errors.items()
            )
            raise AIProviderError(
                f"All AI providers failed. Details: {error_details}"
            )

        # Some failed → warn
        if errors:
            logger.warning(
                "%d of %d providers failed: %s",
                len(errors),
                len(selected),
                ", ".join(errors.keys()),
            )

        # Aggregate results
        aggregated = self._aggregator.aggregate(
            successful, decision_maker=decision_maker
        )

        logger.info(
            "Aggregated result: %d cuts from %d provider(s)",
            aggregated.cut_count,
            len(successful),
        )

        return aggregated
