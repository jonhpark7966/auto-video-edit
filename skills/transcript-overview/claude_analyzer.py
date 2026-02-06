"""Claude-based transcript overview analysis (Pass 1).

Analyzes the full transcript to produce a storyline overview:
narrative arc, chapters, key moments, dependencies, and pacing notes.

Adapts to transcript size:
- ≤150 segments: Full segments in one call
- 151-400: Compressed format (index + first 80 chars + timestamp)
- 400+: Two-step — Step A (chapter boundaries) → Step B (per-chapter analysis) → merge
"""

import json
import sys
from pathlib import Path

# Add skills directory to path for imports
skills_dir = Path(__file__).parent.parent
if str(skills_dir) not in sys.path:
    sys.path.insert(0, str(skills_dir))

from _common import SubtitleSegment, call_claude, parse_json_response
from models import (
    TranscriptOverview,
    NarrativeArc,
    Chapter,
    KeyMoment,
    Dependency,
    PacingNotes,
    PacingSection,
)


OVERVIEW_PROMPT = '''당신은 전문 영상 편집자이자 스토리 분석가입니다.
전체 자막을 읽고 스토리 구조를 분석해주세요.

## 전체 자막:
{segments}

## 분석 항목:

1. **narrative_arc**: 콘텐츠 유형(lecture/podcast/interview), 요약, 전체 흐름, 톤(educational/entertaining/mixed)
2. **chapters**: 챕터 분할
   - id: "ch_1", "ch_2" 형식
   - title: 챕터 제목
   - start_segment, end_segment: 시작/끝 세그먼트 인덱스
   - summary: 챕터 요약
   - role: intro, context, main_topic, deep_dive, tangent, transition, climax, conclusion, qa, outro 중 하나
   - importance: 1-10 (전체 내용에서의 중요도)
   - topics: 주요 키워드 목록
3. **key_moments**: 핵심 순간
   - segment_index: 세그먼트 번호
   - type: highlight, emotional_peak, callback, punchline, setup 중 하나
   - description: 설명
   - chapter_id: 속한 챕터 ID
   - references: 참조하는 다른 세그먼트 번호 (callback일 때)
4. **dependencies**: 의존성 쌍 (함께 유지해야 하는 세그먼트들)
   - type: setup_payoff, callback, qa_pair, running_joke 중 하나
   - setup_segments: 앞 세그먼트 번호들
   - payoff_segments: 뒤 세그먼트 번호들
   - description: 왜 함께 유지해야 하는지
   - strength: required(반드시), strong(강력 권장), moderate(권장)
5. **pacing_notes**: 페이싱 메모
   - slow_sections: 느리지만 필수적인 구간 (start_segment, end_segment, note)
   - high_energy_sections: 에너지 높은 구간

## 출력 형식 (JSON):
```json
{{
  "narrative_arc": {{
    "type": "lecture",
    "summary": "전체 요약",
    "flow": "인트로 → 배경 → 핵심 → 사례 → 결론",
    "tone": "educational"
  }},
  "chapters": [
    {{
      "id": "ch_1", "title": "인트로",
      "start_segment": 1, "end_segment": 15,
      "summary": "인사 및 주제 소개",
      "role": "intro", "importance": 8,
      "topics": ["인사", "주제 예고"]
    }}
  ],
  "key_moments": [
    {{"segment_index": 42, "type": "highlight", "description": "핵심 인사이트", "chapter_id": "ch_2"}}
  ],
  "dependencies": [
    {{
      "type": "setup_payoff",
      "setup_segments": [25, 26], "payoff_segments": [98, 99],
      "description": "배경 설명이 핵심 주장의 근거",
      "strength": "strong"
    }}
  ],
  "pacing_notes": {{
    "slow_sections": [{{"start_segment": 60, "end_segment": 75, "note": "이후 논점에 필수적"}}],
    "high_energy_sections": [{{"start_segment": 100, "end_segment": 130, "note": "활발한 대화"}}]
  }}
}}
```

**중요**:
- 챕터는 빠짐없이 전체 자막을 커버해야 합니다.
- 의존성은 편집 시 함께 유지해야 하는 쌍만 식별하세요.
- 핵심 순간은 절대 자르면 안 되는 부분입니다.
- JSON만 출력하세요.'''


