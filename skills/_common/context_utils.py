"""Context utilities for Two-Pass editing architecture.

Provides functions to:
- Load storyline JSON context from Pass 1
- Format storyline context for inclusion in Pass 2 prompts
- Filter context for a specific segment range (used by chunk-based processing)
"""

import json
from pathlib import Path


def load_storyline(path: str | Path) -> dict:
    """Load storyline JSON from file.

    Args:
        path: Path to storyline.json

    Returns:
        Storyline dict
    """
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def format_context_for_prompt(storyline: dict) -> str:
    """Format full storyline context for insertion into Pass 2 prompt.

    Used by subtitle-cut which processes all segments at once.

    Args:
        storyline: Full storyline dict from Pass 1

    Returns:
        Formatted context string for prompt injection
    """
    lines = []
    lines.append("## 스토리 구조 컨텍스트 (반드시 참고!)")
    lines.append("")

    # Narrative arc
    arc = storyline.get("narrative_arc", {})
    lines.append("### 전체 요약")
    if arc.get("summary"):
        lines.append(f"{arc['summary']}")
    if arc.get("flow"):
        lines.append(f"흐름: {arc['flow']}")
    if arc.get("tone"):
        lines.append(f"톤: {arc['tone']}")
    lines.append("")

    # Chapters
    chapters = storyline.get("chapters", [])
    if chapters:
        lines.append("### 챕터 구조")
        for ch in chapters:
            ch_id = ch.get("id", "")
            title = ch.get("title", "")
            start = ch.get("start_segment", 0)
            end = ch.get("end_segment", 0)
            importance = ch.get("importance", 5)
            summary = ch.get("summary", "")
            role = ch.get("role", "")
            topics_str = ", ".join(ch.get("topics", []))

            line = f"[{ch_id}] {title} (seg {start}-{end}, importance: {importance}, role: {role})"
            if summary:
                line += f" — {summary}"
            if topics_str:
                line += f" [{topics_str}]"
            lines.append(line)
        lines.append("")

    # Dependencies
    deps = storyline.get("dependencies", [])
    if deps:
        lines.append("### 의존성 (함께 유지해야 하는 세그먼트)")
        for dep in deps:
            strength = dep.get("strength", "moderate")
            strength_label = {"required": "필수", "strong": "강력", "moderate": "권장"}.get(strength, strength)
            dep_type = dep.get("type", "")
            setup = dep.get("setup_segments", [])
            payoff = dep.get("payoff_segments", [])
            desc = dep.get("description", "")
            lines.append(f"- [{strength_label}] seg {setup} → seg {payoff}: {desc} ({dep_type})")
        lines.append("")

    # Key moments
    key_moments = storyline.get("key_moments", [])
    if key_moments:
        lines.append("### 핵심 순간 (반드시 유지)")
        for km in key_moments:
            seg_idx = km.get("segment_index", 0)
            km_type = km.get("type", "")
            desc = km.get("description", "")
            refs = km.get("references", [])
            line = f"- seg {seg_idx}: [{km_type}] {desc}"
            if refs:
                line += f" (참조: seg {refs})"
            lines.append(line)
        lines.append("")

    # Editing principles
    lines.append("### 편집 원칙")
    lines.append("- 의존성이 있는 세그먼트는 함께 유지하세요 (setup을 자르면 payoff가 의미 없음)")
    lines.append("- 핵심 순간은 반드시 유지하세요")
    lines.append("- 중요도 ≥ 7인 챕터는 보수적으로 편집하세요")
    lines.append("- 느린 구간이라도 이후 논점에 필수적이면 유지하세요")

    return "\n".join(lines)


def filter_context_for_range(storyline: dict, start_idx: int, end_idx: int) -> dict:
    """Filter storyline context for a specific segment index range.

    Used by podcast-cut which processes in chunks.
    Keeps only chapters, dependencies, key_moments that overlap with the range.
    Always includes narrative_arc.

    Args:
        storyline: Full storyline dict
        start_idx: Start segment index (inclusive)
        end_idx: End segment index (inclusive)

    Returns:
        Filtered storyline dict
    """
    filtered = {
        "narrative_arc": storyline.get("narrative_arc", {}),
        "chapters": [],
        "key_moments": [],
        "dependencies": [],
        "pacing_notes": {"slow_sections": [], "high_energy_sections": []},
    }

    # Filter chapters that overlap with range
    for ch in storyline.get("chapters", []):
        ch_start = ch.get("start_segment", 0)
        ch_end = ch.get("end_segment", 0)
        if ch_start <= end_idx and ch_end >= start_idx:
            filtered["chapters"].append(ch)

    # Filter key moments within range
    for km in storyline.get("key_moments", []):
        seg_idx = km.get("segment_index", 0)
        if start_idx <= seg_idx <= end_idx:
            filtered["key_moments"].append(km)

    # Filter dependencies that touch the range
    for dep in storyline.get("dependencies", []):
        setup_segs = dep.get("setup_segments", [])
        payoff_segs = dep.get("payoff_segments", [])
        all_segs = setup_segs + payoff_segs

        # Include if any segment falls within the range
        if any(start_idx <= s <= end_idx for s in all_segs):
            filtered["dependencies"].append(dep)

    # Filter pacing notes
    pacing = storyline.get("pacing_notes", {})
    for section in pacing.get("slow_sections", []):
        s_start = section.get("start_segment", 0)
        s_end = section.get("end_segment", 0)
        if s_start <= end_idx and s_end >= start_idx:
            filtered["pacing_notes"]["slow_sections"].append(section)

    for section in pacing.get("high_energy_sections", []):
        s_start = section.get("start_segment", 0)
        s_end = section.get("end_segment", 0)
        if s_start <= end_idx and s_end >= start_idx:
            filtered["pacing_notes"]["high_energy_sections"].append(section)

    return filtered


def format_filtered_context_for_prompt(storyline: dict, start_idx: int, end_idx: int) -> str:
    """Filter and format context for a specific segment range.

    Convenience function that combines filter + format.
    Used by podcast-cut for chunk-level context injection.

    Args:
        storyline: Full storyline dict
        start_idx: Start segment index
        end_idx: End segment index

    Returns:
        Formatted context string for the range
    """
    filtered = filter_context_for_range(storyline, start_idx, end_idx)
    return format_context_for_prompt(filtered)


def format_podcast_context_for_prompt(storyline: dict) -> str:
    """Format storyline context with podcast-specific editing principles.

    Similar to format_context_for_prompt but adds podcast-specific rules.

    Args:
        storyline: Full or filtered storyline dict

    Returns:
        Formatted context string for podcast prompt injection
    """
    base = format_context_for_prompt(storyline)

    # Replace generic editing principles with podcast-specific ones
    generic_principles = "### 편집 원칙"
    if generic_principles in base:
        idx = base.index(generic_principles)
        base = base[:idx]

    lines = [base.rstrip()]
    lines.append("### 편집 원칙 (팟캐스트)")
    lines.append("- 의존성이 있는 세그먼트는 함께 유지하세요 (setup을 자르면 payoff가 의미 없음)")
    lines.append("- 핵심 순간은 반드시 유지하세요")
    lines.append("- 지루해 보여도 이후 payoff가 있는 setup은 유지")
    lines.append("- 콜백 유머의 원본을 자르면 안 됨")
    lines.append("- Q&A 쌍은 함께 유지")
    lines.append("- 고에너지 구간 사이의 쉼(breathing room)은 자르지 마세요")
    lines.append("- 중요도 ≥ 7인 챕터는 보수적으로 편집하세요")

    return "\n".join(lines)
