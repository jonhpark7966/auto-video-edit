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

from _common import (
    SubtitleSegment,
    call_codex,
    parse_json_response,
    format_filtered_context_for_prompt,
    format_podcast_context_for_prompt,
    process_chunks_parallel,
    apply_boundary_aware_prompt,
    apply_junction_coherence_guard,
    resolve_boundary_repairs,
    format_segments_with_boundary_metadata,
    is_boundary_aware_version,
    normalize_edit_decision_version,
)
from models import PodcastAnalysisResult
from prompt_profiles import PromptProfile, render_edit_decision_prompt


# Chunk size for processing large transcripts
CHUNK_SIZE = 80  # Process 80 segments at a time
CHUNK_OVERLAP = 5  # Overlap to maintain context
LLM_TIMEOUT_SECONDS = 600
LLM_MAX_ATTEMPTS = 3


def _edit_intensity_guidance(edit_intensity: str = "normal") -> str:
    normalized = edit_intensity if edit_intensity in {"light", "normal", "heavy"} else "normal"
    labels = {
        "light": "적게 편집",
        "normal": "일반 편집",
        "heavy": "많이 편집",
    }
    details = {
        "light": [
            "- 메타 발화, 명백한 실수, 긴 침묵, 완전 중복 위주로만 cut하세요.",
            "- 약한 반복이나 보충 대화는 남은 흐름이 자연스러우면 keep하세요.",
        ],
        "normal": [
            "- 중복, 필러, 불완전 문장, 늘어지는 구간을 균형 있게 제거하세요.",
            "- 질문-답변 흐름과 대화 전환 문장은 적극적으로 보존하세요.",
        ],
        "heavy": [
            "- 재미와 핵심 전개를 직접 강화하지 않는 반복, 느슨한 보충 대화, 낮은 정보 밀도 구간까지 cut 후보로 보세요.",
            "- 애매한 bridge segment는 자동 keep하지 말고, 앞뒤를 합쳐 읽었을 때 setup/payoff나 문장 완성에 필요한 경우에만 keep하세요.",
            "- 남은 결과가 요약 조각처럼 끊기지 않는 선에서 과감하게 압축하세요.",
        ],
    }
    keep_targets = {
        "light": "60-75%",
        "normal": "35-55%",
        "heavy": "20-40%",
    }
    lines = [
        "## 컷 편집 강도 지시 (최우선)",
        f"- 선택된 편집 강도: {labels[normalized]}",
        f"- 목표 keep 비율: 전체 segment 중 {keep_targets[normalized]}만 남기는 방향으로 판단하세요.",
        "- 이 강도에 맞춰 cut/keep을 판단하세요.",
        "- 남은 segment들의 맥락은 자연스럽게 이어져야 하지만, 맥락 보존을 이유로 저밀도 보충 대화까지 남기지 마세요.",
        "- 질문만 남거나 답변만 남는 컷, setup 없이 payoff만 남는 컷, 전환 문장 제거로 흐름이 끊기는 컷은 피하세요.",
        "- 애매한 세그먼트는 편집 강도와 목표 keep 비율에 맞춰 cut 쪽으로 재검토하세요.",
        *details[normalized],
    ]
    return "\n".join(lines)


def _apply_edit_intensity_guidance(prompt: str, edit_intensity: str = "normal") -> str:
    return _edit_intensity_guidance(edit_intensity) + "\n\n" + prompt


MIXED_SPEAKER_HANDLING_PROMPT = """## Mixed speaker handling
- `speaker=mixed` means the segment may contain speech from multiple speakers, often because overlap-protection merged adjacent overlapped speech into one review unit.
- Do not treat `speaker=mixed` by itself as a reason to CUT.
- Do not classify a segment as `crosstalk` only because `speaker=mixed`.
- Use `crosstalk` only when the text itself is hard to understand, semantically unusable, or the overlapping speech prevents a coherent edit.
- If a `speaker=mixed` segment contains understandable content that connects to adjacent KEEP segments, judge it by content and boundary continuity, not by the mixed speaker label.
- If cutting a `speaker=mixed` segment would leave the previous or next KEEP segment as an incomplete sentence, prefer KEEP or use a keep repair.
"""