CHAPTER_BOUNDARY_PROMPT = '''당신은 전문 영상 편집자입니다.
아래 긴 자막에서 주제가 바뀌는 지점을 찾아 챕터 경계를 나눠주세요.

## 자막 (압축):
{segments}

## 출력 형식 (JSON):
```json
{{
  "chapters": [
    {{"start_segment": 1, "end_segment": 50, "title": "인트로", "role": "intro"}},
    {{"start_segment": 51, "end_segment": 120, "title": "AI 코딩 현황", "role": "main_topic"}},
    {{"start_segment": 121, "end_segment": 200, "title": "실제 사례", "role": "deep_dive"}}
  ],
  "narrative_arc": {{
    "type": "lecture",
    "summary": "전체 요약 (1-2문장)",
    "flow": "인트로 → 주제1 → 주제2 → 결론",
    "tone": "educational"
  }}
}}
```

JSON만 출력하세요.'''


CHAPTER_DETAIL_PROMPT = '''당신은 전문 영상 편집자이자 스토리 분석가입니다.
아래 챕터의 자막을 읽고 상세 분석해주세요.

## 챕터: {chapter_title} (세그먼트 {start_seg}-{end_seg})
## 전체 흐름: {overall_flow}

## 자막:
{segments}

## 분석 항목:
1. **importance**: 1-10 (전체 내용에서 이 챕터의 중요도)
2. **topics**: 주요 키워드
3. **summary**: 챕터 요약
4. **key_moments**: 이 챕터의 핵심 순간들
5. **dependencies**: 이 챕터 내 또는 다른 챕터와의 의존성
6. **pacing**: 느린 구간, 고에너지 구간

## 출력 형식 (JSON):
```json
{{
  "importance": 8,
  "topics": ["주제1", "주제2"],
  "summary": "챕터 요약",
  "key_moments": [
    {{"segment_index": 42, "type": "highlight", "description": "핵심 인사이트"}}
  ],
  "dependencies": [
    {{
      "type": "setup_payoff",
      "setup_segments": [25], "payoff_segments": [38],
      "description": "배경 → 결론",
      "strength": "strong"
    }}
  ],
  "slow_sections": [{{"start_segment": 30, "end_segment": 35, "note": "이후 논점에 필수적"}}],
  "high_energy_sections": [{{"start_segment": 40, "end_segment": 45, "note": "핵심 설명"}}]
}}
```

JSON만 출력하세요.'''


def format_segments_full(segments: list[SubtitleSegment]) -> str:
    """Format segments with full text."""
    lines = []
    for seg in segments:
        time_str = f"{seg.start_ms // 1000}s - {seg.end_ms // 1000}s"
        lines.append(f"[{seg.index}] ({time_str}): \"{seg.text}\"")
    return "\n".join(lines)


def format_segments_compressed(segments: list[SubtitleSegment]) -> str:
    """Format segments in compressed form (index + first 80 chars + timestamp)."""
    lines = []
    for seg in segments:
        text_preview = seg.text[:80] + ("..." if len(seg.text) > 80 else "")
        lines.append(f"[{seg.index}] ({seg.start_ms // 1000}s): {text_preview}")
    return "\n".join(lines)


def _analyze_small(segments: list[SubtitleSegment]) -> dict:
    """Analyze ≤150 segments in a single call."""
    segments_text = format_segments_full(segments)
    prompt = OVERVIEW_PROMPT.format(segments=segments_text)

    response = call_claude(prompt, timeout=300)
    return parse_json_response(response)


def _analyze_medium(segments: list[SubtitleSegment]) -> dict:
    """Analyze 151-400 segments with compressed format."""
    segments_text = format_segments_compressed(segments)
    prompt = OVERVIEW_PROMPT.format(segments=segments_text)

    response = call_claude(prompt, timeout=300)
    return parse_json_response(response)


