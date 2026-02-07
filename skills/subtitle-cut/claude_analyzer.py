"""Claude-based subtitle analysis for lecture/explanation videos.

Uses Claude CLI to semantically analyze subtitles and decide what to cut.
Focuses on removing duplicates, incomplete takes, and fillers.
"""

import sys
from pathlib import Path

# Add skills directory to path for imports
skills_dir = Path(__file__).parent.parent
if str(skills_dir) not in sys.path:
    sys.path.insert(0, str(skills_dir))

from _common import SubtitleSegment, AnalysisResult, call_claude, parse_json_response, format_context_for_prompt, format_filtered_context_for_prompt, process_chunks_parallel


# Chunk size for processing large transcripts
CHUNK_SIZE = 80
CHUNK_OVERLAP = 5


CHUNK_ANALYSIS_PROMPT = '''당신은 영상 편집 전문가입니다. 아래 자막 세그먼트들을 분석해서 어떤 부분을 잘라야 하는지 판단해주세요.

## 자막 세그먼트들:
{segments}

## 분석 방법 — 반드시 2단계로 수행하세요:

### 1단계: 테이크(녹화 시도) 구분
먼저 전체 자막을 읽고 **테이크 경계**를 파악하세요.
화자가 처음부터 다시 시작하거나, 같은 내용을 다시 말하기 시작하면 새로운 테이크입니다.
예: "안녕하세요, D2SF 왔습니다" 같은 인트로가 반복되면, 그 사이가 테이크 경계입니다.

### 2단계: 테이크 단위로 판단
- **같은 내용의 테이크가 여러 개 있으면, 마지막 테이크 전체를 살리고 이전 테이크 전체를 자르세요.**
- 이전 테이크에 속한 모든 세그먼트는 개별적으로 "유니크"해 보여도 자릅니다.
  이전 테이크의 마무리 멘트, 중간 멘트, 반응("바로 가시죠", "뭐라고요?" 등)도 모두 이전 테이크의 일부이므로 자릅니다.
- 테이크 사이의 잡담, 반응, 독백도 자릅니다 (filler).

## 판단 기준:
1. **중복 (duplicate)**: 이전 테이크에 속한 세그먼트. 마지막 테이크에서 같은 내용을 다루므로 자름.
   - **마지막 테이크 우선 원칙**: 화자가 같은 말을 다시 시도했다는 것은 이전 테이크가 마음에 안 들었다는 뜻이고, 마지막 테이크 후에 다음 내용으로 넘어갔으므로 그것이 채택된 버전입니다.
   - 단, 마지막 테이크가 명백히 불완전하거나 끊긴 경우에만 더 완성도 높은 이전 테이크를 선택하세요.
2. **불완전 (incomplete)**: 문장이 중간에 끊기거나 말을 더듬은 경우
3. **필러 (filler)**: 의미 없는 말, 망설임, "어...", "음...", 테이크 사이의 잡담/반응 등

## 중요:
- 내용이 다르고 서로 다른 테이크에 속하지 않는 독립적인 정보는 둘 다 유지하세요.
- 이전 테이크에 속한 세그먼트는 문장 단위로 비교하지 말고 **테이크 단위**로 통째로 자르세요.
- 최종 테이크 이후에 나오는 새로운 내용(다음 주제 등)은 유지하세요.

## 출력 형식 (JSON):
```json
{{{{
  "analysis": [
    {{{{
      "segment_index": 1,
      "action": "cut",
      "reason": "duplicate",
      "note": "segment 6의 인트로가 더 완성도 높음."
    }}}},
    {{{{
      "segment_index": 6,
      "action": "keep",
      "reason": "best_take",
      "note": "인트로 중 가장 완성도 높은 버전."
    }}}}
  ]
}}}}
```

**중요**: 각 결정에 대해 반드시 구체적인 `note`를 작성하세요.
reason 값: "duplicate", "incomplete", "filler", "best_take", "unique"

JSON만 출력하세요.'''