PODCAST_ANALYSIS_PROMPT = '''당신은 유명 유튜브 하이라이트 편집자입니다. 긴 팟캐스트에서 **재미있는 부분만 골라내는** 전문가입니다.

## 핵심 원칙
당신의 목표는 **과감하게 자르는 것**입니다.
시청자는 10분짜리 하이라이트를 원하지, 40분짜리 약간 다듬은 버전을 원하지 않습니다.
**"이거 꼭 남겨야 해?"** 라고 자문하세요. 확신이 없으면 자르세요.

## 자막 세그먼트들:
{segments}

## 인접 segment 연결성 규칙
- 각 segment에는 `gap_from_prev_ms`, `gap_to_next_ms`, `speaker`가 함께 제공됩니다.
- `gap_from_prev_ms` 또는 `gap_to_next_ms`가 500ms 미만이면 앞뒤 segment와 거의 붙어 있는 연속 대화로 간주하세요.
- 연속 대화 안의 segment 하나만 CUT하면 대화가 뚝 끊길 수 있습니다.
- 짧은 응답, 화자 전환 직후 발화, "그러니까", "제가 아까 말씀드린 것처럼", "네", "아", "그게" 같은 bridge 발화는 filler처럼 보여도 연결에 필요할 수 있습니다.
- 불완전해 보이는 fragment는 segmentation/chunk artifact일 수 있으므로 이전/다음 segment와 합쳐 실제 문장으로 읽은 뒤 CUT/KEEP을 판단하세요.
- 짧거나 정보량이 낮아 보여도 다음/이전 KEEP segment의 문장을 완성하면 CUT하지 마세요.
- 예: "약간 그것만 좀" + "다르다고 생각해요"는 이어서 읽어야 자연스러운 한 문장입니다.
- 예: "왜냐하면 AI 시대가" + "되어서..." 또는 "그걸 사람들이 막" + "체감한다는 얘기가..."처럼 다음 segment가 문장을 완성하면 앞 조각을 filler로 자르지 마세요.
- 남은 KEEP sequence가 자연스럽게 읽히는지가 짧음/낮은 정보량보다 우선입니다.
- chunk 경계 때문에 생긴 미완성처럼 보이는 조각만으로 fumble 또는 filler로 판단하지 마세요.
- CUT하기 전에 이전/다음 segment가 KEEP될 때 자연스럽게 이어지는지 반드시 확인하세요.
- gap 500ms 미만인 segment를 CUT한다면 note에 앞뒤 연결이 자연스러운 이유를 구체적으로 쓰세요.

## 분석 방법 — 반드시 2단계로 수행하세요:

### 1단계: 먼저 자를 것을 찾기
아래 기준에 해당하면 CUT입니다:
1. **지루함 (boring)**: 에너지 낮은 구간, 흥미 없는 설명, 단답 연속, 그냥 평범한 대화
2. **탈선 (tangent)**: 본 주제와 무관한 대화. 사적 잡담(개인 근황, 안부), 주제 이탈 질문, 호스트 간 본론 무관 장난/놀림, 방송 마무리 수다, 짧은 무의미 감탄("미쳤네", "몰라"). **주제 내 마이크로 탈선도 포함**: 핵심 논의를 진전시키지 않는 짧은 질문/언급, 이름·제품 드롭, "~는 어때?" 식 단순 호기심.
3. **반복 (repetitive)**: 같은 이야기를 다시 하거나, 이미 한 설명을 반복
4. **긴 침묵 (long_pause)**: 3초 이상의 불필요한 침묵
5. **겹침 (crosstalk)**: 동시에 말해서 알아듣기 어려운 구간
6. **무관함 (irrelevant)**: 시청자에게 무관한 내용 (TMI, 사적인 이야기, inside joke)
7. **필러 (filler)**: "어...", "음...", "그래서...", 의미 없는 추임새
8. **늘어짐 (dragging)**: 핵심 없이 질질 끄는 구간. 같은 포인트를 돌려 말하기.
9. **메타 발언 (meta_comment)**: 제작 과정에 관한 대화. 촬영 전 준비(장비 체크, 채팅 설정, 카운트다운), 콘텐츠 기획/포맷 논의, 방송 중 기술 오류 확인(링크 깨짐, 자동 업로드 안 됨), 콘텐츠 진행 조정("이건 스킵하자", "다음에 하죠").
10. **말더듬 (fumble)**: 명백한 발음 실수나 잘못 말한 단어 뒤에 화자가 곧바로 자기수정/재시작하는 경우. segmentation/chunk 경계 때문에 불완전해 보이는 fragment만으로 fumble 처리하지 마세요
11. **재촬영 신호 (retake_signal)**: "다시", "잠깐만", "아 씨" 등 명시적으로 다시 하겠다는 선언

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
- 주제 내에서도 본론에 직접 기여하지 않는 짧은 감탄, 사적 호기심, 호스트 간 놀림은 CUT.
- "같은 주제 내 발언" ≠ keep. 해당 토론의 핵심 포인트를 직접 진전시키는 발언만 keep.
- 짧은 세그먼트(1-2문장)라도 본론에 기여하지 않으면 CUT. "짧아서 해가 안 됨"은 keep 이유가 아닙니다.
- 에피소드 초반(인사/근황)과 후반(마무리/정리) 구간은 특히 과감하게 자르세요.

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
- 전체를 약간 다듬는 것이 아니라, 편집 강도 지시의 목표 keep 비율에 맞춰 충분히 잘라야 합니다.
- CUT 이유: "boring", "tangent", "repetitive", "long_pause", "crosstalk", "irrelevant", "filler", "dragging", "meta_comment", "fumble", "retake_signal"
- KEEP 이유: "funny", "witty", "chemistry", "reaction", "callback", "climax", "engaging", "emotional"

JSON만 출력하세요.'''


