"""Codex CLI-based subtitle analysis for lecture/explanation videos.

Uses Codex CLI to semantically analyze subtitles and decide what to cut.
Focuses on removing duplicates, incomplete takes, and fillers.
"""

import sys
from pathlib import Path

# Add skills directory to path for imports
skills_dir = Path(__file__).parent.parent
if str(skills_dir) not in sys.path:
    sys.path.insert(0, str(skills_dir))

from _common import SubtitleSegment, AnalysisResult, call_codex, parse_json_response, format_context_for_prompt, format_filtered_context_for_prompt, process_chunks_parallel


# Chunk size for processing large transcripts
CHUNK_SIZE = 80
CHUNK_OVERLAP = 5


CHUNK_ANALYSIS_PROMPT = '''당신은 영상 편집 전문가입니다. 아래 자막 세그먼트들을 분석해서 어떤 부분을 잘라야 하는지 판단해주세요.

## 자막 세그먼트들:
{segments}

## 분석 방법 — 반드시 3단계로 수행하세요:

### 1단계: 촬영 메타 발화 식별
먼저 **촬영 과정 자체에 대한 발화**를 찾아서 모두 잘라주세요.
이것들은 영상 내용과 무관한 프로덕션 발화입니다:
- **프리롤**: 슬레이트("하나 둘 셋"), 마이크 체크/싱크, 카메라·조명 셋업 언급
- **포스트롤**: 촬영 종료 제안("여기까지 할까요?"), 피로 표현("힘들어"), 녹화 시간 확인("얼마나 했지?", "30분이나 했네"), 다음 촬영 계획("나머지는 간단하게 해야겠다"), 분량 걱정
- **리테이크 선언**: "다시 할게요", "처음부터", 다시 찍자는 대화
- **화면 전환·기술 이슈**: 화면 꺼짐 안내, 장비 문제 언급

### 2단계: 테이크(녹화 시도) 구분
나머지 세그먼트에서 **테이크 경계**를 파악하세요.
**주제 수준**에서 비교하세요 — 정확히 같은 단어가 아니어도, 같은 개념·정의·설명을 다시 시도하면 새로운 테이크입니다.

**테이크 경계 신호** (이런 것이 보이면 앞뒤로 테이크가 나뉩니다):
- 같은 용어를 다시 정의하기 시작하면 → 새 테이크
- 같은 개념을 처음부터 다시 설명하면 → 새 테이크
- 인트로/도입부가 반복되면 → 새 테이크
- **자기 수정 발화**: "말이 이상해", "아 아니다", "아니죠", "다시", "그게 아니라" → 앞의 세그먼트가 불만족스러운 이전 테이크
- **문장 수준 리테이크**: 거의 같은 문장이 연이어 나오면(단어만 약간 다름), 앞의 것이 이전 테이크
- **끊긴 시도 후 재시작**: 문장이 접속사(~는데, ~고, ~서, ~지만)로 끝나고 뒤이어 같은 내용을 더 완전하게 다시 시작하면, 끊긴 문장은 이전 테이크

### 3단계: 테이크 단위로 판단
- **같은 주제의 테이크가 여러 개 있으면, 마지막(가장 나중) 테이크 전체를 살리고 이전 테이크 전체를 자르세요.**
- 이전 테이크에 속한 모든 세그먼트는 개별적으로 "유니크"해 보여도 자릅니다.
  이전 테이크의 마무리 멘트, 중간 멘트, 반응("바로 가시죠", "뭐라고요?" 등)도 모두 이전 테이크의 일부이므로 자릅니다.
- 테이크 사이의 잡담, 반응, 독백도 자릅니다 (filler).
- **문장 수준 리테이크도 적용**: 단 한 문장이라도 바로 뒤에 같은 내용의 더 나은 문장이 있으면, 앞 문장을 자르세요.

## 판단 기준:
1. **중복 (duplicate)**: 이전 테이크에 속한 세그먼트. 나중 테이크에서 같은 주제를 다루므로 자름.
   - **마지막 테이크 우선 원칙**: 화자가 같은 내용을 다시 시도했다는 것은 이전 버전에 만족하지 못했다는 뜻입니다. 마지막 테이크가 채택된 버전입니다.
   - 단어가 다르더라도 같은 **주제·개념·정의**를 다시 설명하면 이전 것은 duplicate입니다.
   - **끊긴 문장 후 재시작**: 접속사(~는데, ~고, ~서)로 끝나는 미완성 문장 뒤에 같은 내용을 다시 시작하면, 미완성 문장은 duplicate입니다.
   - 단, 마지막 테이크가 명백히 불완전하거나 끊긴 경우에만 더 완성도 높은 이전 테이크를 선택하세요.
2. **불완전 (incomplete)**: 문장이 중간에 끊기거나 말을 더듬은 경우
3. **필러 (filler)**: 의미 없는 말, 망설임, "어...", "음...", 테이크 사이의 잡담/반응 등
   - **후행 접속 잔여**: 앞 문장의 내용을 이어가지 않고 접속사(~는데, ~고)로만 끝나는 짧은 문장은 filler입니다.
4. **촬영 메타 (meta_comment)**: 촬영 과정 자체에 대한 발화 (1단계에서 식별한 것)
5. **리테이크 선언 (retake_signal)**: 다시 촬영하겠다는 명시적 선언
6. **말실수 (fumble)**: 잘못된 설명, 말 꼬임, 발음 오류. **반드시** 뒤에서 화자가 스스로 교정하는 경우에만 해당 (예: "아니죠", "아 아니다", "그게 아니라" 등의 자기 수정이 뒤따라야 함). 단순히 생소한 용어나 약어가 나온다고 fumble로 판단하지 마세요.

## 중복이 아닌 것 (주의!):
- **나열형 설명**: "A 따로, B 따로, C가 아니라" 같은 목록의 각 항목은 하나의 논점을 구성하는 부분이지 중복이 아닙니다.
- **짧은 정의·요약**: "이게 X입니다", "P가 Y예요" 같은 한 줄 정의는 독립적 정보입니다.
- **보충 설명**: 같은 주제를 다른 각도에서 설명하는 것은 중복이 아니라 보충입니다.

## 필러가 아닌 것 (주의!):
- **주제 전환**: "그래서 현재~", "근데 여기서~" 같은 전환 문장은 흐름에 필요합니다.
- **구체적 사례·예시**: 추상적 개념 뒤에 나오는 실제 사례는 핵심 콘텐츠입니다.
- **맥락 설명**: 배경 정보를 제공하는 문장은 내용 이해에 필요합니다.
- **짧은 정의·결론**: "이게 X입니다", "~법칙이죠" 같은 한 줄 정의나 결론은 핵심 정보입니다.

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
      "reason": "meta_comment",
      "note": "슬레이트. 촬영 준비 발화."
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
reason 값: "duplicate", "incomplete", "filler", "meta_comment", "retake_signal", "fumble", "best_take", "unique"

JSON만 출력하세요.'''