ANALYSIS_PROMPT = '''당신은 영상 편집 전문가입니다. 아래 자막 세그먼트들을 분석해서 어떤 부분을 잘라야 하는지 판단해주세요.

## 자막 세그먼트들:
{segments}

## 분석 방법 — 반드시 3단계로 수행하세요:

### 1단계: 테이크(녹화 시도) 구분
먼저 전체 자막을 읽고 **테이크 경계**를 파악하세요.
화자가 처음부터 다시 시작하거나, 같은 내용을 다시 말하기 시작하면 새로운 테이크입니다.
예: "안녕하세요, D2SF 왔습니다" 같은 인트로가 반복되면, 그 사이가 테이크 경계입니다.

### 2단계: 테이크 단위로 판단
- **같은 내용의 테이크가 여러 개 있으면, 마지막 테이크 전체를 살리고 이전 테이크 전체를 자르세요.**
- 이전 테이크에 속한 모든 세그먼트는 개별적으로 "유니크"해 보여도 자릅니다.
  이전 테이크의 마무리 멘트, 중간 멘트, 반응("바로 가시죠", "뭐라고요?" 등)도 모두 이전 테이크의 일부이므로 자릅니다.
- 테이크 사이의 잡담, 반응, 독백도 자릅니다 (filler).

### 3단계: 흐름 검토 (필수!)
판단을 마친 후, **keep으로 결정한 세그먼트만 순서대로 나열해서 읽어보세요.**
이것이 최종 영상의 자막입니다. 자연스러운 하나의 영상이 되는지 확인하세요.

검토 시 수정할 수 있는 것:
- 말더듬이나 불완전한 문장이 남아있으면 추가로 잘라주세요.
- 바로 뒤에 같은 내용의 더 완전한 문장이 있을 때, 앞의 불완전한 것을 잘라주세요.

검토 시 절대 하면 안 되는 것:
- **마지막 테이크로 선택한 인트로/본문을 다시 자르지 마세요.** 2단계에서 이미 최종 테이크로 결정한 것입니다.
- 다른 테이크에 비슷한 내용이 있다는 이유로 최종 테이크의 세그먼트를 자르지 마세요.

## 판단 기준:
1. **중복 (duplicate)**: 이전 테이크에 속한 세그먼트. 마지막 테이크에서 같은 내용을 다루므로 자름.
   - **마지막 테이크 우선 원칙**: 화자가 같은 말을 다시 시도했다는 것은 이전 테이크가 마음에 안 들었다는 뜻이고, 마지막 테이크 후에 다음 내용으로 넘어갔으므로 그것이 채택된 버전입니다.
   - 단, 마지막 테이크가 명백히 불완전하거나 끊긴 경우에만 더 완성도 높은 이전 테이크를 선택하세요.
2. **불완전 (incomplete)**: 문장이 중간에 끊기거나 말을 더듬은 경우
3. **필러 (filler)**: 의미 없는 말, 망설임, "어...", "음...", 테이크 사이의 잡담/반응 등

## 중요:
- 내용이 다르고 서로 다른 테이크에 속하지 않는 독립적인 정보는 둘 다 유지하세요.
- 이전 테이크에 속한 세그먼트는 문장 단위로 비교하지 말고 **테이크 단위**로 통째로 자르세요.
- 최종 테이크 이후에 나오는 새로운 내용(다음 주제 등)은 유지하세요.

## 출력 형식 (JSON):
```json
{{
  "analysis": [
    {{
      "segment_index": 1,
      "action": "cut",
      "reason": "duplicate",
      "note": "segment 6의 인트로가 더 완성도 높음. 문장 완결성과 발음 명확성 기준."
    }},
    {{
      "segment_index": 6,
      "action": "keep",
      "reason": "best_take",
      "note": "인트로 중 가장 완성도 높은 버전. 발음이 명확하고 문장이 완전함."
    }}
  ]
}}
```

**중요**: 각 결정에 대해 반드시 구체적인 `note`를 작성하세요.
왜 이 세그먼트를 자르거나 유지하는지, 어떤 기준으로 판단했는지 설명해주세요.

reason 값: "duplicate", "incomplete", "filler", "best_take", "unique"

JSON만 출력하세요.'''


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
    """Analyze a chunk of segments using Claude (2-step prompt, no flow review).

    Args:
        segments: Chunk of segments to analyze
        chunk_num: Current chunk number
        total_chunks: Total number of chunks
        storyline_context: Optional full storyline dict (will be filtered for chunk range)

    Returns:
        Tuple of (cuts, keeps) lists
    """
    segments_text = format_segments_for_prompt(segments)
    prompt = CHUNK_ANALYSIS_PROMPT.format(segments=segments_text)

    # Inject filtered storyline context for this chunk's range
    if storyline_context and segments:
        start_idx = segments[0].index
        end_idx = segments[-1].index
        context_text = format_filtered_context_for_prompt(storyline_context, start_idx, end_idx)
        prompt = context_text + "\n\n" + prompt

    print(f"  Processing chunk {chunk_num}/{total_chunks} ({len(segments)} segments)...")

    response = call_claude(prompt, timeout=300)
    data = parse_json_response(response)

    cuts = []
    keeps = []

    for item in data.get("analysis", []):
        seg_idx = item.get("segment_index")
        action = item.get("action")
        reason = item.get("reason", "")
        note = item.get("note", "")

        if action == "cut":
            cuts.append({"segment_index": seg_idx, "reason": reason, "note": note})
        else:
            keeps.append({"segment_index": seg_idx, "is_best_take": reason == "best_take", "note": note})

    return cuts, keeps


