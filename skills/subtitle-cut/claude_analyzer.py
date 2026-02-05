"""Claude-based subtitle analysis.

Uses Claude CLI to semantically analyze subtitles and decide what to cut.
"""

import json
import subprocess

from srt_parser import SubtitleSegment
from models import AnalysisResult


ANALYSIS_PROMPT = '''당신은 영상 편집 전문가입니다. 아래 자막 세그먼트들을 분석해서 어떤 부분을 잘라야 하는지 판단해주세요.

## 자막 세그먼트들:
{segments}

## 판단 기준:
1. **중복 (duplicate)**: 같은 내용을 여러 번 말한 경우, 가장 완성도 높은 테이크만 남기고 나머지는 자름
   - 완성도 기준: 문장이 완전하고, 더 자연스럽고, 내용이 더 충실한 것
2. **불완전 (incomplete)**: 문장이 중간에 끊기거나 말을 더듬은 경우
3. **필러 (filler)**: 의미 없는 말, 망설임, "어...", "음..." 등

## 중요:
- 내용이 다르면 중복이 아닙니다. 비슷해 보여도 실제로 다른 정보를 전달하면 둘 다 유지하세요.
- 인트로를 여러 번 시도한 경우, 가장 좋은 것 하나만 남기세요.
- 같은 설명을 여러 번 한 경우, 가장 완전한 것 하나만 남기세요.

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


def call_claude(prompt: str) -> str:
    """Call Claude CLI and get response."""
    try:
        result = subprocess.run(
            ["claude", "-p", prompt, "--output-format", "text"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Claude CLI error: {result.stderr}")
        return result.stdout.strip()
    except FileNotFoundError:
        raise RuntimeError("Claude CLI not found. Please install claude-code.")
    except subprocess.TimeoutExpired:
        raise RuntimeError("Claude CLI timeout")


def parse_response(response: str) -> dict:
    """Parse Claude's JSON response."""
    # Find JSON in response
    start = response.find("{")
    end = response.rfind("}") + 1

    if start == -1 or end == 0:
        raise ValueError(f"No JSON found in response: {response[:200]}")

    json_str = response[start:end]
    return json.loads(json_str)


def analyze_with_claude(
    segments: list[SubtitleSegment],
    keep_alternatives: bool = False,
) -> AnalysisResult:
    """Analyze subtitle segments using Claude CLI.

    Args:
        segments: List of subtitle segments to analyze
        keep_alternatives: If True, ask Claude to identify good alternatives

    Returns:
        AnalysisResult with cuts and keeps
    """
    # Format prompt
    segments_text = format_segments_for_prompt(segments)
    prompt = ANALYSIS_PROMPT.format(segments=segments_text)

    if keep_alternatives:
        prompt += "\n\n추가로, 좋은 대안이 있는 경우 'has_alternative': true와 'alternative_to': [segment_index]를 추가해주세요."

    # Call Claude
    response = call_claude(prompt)

    # Parse response
    try:
        data = parse_response(response)
    except (json.JSONDecodeError, ValueError) as e:
        print(f"Failed to parse Claude response: {e}")
        print(f"Response: {response[:500]}")
        raise

    # Convert to result
    cuts = []
    keeps = []

    for item in data.get("analysis", []):
        seg_idx = item.get("segment_index")
        action = item.get("action")
        reason = item.get("reason", "")
        note = item.get("note", "")

        if action == "cut":
            cuts.append({
                "segment_index": seg_idx,
                "reason": reason,
                "note": note,
            })
        else:
            keeps.append({
                "segment_index": seg_idx,
                "is_best_take": reason == "best_take",
                "note": note,
            })

    return AnalysisResult(cuts=cuts, keeps=keeps, raw_response=response)
