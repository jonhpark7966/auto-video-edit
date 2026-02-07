"""Common parallel chunk processing for video editing skills.

Splits segments into overlapping chunks, processes them in parallel via
ThreadPoolExecutor, then deduplicates results by segment_index.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable


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
        Tuple of (all_cuts, all_keeps) with duplicates removed.
    """
    # Build chunks
    chunks = []
    step = chunk_size - chunk_overlap
    for i in range(0, len(segments), step):
        chunk = segments[i:i + chunk_size]
        chunks.append(chunk)
        # Stop if this chunk already reached the end
        if i + chunk_size >= len(segments):
            break

    total_chunks = len(chunks)
    print(f"  Parallel processing: {total_chunks} chunks with {max_workers} workers...")

    # Submit all chunks to executor
    results: dict[int, tuple[list[dict], list[dict]]] = {}

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_chunk_num = {
            executor.submit(analyze_fn, chunk, chunk_num + 1, total_chunks): chunk_num
            for chunk_num, chunk in enumerate(chunks)
        }

        for future in as_completed(future_to_chunk_num):
            chunk_num = future_to_chunk_num[future]
            try:
                cuts, keeps = future.result()
                results[chunk_num] = (cuts, keeps)
            except Exception as e:
                print(f"  Warning: Chunk {chunk_num + 1}/{total_chunks} failed: {e}")
                # Skip failed chunk, continue with others

    # Merge results in chunk order, dedup by segment_index
    all_cuts = []
    all_keeps = []
    seen_indices: set[int] = set()

    for chunk_num in sorted(results.keys()):
        cuts, keeps = results[chunk_num]
        for cut in cuts:
            idx = cut.get("segment_index")
            if idx not in seen_indices:
                all_cuts.append(cut)
                seen_indices.add(idx)
        for keep in keeps:
            idx = keep.get("segment_index")
            if idx not in seen_indices:
                all_keeps.append(keep)
                seen_indices.add(idx)

    return all_cuts, all_keeps