ANALYSIS_PROMPT = '''당신은 영상 편집 전문가입니다. 아래 자막 세그먼트들을 분석해서 어떤 부분을 잘라야 하는지 판단해주세요.

## 자막 세그먼트들:
{segments}

## 분석 방법 — 반드시 4단계로 수행하세요:

### 1단계: 촬영 메타 발화 식별
먼저 **촬영 과정 자체에 대한 발화**를 찾아서 모두 잘라주세요.
이것들은 영상 내용과 무관한 프로덕션 발화입니다:
- **프리롤**: 슬레이트("하나 둘 셋"), 마이크 체크/싱크, 카메라·조명 셋업 언급
- **포스트롤**: 촬영 종료 제안("여기까지 할까요?"), 피로 표현("힘들어"), 녹화 시간 확인("얼마나 했지?", "30분이나 했네"), 다음 촬영 계획("나머지는 간단하게 해야겠다"), 분량 걱정
- **리테이크 선언**: "다시 할게요", "처음부터", 다시 찍자는 대화
- **화면 전환·기술 이슈**: 화면 꺼짐 안내, 장비 문제 언급

### 2단계: 테이크(녹화 시도) 구분
나머지 세그먼트에서 **테이크 경계**를 파악하세요.
**주제 수준**에서 비교하세요 — 정확히 같은 단어가 아니어도, 같은 개념·정의·설명을 다시 시도하면 새로운 테이크입니다.

**테이크 경계 신호** (이런 것이 보이면 앞뒤로 테이크가 나뉩니다):
- 같은 용어를 다시 정의하기 시작하면 → 새 테이크
- 같은 개념을 처음부터 다시 설명하면 → 새 테이크
- 인트로/도입부가 반복되면 → 새 테이크
- **자기 수정 발화**: "말이 이상해", "아 아니다", "아니죠", "다시", "그게 아니라" → 앞의 세그먼트가 불만족스러운 이전 테이크
- **문장 수준 리테이크**: 거의 같은 문장이 연이어 나오면(단어만 약간 다름), 앞의 것이 이전 테이크
- **끊긴 시도 후 재시작**: 문장이 접속사(~는데, ~고, ~서, ~지만)로 끝나고 뒤이어 같은 내용을 더 완전하게 다시 시작하면, 끊긴 문장은 이전 테이크

### 3단계: 테이크 단위로 판단
- **같은 주제의 테이크가 여러 개 있으면, 마지막(가장 나중) 테이크 전체를 살리고 이전 테이크 전체를 자르세요.**
- 이전 테이크에 속한 모든 세그먼트는 개별적으로 "유니크"해 보여도 자릅니다.
  이전 테이크의 마무리 멘트, 중간 멘트, 반응("바로 가시죠", "뭐라고요?" 등)도 모두 이전 테이크의 일부이므로 자릅니다.
- 테이크 사이의 잡담, 반응, 독백도 자릅니다 (filler).
- **문장 수준 리테이크도 적용**: 단 한 문장이라도 바로 뒤에 같은 내용의 더 나은 문장이 있으면, 앞 문장을 자르세요.

### 4단계: 흐름 검토 (필수!)
판단을 마친 후, **keep으로 결정한 세그먼트만 순서대로 나열해서 읽어보세요.**
이것이 최종 영상의 자막입니다. 자연스러운 하나의 영상이 되는지 확인하세요.

검토 시 수정할 수 있는 것:
- 말더듬이나 불완전한 문장이 남아있으면 추가로 잘라주세요.
- 바로 뒤에 같은 내용의 더 완전한 문장이 있을 때, 앞의 불완전한 것을 잘라주세요.

검토 시 절대 하면 안 되는 것:
- **마지막 테이크로 선택한 인트로/본문을 다시 자르지 마세요.** 3단계에서 이미 최종 테이크로 결정한 것입니다.
- 다른 테이크에 비슷한 내용이 있다는 이유로 최종 테이크의 세그먼트를 자르지 마세요.

## 판단 기준:
1. **중복 (duplicate)**: 이전 테이크에 속한 세그먼트. 나중 테이크에서 같은 주제를 다루므로 자름.
   - **마지막 테이크 우선 원칙**: 화자가 같은 내용을 다시 시도했다는 것은 이전 버전에 만족하지 못했다는 뜻입니다. 마지막 테이크가 채택된 버전입니다.
   - 단어가 다르더라도 같은 **주제·개념·정의**를 다시 설명하면 이전 것은 duplicate입니다.
   - **끊긴 문장 후 재시작**: 접속사(~는데, ~고, ~서)로 끝나는 미완성 문장 뒤에 같은 내용을 다시 시작하면, 미완성 문장은 duplicate입니다.
   - 단, 마지막 테이크가 명백히 불완전하거나 끊긴 경우에만 더 완성도 높은 이전 테이크를 선택하세요.
2. **불완전 (incomplete)**: 문장이 중간에 끊기거나 말을 더듬은 경우
3. **필러 (filler)**: 의미 없는 말, 망설임, "어...", "음...", 테이크 사이의 잡담/반응 등
   - **후행 접속 잔여**: 앞 문장의 내용을 이어가지 않고 접속사(~는데, ~고)로만 끝나는 짧은 문장은 filler입니다.
4. **촬영 메타 (meta_comment)**: 촬영 과정 자체에 대한 발화 (1단계에서 식별한 것)
5. **리테이크 선언 (retake_signal)**: 다시 촬영하겠다는 명시적 선언
6. **말실수 (fumble)**: 잘못된 설명, 말 꼬임, 발음 오류. **반드시** 뒤에서 화자가 스스로 교정하는 경우에만 해당 (예: "아니죠", "아 아니다", "그게 아니라" 등의 자기 수정이 뒤따라야 함). 단순히 생소한 용어나 약어가 나온다고 fumble로 판단하지 마세요.

## 중복이 아닌 것 (주의!):
- **나열형 설명**: "A 따로, B 따로, C가 아니라" 같은 목록의 각 항목은 하나의 논점을 구성하는 부분이지 중복이 아닙니다.
- **짧은 정의·요약**: "이게 X입니다", "P가 Y예요" 같은 한 줄 정의는 독립적 정보입니다.
- **보충 설명**: 같은 주제를 다른 각도에서 설명하는 것은 중복이 아니라 보충입니다.

## 필러가 아닌 것 (주의!):
- **주제 전환**: "그래서 현재~", "근데 여기서~" 같은 전환 문장은 흐름에 필요합니다.
- **구체적 사례·예시**: 추상적 개념 뒤에 나오는 실제 사례는 핵심 콘텐츠입니다.
- **맥락 설명**: 배경 정보를 제공하는 문장은 내용 이해에 필요합니다.
- **짧은 정의·결론**: "이게 X입니다", "~법칙이죠" 같은 한 줄 정의나 결론은 핵심 정보입니다.

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
      "reason": "meta_comment",
      "note": "슬레이트. 촬영 준비 발화."
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

reason 값: "duplicate", "incomplete", "filler", "meta_comment", "retake_signal", "fumble", "best_take", "unique"

JSON만 출력하세요.'''


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
    """Analyze a chunk of segments using Codex (2-step prompt, no flow review).

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

    response = call_codex(prompt, timeout=300)
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


def analyze_with_codex(
    segments: list[SubtitleSegment],
    keep_alternatives: bool = False,
    storyline_context: dict | None = None,
) -> AnalysisResult:
    """Analyze subtitle segments using Codex CLI.

    Args:
        segments: List of subtitle segments to analyze
        keep_alternatives: If True, ask Codex to identify good alternatives
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

        response = call_codex(prompt)

        try:
            data = parse_json_response(response)
        except (ValueError, Exception) as e:
            print(f"Failed to parse Codex response: {e}")
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
