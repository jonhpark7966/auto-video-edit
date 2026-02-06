"""Claude-based podcast analysis for entertainment-focused editing.

Uses Claude CLI to analyze podcast transcripts and identify:
- Segments to cut (boring, tangent, repetitive, etc.)
- Segments to keep (funny, chemistry, engaging, etc.)

The key difference from subtitle-cut is the focus on "entertainment value"
rather than "information efficiency".
"""

import sys
from pathlib import Path

# Add skills directory to path for imports
skills_dir = Path(__file__).parent.parent
if str(skills_dir) not in sys.path:
    sys.path.insert(0, str(skills_dir))

from _common import SubtitleSegment, call_claude, parse_json_response, format_filtered_context_for_prompt, format_podcast_context_for_prompt
from models import PodcastAnalysisResult


# Chunk size for processing large transcripts
CHUNK_SIZE = 80  # Process 80 segments at a time
CHUNK_OVERLAP = 5  # Overlap to maintain context


PODCAST_ANALYSIS_PROMPT = '''당신은 인기 팟캐스트 편집자입니다. 아래 자막 세그먼트들을 분석해서 어떤 부분을 잘라야 하는지 판단해주세요.

## 핵심 원칙
팟캐스트 편집의 목표는 **"재미없는 구간을 제거하여 청취자의 몰입을 유지하는 것"**입니다.
강의 영상과 다르게, 정보 전달보다 **재미와 몰입**이 더 중요합니다.

## 자막 세그먼트들:
{segments}

## CUT 기준 (제거할 구간)
1. **지루함 (boring)**: 에너지 낮은 단답 연속, 흥미 없는 긴 설명
2. **탈선 (tangent)**: 지루한 옆길로 새는 대화 (재미있는 탈선은 유지!)
3. **반복 (repetitive)**: 같은 이야기나 설명 반복
4. **긴 침묵 (long_pause)**: 3초 이상의 불필요한 침묵
5. **겹침 (crosstalk)**: 동시에 말해서 알아듣기 어려운 구간
6. **무관함 (irrelevant)**: 시청자에게 무관한 내용 (TMI, inside joke)
7. **필러 (filler)**: 의미 없는 필러워드

## KEEP 기준 (유지할 구간)
1. **유머 (funny)**: 농담, 출연자가 웃는 순간
2. **재치 (witty)**: 재치 있는 답변, 말장난
3. **케미 (chemistry)**: 출연자 간 티키타카, 말 받아치기
4. **반응 (reaction)**: 놀람, 웃음, 공감 리액션
5. **콜백 (callback)**: 앞서 나온 이야기 재참조, 반복 유머
6. **클라이맥스 (climax)**: 이야기의 핵심 포인트
7. **몰입 (engaging)**: 흥미로운 스토리
8. **감정 (emotional)**: 감정적인 순간

## 중요 주의사항
- **보수적으로 자르기**: 확실히 지루한 것만 제거하세요. 애매하면 유지!
- **대화 흐름 유지**: 질문-답변은 함께 처리하세요
- **재미있는 탈선은 유지**: 탈선이라도 웃기거나 흥미로우면 유지하세요
- **entertainment_score**: 1-10점으로 재미 정도를 평가하세요 (1=매우 지루, 10=매우 재미있음)

## 출력 형식 (JSON):
```json
{{
  "analysis": [
    {{
      "segment_index": 1,
      "action": "cut",
      "reason": "boring",
      "entertainment_score": 2,
      "note": "에너지 낮은 단답 연속. 시청자 이탈 위험."
    }},
    {{
      "segment_index": 5,
      "action": "keep",
      "reason": "funny",
      "entertainment_score": 9,
      "note": "예상치 못한 답변에 모두 웃음. 하이라이트 후보."
    }},
    {{
      "segment_index": 8,
      "action": "keep",
      "reason": "chemistry",
      "entertainment_score": 8,
      "note": "출연자 간 티키타카가 좋음. 자연스러운 케미."
    }}
  ]
}}
```

**중요**:
- 각 결정에 대해 반드시 구체적인 `note`를 작성하세요.
- `entertainment_score`는 반드시 1-10 사이의 정수로 작성하세요.
- CUT 이유: "boring", "tangent", "repetitive", "long_pause", "crosstalk", "irrelevant", "filler"
- KEEP 이유: "funny", "witty", "chemistry", "reaction", "callback", "climax", "engaging", "emotional"

JSON만 출력하세요.'''


def _apply_podcast_principles(context_text: str) -> str:
    """Replace generic editing principles with podcast-specific ones."""
    generic_marker = "### 편집 원칙"
    if generic_marker in context_text:
        idx = context_text.index(generic_marker)
        context_text = context_text[:idx]
        context_text += "### 편집 원칙 (팟캐스트)\n"
        context_text += "- 의존성이 있는 세그먼트는 함께 유지하세요 (setup을 자르면 payoff가 의미 없음)\n"
        context_text += "- 핵심 순간은 반드시 유지하세요\n"
        context_text += "- 지루해 보여도 이후 payoff가 있는 setup은 유지\n"
        context_text += "- 콜백 유머의 원본을 자르면 안 됨\n"
        context_text += "- Q&A 쌍은 함께 유지\n"
        context_text += "- 고에너지 구간 사이의 쉼(breathing room)은 자르지 마세요\n"
        context_text += "- 중요도 ≥ 7인 챕터는 보수적으로 편집하세요"
    return context_text