def analyze_with_claude(
    segments: list[SubtitleSegment],
    keep_alternatives: bool = False,
    storyline_context: dict | None = None,
) -> AnalysisResult:
    """Analyze subtitle segments using Claude CLI.

    Args:
        segments: List of subtitle segments to analyze
        keep_alternatives: If True, ask Claude to identify good alternatives
        storyline_context: Optional storyline dict from Pass 1 (transcript-overview)

    Returns:
        AnalysisResult with cuts and keeps
    """
    # Small transcript: single call with full 3-step prompt
    if len(segments) <= 150:
        segments_text = format_segments_for_prompt(segments)
        prompt = ANALYSIS_PROMPT.format(segments=segments_text)

        if storyline_context:
            context_text = format_context_for_prompt(storyline_context)
            prompt = context_text + "\n\n" + prompt

        if keep_alternatives:
            prompt += "\n\n추가로, 좋은 대안이 있는 경우 'has_alternative': true와 'alternative_to': [segment_index]를 추가해주세요."

        response = call_claude(prompt)

        try:
            data = parse_json_response(response)
        except (ValueError, Exception) as e:
            print(f"Failed to parse Claude response: {e}")
            print(f"Response: {response[:500]}")
            raise

        cuts = []
        keeps = []

        for item in data.get("analysis", []):
            seg_idx = item.get("segment_index")
            action = item.get("action")
            reason = item.get("reason", "")
            note = item.get("note", "")

            if action == "cut":
                cuts.append({"segment_index": seg_idx, "reason": reason, "note": note})
            else:
                keeps.append({"segment_index": seg_idx, "is_best_take": reason == "best_take", "note": note})

        return AnalysisResult(cuts=cuts, keeps=keeps, raw_response=response)
    else:
        # Large transcript: parallel chunk processing (2-step prompt, no flow review)
        print(f"  Large transcript ({len(segments)} segments). Using parallel chunk processing...")

        all_cuts, all_keeps = process_chunks_parallel(
            segments, CHUNK_SIZE, CHUNK_OVERLAP,
            analyze_fn=lambda chunk, num, total: analyze_chunk(chunk, num, total, storyline_context),
            max_workers=5,
        )

        return AnalysisResult(cuts=all_cuts, keeps=all_keeps)
