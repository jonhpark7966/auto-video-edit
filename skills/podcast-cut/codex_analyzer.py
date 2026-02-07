"""Codex CLI-based podcast analysis for entertainment-focused editing.

Uses Codex CLI to analyze podcast transcripts and identify:
- Segments to cut (boring, tangent, repetitive, etc.)
- Segments to keep (funny, chemistry, engaging, etc.)
"""

import sys
from pathlib import Path

# Add skills directory to path for imports
skills_dir = Path(__file__).parent.parent
if str(skills_dir) not in sys.path:
    sys.path.insert(0, str(skills_dir))

from _common import SubtitleSegment, call_codex, parse_json_response, format_filtered_context_for_prompt, format_podcast_context_for_prompt, process_chunks_parallel
from models import PodcastAnalysisResult


# Chunk size for processing large transcripts
CHUNK_SIZE = 80  # Process 80 segments at a time
CHUNK_OVERLAP = 5  # Overlap to maintain context


PODCAST_ANALYSIS_PROMPT = '''당신은 유명 유튜브 하이라이트 편집자입니다. 긴 팟캐스트에서 **재미있는 부분만 골라내는** 전문가입니다.

## 핵심 원칙
당신의 목표는 **과감하게 자르는 것**입니다.
시청자는 10분짜리 하이라이트를 원하지, 40분짜리 약간 다듬은 버전을 원하지 않습니다.
**"이거 꼭 남겨야 해?"** 라고 자문하세요. 확신이 없으면 자르세요.

## 자막 세그먼트들:
{segments}

## 분석 방법 — 반드시 2단계로 수행하세요:

### 1단계: 먼저 자를 것을 찾기
아래 기준에 해당하면 CUT입니다:
1. **지루함 (boring)**: 에너지 낮은 구간, 흥미 없는 설명, 단답 연속, 그냥 평범한 대화
2. **탈선 (tangent)**: 본 주제에서 벗어난 대화 (웃기지 않은 잡담)
3. **반복 (repetitive)**: 같은 이야기를 다시 하거나, 이미 한 설명을 반복
4. **긴 침묵 (long_pause)**: 3초 이상의 불필요한 침묵
5. **겹침 (crosstalk)**: 동시에 말해서 알아듣기 어려운 구간
6. **무관함 (irrelevant)**: 시청자에게 무관한 내용 (TMI, 사적인 이야기, inside joke)
7. **필러 (filler)**: "어...", "음...", "그래서...", 의미 없는 추임새
8. **늘어짐 (dragging)**: 핵심 없이 질질 끄는 구간. 같은 포인트를 돌려 말하기.

### 2단계: 남길 것 확인
아래 기준에 해당하는 것만 KEEP합니다:
1. **유머 (funny)**: 웃긴 순간. 농담의 setup + punchline은 함께 유지.
2. **재치 (witty)**: 재치 있는 답변, 말장난
3. **케미 (chemistry)**: 출연자 간 찰떡 호흡, 말 받아치기
4. **반응 (reaction)**: 놀람, 웃음, 공감 — 짧고 강렬한 것만
5. **콜백 (callback)**: 앞서 나온 이야기 재참조, 반복 유머
6. **클라이맥스 (climax)**: 이야기의 핵심 포인트, 반전
7. **몰입 (engaging)**: 듣는 사람이 궁금해지는 흥미로운 스토리
8. **감정 (emotional)**: 진심이 담긴 감정적 순간

## 판단 기준
- **entertainment_score 5 이하는 과감하게 CUT하세요.**
- 평범한 대화는 keep이 아닙니다. "그냥 괜찮은" 정도는 CUT입니다.
- 진짜 재미있거나, 핵심 정보이거나, 감정적인 순간만 남기세요.
- 질문-답변은 함께 처리하되, 답변이 지루하면 질문도 함께 자르세요.
- 농담의 setup은 punchline을 위해 유지하되, punchline이 없는 setup은 자르세요.

## 출력 형식 (JSON):
```json
{{
  "analysis": [
    {{
      "segment_index": 1,
      "action": "cut",
      "reason": "boring",
      "entertainment_score": 3,
      "note": "에너지 낮은 단답 연속. 시청자 이탈 위험."
    }},
    {{
      "segment_index": 5,
      "action": "keep",
      "reason": "funny",
      "entertainment_score": 9,
      "note": "예상치 못한 답변에 모두 웃음. 하이라이트 후보."
    }}
  ]
}}
```

**중요**:
- 각 결정에 대해 반드시 구체적인 `note`를 작성하세요.
- `entertainment_score`는 반드시 1-10 사이의 정수로 작성하세요.
- 전체의 30-50% 정도만 남긴다는 마음으로 편집하세요. 많이 남기면 지루해집니다.
- CUT 이유: "boring", "tangent", "repetitive", "long_pause", "crosstalk", "irrelevant", "filler", "dragging"
- KEEP 이유: "funny", "witty", "chemistry", "reaction", "callback", "climax", "engaging", "emotional"

JSON만 출력하세요.'''