def _has_mixed_speaker(segments: list[SubtitleSegment]) -> bool:
    return any(str(seg.speaker or "").strip().lower() == "mixed" for seg in segments)


def _apply_mixed_speaker_guidance(prompt: str, segments: list[SubtitleSegment]) -> str:
    if not _has_mixed_speaker(segments):
        return prompt

    marker = "\n\n## 인접 segment 연결성 규칙"
    if marker not in prompt:
        return prompt + "\n\n" + MIXED_SPEAKER_HANDLING_PROMPT
    return prompt.replace(marker, "\n\n" + MIXED_SPEAKER_HANDLING_PROMPT + marker, 1)


def _apply_podcast_principles(context_text: str) -> str:
    """Replace generic editing principles with podcast-specific ones."""
    generic_marker = "### 편집 원칙"
    if generic_marker in context_text:
        idx = context_text.index(generic_marker)
        context_text = context_text[:idx]
        context_text += "### 편집 원칙 (팟캐스트 하이라이트)\n"
        context_text += "- setup → payoff 쌍은 함께 유지 (setup만 있고 payoff가 없으면 둘 다 자르기)\n"
        context_text += "- 콜백 유머의 원본은 유지\n"
        context_text += "- 챕터 importance와 핵심 순간은 참고용. 세그먼트 자체의 entertainment value가 최종 기준\n"
        context_text += "- intro/outro/근황 토크/세팅 챕터의 세그먼트는 대부분 CUT 대상\n"
        context_text += "- 핵심 챕터라도 지루한 구간은 자르기 — 챕터 전체를 살릴 필요 없음"
    return context_text


