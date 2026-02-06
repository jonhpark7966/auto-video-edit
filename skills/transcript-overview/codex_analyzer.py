"""Codex-based transcript overview analysis (Pass 1).

Analyzes the full transcript to produce a storyline overview:
narrative arc, chapters, key moments, dependencies, and pacing notes.

Uses Codex CLI (codex exec) with gpt-5.2 model.

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

from _common import SubtitleSegment, call_codex, parse_json_response
from models import (
    TranscriptOverview,
    NarrativeArc,
    Chapter,
    KeyMoment,
    Dependency,
    PacingNotes,
    PacingSection,
)

# Reuse prompts from claude_analyzer
from claude_analyzer import (
    OVERVIEW_PROMPT,
    CHAPTER_BOUNDARY_PROMPT,
    CHAPTER_DETAIL_PROMPT,
    format_segments_full,
    format_segments_compressed,
)


def _analyze_small(segments: list[SubtitleSegment]) -> dict:
    """Analyze ≤150 segments in a single call."""
    segments_text = format_segments_full(segments)
    prompt = OVERVIEW_PROMPT.format(segments=segments_text)

    response = call_codex(prompt, timeout=300)
    return parse_json_response(response)


def _analyze_medium(segments: list[SubtitleSegment]) -> dict:
    """Analyze 151-400 segments with compressed format."""
    segments_text = format_segments_compressed(segments)
    prompt = OVERVIEW_PROMPT.format(segments=segments_text)

    response = call_codex(prompt, timeout=300)
    return parse_json_response(response)


def _analyze_large(segments: list[SubtitleSegment]) -> dict:
    """Analyze 400+ segments in two steps: chapter boundaries → per-chapter details."""
    segment_map = {seg.index: seg for seg in segments}

    # Step A: Find chapter boundaries using compressed format
    print("  Step A: Finding chapter boundaries...")
    segments_text = format_segments_compressed(segments)
    boundary_prompt = CHAPTER_BOUNDARY_PROMPT.format(segments=segments_text)

    boundary_response = call_codex(boundary_prompt, timeout=300)
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
            detail_response = call_codex(detail_prompt, timeout=180)
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


def analyze_with_codex(
    segments: list[SubtitleSegment],
    content_type: str = "auto",
) -> TranscriptOverview:
    """Analyze full transcript to produce storyline overview using Codex.

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
