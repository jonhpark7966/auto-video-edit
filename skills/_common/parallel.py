"""Common parallel chunk processing for video editing skills.

Splits segments into context-aware chunks, processes them in parallel via
ThreadPoolExecutor, then accepts decisions only for each chunk's owned core range.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class _ChunkSpec:
    context_segments: list
    core_indices: set[int]


def _decision_segment_index(value) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def process_chunks_parallel(
    segments: list,
    chunk_size: int,
    chunk_overlap: int,
    analyze_fn: Callable,
    max_workers: int = 5,
) -> tuple[list[dict], list[dict]]:
    """Split segments into chunks and process them in parallel.

    Args:
        segments: Full list of segments to process.
        chunk_size: Number of segments per chunk.
        chunk_overlap: Overlap between consecutive chunks for context continuity.
        analyze_fn: Callable(chunk, chunk_num, total_chunks) -> (cuts, keeps).
        max_workers: Maximum parallel threads.

    Returns:
        Tuple of (all_cuts, all_keeps) for each segment's owned core range.
    """
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if chunk_overlap < 0:
        raise ValueError("chunk_overlap must be non-negative")
    if chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap must be smaller than chunk_size")

    # Build chunks where overlap is prompt context only. Each segment belongs to
    # exactly one core range, but the analyzer can see surrounding context.
    chunks: list[_ChunkSpec] = []
    core_size = chunk_size - chunk_overlap
    for core_start in range(0, len(segments), core_size):
        core_end = min(core_start + core_size, len(segments))
        context_start = max(0, core_start - chunk_overlap)
        context_end = min(len(segments), core_end + chunk_overlap)
        core_indices = {
            getattr(seg, "index")
            for seg in segments[core_start:core_end]
            if hasattr(seg, "index")
        }
        chunks.append(
            _ChunkSpec(
                context_segments=segments[context_start:context_end],
                core_indices=core_indices,
            )
        )

    total_chunks = len(chunks)
    print(f"  Parallel processing: {total_chunks} chunks with {max_workers} workers...")

    # Submit all chunks to executor
    results: dict[int, tuple[list[dict], list[dict]]] = {}
    failures: list[str] = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_chunk_num = {
            executor.submit(
                analyze_fn,
                chunk.context_segments,
                chunk_num + 1,
                total_chunks,
            ): chunk_num
            for chunk_num, chunk in enumerate(chunks)
        }

        for future in as_completed(future_to_chunk_num):
            chunk_num = future_to_chunk_num[future]
            try:
                cuts, keeps = future.result()
                results[chunk_num] = (cuts, keeps)
            except Exception as e:
                context = chunks[chunk_num].context_segments
                start = getattr(context[0], "index", "?") if context else "?"
                end = getattr(context[-1], "index", "?") if context else "?"
                failures.append(
                    f"Chunk {chunk_num + 1}/{total_chunks} failed "
                    f"for segment range {start}-{end}: {type(e).__name__}: {e}"
                )

    if failures:
        raise RuntimeError("Parallel chunk processing failed:\n" + "\n".join(failures))

    # Merge results in chunk order, accepting only the current chunk's core range.
    all_cuts = []
    all_keeps = []
    seen_indices: set[int] = set()

    for chunk_num in sorted(results.keys()):
        core_indices = chunks[chunk_num].core_indices
        cuts, keeps = results[chunk_num]
        for cut in cuts:
            idx = _decision_segment_index(cut.get("segment_index"))
            if idx in core_indices and idx not in seen_indices:
                all_cuts.append(cut)
                seen_indices.add(idx)
        for keep in keeps:
            idx = _decision_segment_index(keep.get("segment_index"))
            if idx in core_indices and idx not in seen_indices:
                all_keeps.append(keep)
                seen_indices.add(idx)

    return all_cuts, all_keeps