def format_segments_for_prompt(
    segments: list[SubtitleSegment],
    edit_decision_version: str = "legacy",
) -> str:
    """Format segments for the Codex prompt."""
    if is_boundary_aware_version(edit_decision_version):
        return format_segments_with_boundary_metadata(segments)

    lines = []
    for i, seg in enumerate(segments):
        prev_seg = segments[i - 1] if i > 0 else None
        next_seg = segments[i + 1] if i + 1 < len(segments) else None
        gap_from_prev = (
            str(max(0, seg.start_ms - prev_seg.end_ms)) if prev_seg else "unknown"
        )
        gap_to_next = (
            str(max(0, next_seg.start_ms - seg.end_ms)) if next_seg else "unknown"
        )
        speaker = seg.speaker or "unknown"
        lines.append(
            f"[{seg.index}] {seg.start_ms}ms-{seg.end_ms}ms "
            f"speaker={speaker} "
            f"gap_from_prev_ms={gap_from_prev} "
            f"gap_to_next_ms={gap_to_next}\n"
            f"text: \"{seg.text}\""
        )
    return "\n".join(lines)


def _decision_segment_index(item: dict) -> int | None:
    value = item.get("segment_index")
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _validate_decision_coverage(
    segments: list[SubtitleSegment],
    cuts: list[dict],
    keeps: list[dict],
) -> None:
    expected = {seg.index for seg in segments}
    covered: set[int] = set()
    invalid = 0
    for item in [*cuts, *keeps]:
        idx = _decision_segment_index(item)
        if idx is None:
            invalid += 1
        elif idx in expected:
            covered.add(idx)

    missing = sorted(expected - covered)
    if missing or invalid:
        sample = ", ".join(str(idx) for idx in missing[:20])
        suffix = "..." if len(missing) > 20 else ""
        raise RuntimeError(
            "Podcast analysis did not return a cut/keep decision for every segment "
            f"(segments={len(expected)}, covered={len(covered)}, "
            f"missing={len(missing)}, invalid={invalid}; "
            f"missing_sample=[{sample}{suffix}])"
        )


def _parse_podcast_analysis_response(
    response: str,
    edit_decision_version: str,
    segments: list[SubtitleSegment],
) -> tuple[list[dict], list[dict]]:
    data = parse_json_response(response)

    items = []
    entries = []
    actions = []

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
        items.append(item)
        entries.append(entry)
        actions.append(action)

    cuts, keeps = resolve_boundary_repairs(
        items,
        entries,
        actions,
        segment_indices=[seg.index for seg in segments],
        edit_decision_version=edit_decision_version,
    )
    return apply_junction_coherence_guard(segments, cuts, keeps)


def _analyze_prompt_once(
    prompt: str,
    segments: list[SubtitleSegment],
    edit_decision_version: str,
) -> tuple[str, list[dict], list[dict]]:
    response = call_codex(prompt, timeout=LLM_TIMEOUT_SECONDS)
    cuts, keeps = _parse_podcast_analysis_response(
        response,
        edit_decision_version,
        segments,
    )
    _validate_decision_coverage(segments, cuts, keeps)
    return response, cuts, keeps


def _retry_analysis(call_once, label: str):
    last_error: Exception | None = None
    for attempt in range(1, LLM_MAX_ATTEMPTS + 1):
        try:
            return call_once()
        except Exception as e:
            last_error = e
            if attempt >= LLM_MAX_ATTEMPTS:
                break
            print(
                f"  {label} failed on attempt {attempt}/{LLM_MAX_ATTEMPTS}: "
                f"{type(e).__name__}: {e}; retrying..."
            )

    assert last_error is not None
    raise last_error


