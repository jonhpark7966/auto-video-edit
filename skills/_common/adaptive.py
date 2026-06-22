"""Adaptive transcript analysis helpers.

The fixed 80-segment chunker is safe but often too conservative. This module
tries the largest useful request first, then recursively splits only chunks
that are too large or fail in recoverable ways.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable, Iterable, TypeVar


T = TypeVar("T")


@dataclass(frozen=True)
class AdaptiveConfig:
    enabled: bool = True
    max_prompt_tokens: int = 300_000
    min_segments: int = 40
    overlap_segments: int = 8
    legacy_chunk_size: int = 80
    legacy_chunk_overlap: int = 5

    @classmethod
    def from_env(cls) -> "AdaptiveConfig":
        legacy_chunk_size = max(2, _env_int("AVID_LEGACY_CHUNK_SIZE", 80))
        legacy_chunk_overlap = max(0, _env_int("AVID_LEGACY_CHUNK_OVERLAP", 5))
        return cls(
            enabled=_env_bool("AVID_ADAPTIVE_FULL_CALL", True),
            max_prompt_tokens=_env_int("AVID_MAX_PROMPT_TOKENS", 300_000),
            min_segments=max(2, _env_int("AVID_ADAPTIVE_MIN_SEGMENTS", 40)),
            overlap_segments=max(0, _env_int("AVID_ADAPTIVE_OVERLAP_SEGMENTS", 8)),
            legacy_chunk_size=legacy_chunk_size,
            legacy_chunk_overlap=min(legacy_chunk_overlap, legacy_chunk_size - 1),
        )


class PromptTooLargeError(RuntimeError):
    """Raised before an LLM call when the prompt exceeds the configured limit."""


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off", ""}


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def count_text_tokens(text: str) -> int:
    """Count tokens using OpenAI's o200k tokenizer when available.

    The editing skills should still run in minimal environments, so this falls
    back to a conservative character-based estimate if tiktoken is absent.
    """
    try:
        import tiktoken

        return len(tiktoken.get_encoding("o200k_base").encode(text))
    except Exception:
        return max(1, len(text) // 2)


def is_recoverable_analysis_error(exc: BaseException) -> bool:
    message = str(exc).lower()
    nonrecoverable_markers = (
        "cli not found",
        "not found:",
        "auth",
        "login",
        "api key",
        "permission denied",
        "rate limit",
        "quota",
        "unsupported provider",
        "file not found",
        "no such file",
    )
    if any(marker in message for marker in nonrecoverable_markers):
        return False

    recoverable_markers = (
        "timeout",
        "context length",
        "maximum context",
        "too many tokens",
        "token",
        "output too large",
        "json",
        "parse",
        "schema",
        "missing",
        "incomplete",
        "prompt exceeds",
    )
    if isinstance(exc, (ValueError, PromptTooLargeError)):
        return True
    return any(marker in message for marker in recoverable_markers)


def dedupe_by_segment_index(items: Iterable[dict]) -> list[dict]:
    merged: list[dict] = []
    seen: set[int] = set()
    for item in items:
        try:
            idx = int(item.get("segment_index"))
        except (TypeError, ValueError):
            continue
        if idx in seen:
            continue
        updated = dict(item)
        updated["segment_index"] = idx
        merged.append(updated)
        seen.add(idx)
    return merged


def adaptive_analyze_segments(
    segments: list[T],
    *,
    analyze_fn: Callable[[list[T], str], list[dict]],
    prompt_token_count_fn: Callable[[list[T]], int],
    segment_token_count_fn: Callable[[T], int],
    fixed_chunk_fallback_fn: Callable[[], list[dict]],
    config: AdaptiveConfig | None = None,
    label: str = "analysis",
) -> list[dict]:
    """Analyze with full-call-first adaptive binary splitting.

    ``analyze_fn`` must return cut decisions only. Recoverable failures split
    the failed chunk and retry; non-recoverable failures are raised directly.
    If adaptive analysis reaches a recoverable failure at the minimum chunk
    size, the legacy fixed chunk fallback is used once for the whole transcript.
    """
    cfg = config or AdaptiveConfig.from_env()
    if not cfg.enabled:
        print("  Adaptive full-call disabled. Using legacy fixed chunks...")
        return fixed_chunk_fallback_fn()

    try:
        return _adaptive_analyze_range(
            segments,
            analyze_fn=analyze_fn,
            prompt_token_count_fn=prompt_token_count_fn,
            segment_token_count_fn=segment_token_count_fn,
            config=cfg,
            label=label,
            depth=0,
        )
    except Exception as exc:
        if not is_recoverable_analysis_error(exc):
            raise
        print(f"  Adaptive analysis failed ({exc}). Falling back to legacy fixed chunks...")
        return fixed_chunk_fallback_fn()


def _adaptive_analyze_range(
    segments: list[T],
    *,
    analyze_fn: Callable[[list[T], str], list[dict]],
    prompt_token_count_fn: Callable[[list[T]], int],
    segment_token_count_fn: Callable[[T], int],
    config: AdaptiveConfig,
    label: str,
    depth: int,
) -> list[dict]:
    if not segments:
        return []

    prompt_tokens = prompt_token_count_fn(segments)
    if prompt_tokens > config.max_prompt_tokens and len(segments) > config.min_segments:
        print(
            f"  {label}: prompt estimate {prompt_tokens} tokens exceeds "
            f"{config.max_prompt_tokens}; splitting {len(segments)} segments..."
        )
        return _split_and_analyze(
            segments,
            analyze_fn=analyze_fn,
            prompt_token_count_fn=prompt_token_count_fn,
            segment_token_count_fn=segment_token_count_fn,
            config=config,
            label=label,
            depth=depth,
        )
    if prompt_tokens > config.max_prompt_tokens:
        raise PromptTooLargeError(
            f"prompt exceeds token limit at minimum chunk size: {prompt_tokens} > "
            f"{config.max_prompt_tokens}"
        )

    try:
        print(f"  {label}: analyzing {len(segments)} segments ({prompt_tokens} est. tokens)...")
        return analyze_fn(segments, label)
    except Exception as exc:
        if not is_recoverable_analysis_error(exc):
            raise
        if len(segments) <= config.min_segments:
            raise
        print(f"  {label}: recoverable failure ({exc}); splitting {len(segments)} segments...")
        return _split_and_analyze(
            segments,
            analyze_fn=analyze_fn,
            prompt_token_count_fn=prompt_token_count_fn,
            segment_token_count_fn=segment_token_count_fn,
            config=config,
            label=label,
            depth=depth,
        )


def _split_and_analyze(
    segments: list[T],
    *,
    analyze_fn: Callable[[list[T], str], list[dict]],
    prompt_token_count_fn: Callable[[list[T]], int],
    segment_token_count_fn: Callable[[T], int],
    config: AdaptiveConfig,
    label: str,
    depth: int,
) -> list[dict]:
    split_at = _balanced_split_index(segments, segment_token_count_fn)
    overlap = min(config.overlap_segments, max(0, len(segments) // 4))

    left = segments[: min(len(segments), split_at + overlap)]
    right = segments[max(0, split_at - overlap) :]

    if len(left) >= len(segments) or len(right) >= len(segments):
        left = segments[:split_at]
        right = segments[split_at:]

    left_label = f"{label}.L{depth + 1}"
    right_label = f"{label}.R{depth + 1}"
    left_cuts = _adaptive_analyze_range(
        left,
        analyze_fn=analyze_fn,
        prompt_token_count_fn=prompt_token_count_fn,
        segment_token_count_fn=segment_token_count_fn,
        config=config,
        label=left_label,
        depth=depth + 1,
    )
    right_cuts = _adaptive_analyze_range(
        right,
        analyze_fn=analyze_fn,
        prompt_token_count_fn=prompt_token_count_fn,
        segment_token_count_fn=segment_token_count_fn,
        config=config,
        label=right_label,
        depth=depth + 1,
    )
    return dedupe_by_segment_index([*left_cuts, *right_cuts])


def _balanced_split_index(
    segments: list[T],
    segment_token_count_fn: Callable[[T], int],
) -> int:
    if len(segments) <= 1:
        return 1

    weights = [max(1, segment_token_count_fn(segment)) for segment in segments]
    total = sum(weights)
    halfway = total / 2
    running = 0
    best_idx = 1
    best_delta = total
    for idx, weight in enumerate(weights[:-1], start=1):
        running += weight
        delta = abs(halfway - running)
        if delta < best_delta:
            best_delta = delta
            best_idx = idx
    return min(max(1, best_idx), len(segments) - 1)
