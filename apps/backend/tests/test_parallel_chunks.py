import sys
from pathlib import Path


SKILLS_DIR = Path(__file__).resolve().parents[3] / "skills"
if str(SKILLS_DIR) not in sys.path:
    sys.path.insert(0, str(SKILLS_DIR))

from _common import SubtitleSegment, process_chunks_parallel  # noqa: E402


def test_parallel_chunks_use_overlap_as_context_only():
    segments = [
        SubtitleSegment(index=i, start_ms=i * 1000, end_ms=i * 1000 + 500, text=str(i))
        for i in range(1, 11)
    ]
    seen_contexts = {}

    def analyze_fn(chunk, chunk_num, total_chunks):
        seen_contexts[chunk_num] = [seg.index for seg in chunk]
        cuts = []
        keeps = []
        for seg in chunk:
            if seg.index == 5:
                cuts.append({"segment_index": seg.index, "reason": "owned cut"})
            elif (seg.index, chunk_num) in {(4, 1), (7, 2)}:
                cuts.append({"segment_index": str(seg.index), "reason": "context conflict"})
            else:
                keeps.append({"segment_index": str(seg.index), "reason": "keep"})
        return cuts, keeps

    cuts, keeps = process_chunks_parallel(
        segments,
        chunk_size=5,
        chunk_overlap=2,
        analyze_fn=analyze_fn,
        max_workers=1,
    )

    assert seen_contexts == {
        1: [1, 2, 3, 4, 5],
        2: [2, 3, 4, 5, 6, 7, 8],
        3: [5, 6, 7, 8, 9, 10],
        4: [8, 9, 10],
    }
    assert [int(item["segment_index"]) for item in cuts] == [5]
    assert sorted(int(item["segment_index"]) for item in keeps) == [
        1,
        2,
        3,
        4,
        6,
        7,
        8,
        9,
        10,
    ]
    assert sorted(int(item["segment_index"]) for item in [*cuts, *keeps]) == list(range(1, 11))