def _apply_podcast_principles(context_text: str) -> str:
    """Replace generic editing principles with podcast-specific ones."""
    generic_marker = "### 편집 원칙"
    if generic_marker in context_text:
        idx = context_text.index(generic_marker)
        context_text = context_text[:idx]
        context_text += "### 편집 원칙 (팟캐스트 하이라이트)\n"
        context_text += "- 스토리라인의 핵심 순간(key_moments)과 클라이맥스는 반드시 유지\n"
        context_text += "- setup → payoff 쌍은 함께 유지 (setup만 있고 payoff가 없으면 둘 다 자르기)\n"
        context_text += "- 콜백 유머의 원본은 유지\n"
        context_text += "- 중요도 낮은 챕터는 과감하게 자르기\n"
        context_text += "- 핵심 챕터라도 지루한 구간은 자르기 — 챕터 전체를 살릴 필요 없음"
    return context_text


def format_segments_for_prompt(segments: list[SubtitleSegment]) -> str:
    """Format segments for the Codex prompt."""
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
    """Analyze a chunk of segments using Codex.

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
        context_text = _apply_podcast_principles(context_text)
        prompt = context_text + "\n\n" + prompt

    print(f"  Processing chunk {chunk_num}/{total_chunks} ({len(segments)} segments)...")

    # Call Codex with longer timeout for large chunks
    response = call_codex(prompt, timeout=300)  # 5 minutes

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


def analyze_with_codex(
    segments: list[SubtitleSegment],
    storyline_context: dict | None = None,
) -> PodcastAnalysisResult:
    """Analyze podcast segments using Codex CLI.

    For large transcripts, processes in chunks to avoid timeout.

    Args:
        segments: List of subtitle segments to analyze
        storyline_context: Optional storyline dict from Pass 1 (transcript-overview)

    Returns:
        PodcastAnalysisResult with cuts, keeps, and entertainment scores
    """
    # Process in chunks if too many segments
    if len(segments) <= CHUNK_SIZE:
        # Small enough to process at once
        segments_text = format_segments_for_prompt(segments)
        prompt = PODCAST_ANALYSIS_PROMPT.format(segments=segments_text)

        # Inject storyline context if available
        if storyline_context:
            context_text = format_podcast_context_for_prompt(storyline_context)
            prompt = context_text + "\n\n" + prompt

        response = call_codex(prompt, timeout=300)

        try:
            data = parse_json_response(response)
        except (ValueError, Exception) as e:
            print(f"Failed to parse Codex response: {e}")
            print(f"Response: {response[:500]}")
            raise

        all_cuts = []
        all_keeps = []

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

        return PodcastAnalysisResult(cuts=all_cuts, keeps=all_keeps, raw_response=response)
    else:
        # Parallel chunk processing
        all_cuts, all_keeps = process_chunks_parallel(
            segments, CHUNK_SIZE, CHUNK_OVERLAP,
            analyze_fn=lambda chunk, num, total: analyze_chunk(chunk, num, total, storyline_context),
            max_workers=5,
        )

        return PodcastAnalysisResult(cuts=all_cuts, keeps=all_keeps)