def _analyze_large(segments: list[SubtitleSegment]) -> dict:
    """Analyze 400+ segments in two steps: chapter boundaries → per-chapter details."""
    segment_map = {seg.index: seg for seg in segments}

    # Step A: Find chapter boundaries using compressed format
    print("  Step A: Finding chapter boundaries...")
    segments_text = format_segments_compressed(segments)
    boundary_prompt = CHAPTER_BOUNDARY_PROMPT.format(segments=segments_text)

    boundary_response = call_claude(boundary_prompt, timeout=300)
    boundary_data = parse_json_response(boundary_response)

    chapters_raw = boundary_data.get("chapters", [])
    narrative_arc = boundary_data.get("narrative_arc", {})
    overall_flow = narrative_arc.get("flow", "")

    if not chapters_raw:
        # Fallback: treat as single chapter
        chapters_raw = [{
            "start_segment": segments[0].index,
            "end_segment": segments[-1].index,
            "title": "Main Content",
            "role": "main_topic",
        }]

    # Step B: Analyze each chapter in detail
    print(f"  Step B: Analyzing {len(chapters_raw)} chapters in detail...")
    all_key_moments = []
    all_dependencies = []
    all_slow_sections = []
    all_high_energy_sections = []
    enriched_chapters = []

    for i, ch_raw in enumerate(chapters_raw):
        start_seg = ch_raw.get("start_segment", 0)
        end_seg = ch_raw.get("end_segment", 0)
        ch_title = ch_raw.get("title", f"Chapter {i + 1}")
        ch_role = ch_raw.get("role", "main_topic")

        # Get segments for this chapter
        chapter_segments = [
            seg for seg in segments
            if start_seg <= seg.index <= end_seg
        ]

        if not chapter_segments:
            enriched_chapters.append({
                "id": f"ch_{i + 1}",
                "title": ch_title,
                "start_segment": start_seg,
                "end_segment": end_seg,
                "summary": "",
                "role": ch_role,
                "importance": 5,
                "topics": [],
            })
            continue

        print(f"    Analyzing chapter {i + 1}/{len(chapters_raw)}: {ch_title}...")

        chapter_text = format_segments_full(chapter_segments)
        detail_prompt = CHAPTER_DETAIL_PROMPT.format(
            chapter_title=ch_title,
            start_seg=start_seg,
            end_seg=end_seg,
            overall_flow=overall_flow,
            segments=chapter_text,
        )

        try:
            detail_response = call_claude(detail_prompt, timeout=180)
            detail_data = parse_json_response(detail_response)
        except Exception as e:
            print(f"    Warning: Chapter detail analysis failed: {e}")
            detail_data = {}

        chapter_id = f"ch_{i + 1}"
        enriched_chapters.append({
            "id": chapter_id,
            "title": ch_title,
            "start_segment": start_seg,
            "end_segment": end_seg,
            "summary": detail_data.get("summary", ""),
            "role": ch_role,
            "importance": detail_data.get("importance", 5),
            "topics": detail_data.get("topics", []),
        })

        # Collect key moments with chapter_id
        for km in detail_data.get("key_moments", []):
            km["chapter_id"] = chapter_id
            all_key_moments.append(km)

        all_dependencies.extend(detail_data.get("dependencies", []))
        all_slow_sections.extend(detail_data.get("slow_sections", []))
        all_high_energy_sections.extend(detail_data.get("high_energy_sections", []))

    return {
        "narrative_arc": narrative_arc,
        "chapters": enriched_chapters,
        "key_moments": all_key_moments,
        "dependencies": all_dependencies,
        "pacing_notes": {
            "slow_sections": all_slow_sections,
            "high_energy_sections": all_high_energy_sections,
        },
    }


def analyze_with_claude(
    segments: list[SubtitleSegment],
    content_type: str = "auto",
) -> TranscriptOverview:
    """Analyze full transcript to produce storyline overview.

    Adapts processing strategy to segment count:
    - ≤150: Full segments in one call
    - 151-400: Compressed format
    - 400+: Two-step (chapters → details)

    Args:
        segments: All subtitle segments
        content_type: "lecture", "podcast", or "auto"

    Returns:
        TranscriptOverview with complete storyline analysis
    """
    num_segments = len(segments)
    print(f"  Transcript size: {num_segments} segments")

    if num_segments <= 150:
        print("  Strategy: Single call (full segments)")
        data = _analyze_small(segments)
    elif num_segments <= 400:
        print("  Strategy: Single call (compressed)")
        data = _analyze_medium(segments)
    else:
        print("  Strategy: Two-step (chapter boundaries → per-chapter details)")
        data = _analyze_large(segments)

    # Build segment lookup for timestamps
    segment_map = {seg.index: seg for seg in segments}

    # Parse narrative arc
    arc_data = data.get("narrative_arc", {})
    if content_type != "auto":
        arc_data["type"] = content_type

    # Enrich chapters with timestamps from segments
    chapters_data = data.get("chapters", [])
    for ch in chapters_data:
        start_seg = segment_map.get(ch.get("start_segment"))
        end_seg = segment_map.get(ch.get("end_segment"))
        if start_seg:
            ch["start_ms"] = start_seg.start_ms
        if end_seg:
            ch["end_ms"] = end_seg.end_ms

    # Calculate total duration
    total_duration_ms = 0
    if segments:
        total_duration_ms = segments[-1].end_ms

    # Build result
    overview = TranscriptOverview.from_dict({
        "version": "1.0",
        "total_segments": num_segments,
        "total_duration_ms": total_duration_ms,
        "narrative_arc": arc_data,
        "chapters": chapters_data,
        "key_moments": data.get("key_moments", []),
        "dependencies": data.get("dependencies", []),
        "pacing_notes": data.get("pacing_notes", {}),
    })

    return overview