def format_segments_for_prompt(segments: list[SubtitleSegment]) -> str:
    """Format segments for the Claude prompt."""
    lines = []
    for seg in segments:
        time_str = f"{seg.start_ms // 1000}s - {seg.end_ms // 1000}s"
        lines.append(f"[{seg.index}] ({time_str}): \"{seg.text}\"")
    return "\n".join(lines)


def analyze_chunk(
    segments: list[SubtitleSegment],
    chunk_num: int,
    total_chunks: int,
    storyline_context: dict | None = None,
) -> tuple[list[dict], list[dict]]:
    """Analyze a chunk of segments.

    Args:
        segments: Chunk of segments to analyze
        chunk_num: Current chunk number
        total_chunks: Total number of chunks
        storyline_context: Optional full storyline dict (will be filtered for chunk range)

    Returns:
        Tuple of (cuts, keeps) lists
    """
    segments_text = format_segments_for_prompt(segments)
    prompt = PODCAST_ANALYSIS_PROMPT.format(segments=segments_text)

    # Inject filtered storyline context for this chunk's range
    if storyline_context and segments:
        start_idx = segments[0].index
        end_idx = segments[-1].index
        context_text = format_filtered_context_for_prompt(storyline_context, start_idx, end_idx)
        # Replace generic editing principles with podcast-specific ones
        context_text = _apply_podcast_principles(context_text)
        prompt = context_text + "\n\n" + prompt

    print(f"  Processing chunk {chunk_num}/{total_chunks} ({len(segments)} segments)...")

    # Call Claude with longer timeout for large chunks
    response = call_claude(prompt, timeout=300)  # 5 minutes

    # Parse response
    data = parse_json_response(response)

    cuts = []
    keeps = []

    for item in data.get("analysis", []):
        seg_idx = item.get("segment_index")
        action = item.get("action")
        reason = item.get("reason", "")
        entertainment_score = item.get("entertainment_score", 5)
        note = item.get("note", "")

        entry = {
            "segment_index": seg_idx,
            "reason": reason,
            "entertainment_score": entertainment_score,
            "note": note,
        }

        if action == "cut":
            cuts.append(entry)
        else:
            keeps.append(entry)

    return cuts, keeps


def analyze_with_claude(
    segments: list[SubtitleSegment],
    storyline_context: dict | None = None,
) -> PodcastAnalysisResult:
    """Analyze podcast segments using Claude CLI.

    For large transcripts, processes in chunks to avoid timeout.

    Args:
        segments: List of subtitle segments to analyze
        storyline_context: Optional storyline dict from Pass 1 (transcript-overview)

    Returns:
        PodcastAnalysisResult with cuts, keeps, and entertainment scores
    """
    all_cuts = []
    all_keeps = []
    all_responses = []

    # Process in chunks if too many segments
    if len(segments) <= CHUNK_SIZE:
        # Small enough to process at once
        segments_text = format_segments_for_prompt(segments)
        prompt = PODCAST_ANALYSIS_PROMPT.format(segments=segments_text)

        # Inject storyline context if available
        if storyline_context:
            context_text = format_podcast_context_for_prompt(storyline_context)
            prompt = context_text + "\n\n" + prompt

        response = call_claude(prompt, timeout=300)
        all_responses.append(response)

        try:
            data = parse_json_response(response)
        except (ValueError, Exception) as e:
            print(f"Failed to parse Claude response: {e}")
            print(f"Response: {response[:500]}")
            raise

        for item in data.get("analysis", []):
            seg_idx = item.get("segment_index")
            action = item.get("action")
            reason = item.get("reason", "")
            entertainment_score = item.get("entertainment_score", 5)
            note = item.get("note", "")

            entry = {
                "segment_index": seg_idx,
                "reason": reason,
                "entertainment_score": entertainment_score,
                "note": note,
            }

            if action == "cut":
                all_cuts.append(entry)
            else:
                all_keeps.append(entry)
    else:
        # Process in chunks
        total_chunks = (len(segments) + CHUNK_SIZE - 1) // CHUNK_SIZE
        print(f"  Large transcript detected. Processing in {total_chunks} chunks...")

        processed_indices = set()

        for i in range(0, len(segments), CHUNK_SIZE - CHUNK_OVERLAP):
            chunk = segments[i:i + CHUNK_SIZE]
            chunk_num = (i // (CHUNK_SIZE - CHUNK_OVERLAP)) + 1

            try:
                cuts, keeps = analyze_chunk(chunk, chunk_num, total_chunks, storyline_context=storyline_context)

                # Add results, avoiding duplicates from overlap
                for cut in cuts:
                    idx = cut["segment_index"]
                    if idx not in processed_indices:
                        all_cuts.append(cut)
                        processed_indices.add(idx)

                for keep in keeps:
                    idx = keep["segment_index"]
                    if idx not in processed_indices:
                        all_keeps.append(keep)
                        processed_indices.add(idx)

            except Exception as e:
                print(f"  Warning: Chunk {chunk_num} failed: {e}")
                # Continue with other chunks

    return PodcastAnalysisResult(
        cuts=all_cuts,
        keeps=all_keeps,
        raw_response="\n---\n".join(all_responses) if all_responses else ""
    )