def analyze_chunk_once(
    segments: list[SubtitleSegment],
    chunk_num: int,
    total_chunks: int,
    storyline_context: dict | None = None,
    edit_intensity: str = "normal",
    edit_decision_version: str = "legacy",
    prompt_profile: PromptProfile = "podcast",
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
    edit_decision_version = normalize_edit_decision_version(edit_decision_version)
    segments_text = format_segments_for_prompt(segments, edit_decision_version)
    prompt = render_edit_decision_prompt(
        prompt_profile,
        segments_text,
        podcast_prompt=PODCAST_ANALYSIS_PROMPT,
    )
    prompt = _apply_mixed_speaker_guidance(prompt, segments)

    # Inject filtered storyline context for this chunk's range
    if storyline_context and segments:
        start_idx = segments[0].index
        end_idx = segments[-1].index
        context_text = format_filtered_context_for_prompt(storyline_context, start_idx, end_idx)
        context_text = _apply_podcast_principles(context_text)
        prompt = context_text + "\n\n" + prompt

    prompt = apply_boundary_aware_prompt(
        prompt,
        edit_decision_version=edit_decision_version,
        include_entertainment_score=True,
    )
    prompt = _apply_edit_intensity_guidance(prompt, edit_intensity)

    _, cuts, keeps = _analyze_prompt_once(prompt, segments, edit_decision_version)
    return cuts, keeps


def analyze_chunk(
    segments: list[SubtitleSegment],
    chunk_num: int,
    total_chunks: int,
    storyline_context: dict | None = None,
    edit_intensity: str = "normal",
    edit_decision_version: str = "legacy",
    prompt_profile: PromptProfile = "podcast",
) -> tuple[list[dict], list[dict]]:
    """Analyze a chunk of segments using Codex with retry."""
    print(f"  Processing chunk {chunk_num}/{total_chunks} ({len(segments)} segments)...")
    return _retry_analysis(
        lambda: analyze_chunk_once(
            segments=segments,
            chunk_num=chunk_num,
            total_chunks=total_chunks,
            storyline_context=storyline_context,
            edit_intensity=edit_intensity,
            edit_decision_version=edit_decision_version,
            prompt_profile=prompt_profile,
        ),
        f"chunk {chunk_num}/{total_chunks}",
    )


def analyze_with_codex(
    segments: list[SubtitleSegment],
    storyline_context: dict | None = None,
    edit_intensity: str = "normal",
    edit_decision_version: str = "legacy",
    prompt_profile: PromptProfile = "podcast",
) -> PodcastAnalysisResult:
    """Analyze podcast segments using Codex CLI.

    For large transcripts, processes in chunks to avoid timeout.

    Args:
        segments: List of subtitle segments to analyze
        storyline_context: Optional storyline dict from Pass 1 (transcript-overview)

    Returns:
        PodcastAnalysisResult with cuts, keeps, and entertainment scores
    """
    edit_decision_version = normalize_edit_decision_version(edit_decision_version)

    # Process in chunks if too many segments
    if len(segments) <= CHUNK_SIZE:
        # Small enough to process at once
        segments_text = format_segments_for_prompt(segments, edit_decision_version)
        prompt = render_edit_decision_prompt(
            prompt_profile,
            segments_text,
            podcast_prompt=PODCAST_ANALYSIS_PROMPT,
        )
        prompt = _apply_mixed_speaker_guidance(prompt, segments)

        # Inject storyline context if available
        if storyline_context:
            context_text = format_podcast_context_for_prompt(storyline_context)
            prompt = context_text + "\n\n" + prompt

        prompt = apply_boundary_aware_prompt(
            prompt,
            edit_decision_version=edit_decision_version,
            include_entertainment_score=True,
        )
        prompt = _apply_edit_intensity_guidance(prompt, edit_intensity)

        response, all_cuts, all_keeps = _retry_analysis(
            lambda: _analyze_prompt_once(prompt, segments, edit_decision_version),
            "full transcript",
        )
        return PodcastAnalysisResult(cuts=all_cuts, keeps=all_keeps, raw_response=response)
    else:
        # Parallel chunk processing
        all_cuts, all_keeps = process_chunks_parallel(
            segments, CHUNK_SIZE, CHUNK_OVERLAP,
            analyze_fn=lambda chunk, num, total: analyze_chunk(
                segments=chunk,
                chunk_num=num,
                total_chunks=total,
                storyline_context=storyline_context,
                edit_intensity=edit_intensity,
                edit_decision_version=edit_decision_version,
                prompt_profile=prompt_profile,
            ),
            max_workers=5,
        )

        _validate_decision_coverage(segments, all_cuts, all_keeps)
        return PodcastAnalysisResult(cuts=all_cuts, keeps=all_keeps)
