#!/usr/bin/env python3
"""Main entry point for transcript-overview skill (Pass 1).

Analyzes full SRT transcript to produce a storyline overview:
narrative arc, chapters, key moments, dependencies, and pacing notes.

The output (storyline.json) is used as context by Pass 2 skills
(subtitle-cut, podcast-cut) for context-aware editing decisions.

Usage:
    python main.py <srt_file> [options]

Options:
    --provider {claude,codex}   AI provider to use (default: codex)
    --output <path>             Output path for storyline JSON
    --content-type {lecture,podcast,auto}  Content type hint (default: auto)
"""

import argparse
import json
import sys
from pathlib import Path

# Add skills directory to path for imports
skills_dir = Path(__file__).parent.parent
if str(skills_dir) not in sys.path:
    sys.path.insert(0, str(skills_dir))

from _common import parse_srt_file
from claude_analyzer import analyze_with_claude
from codex_analyzer import analyze_with_codex


def print_overview_report(overview) -> None:
    """Print a human-readable summary of the storyline analysis."""
    print("=" * 60)
    print("TRANSCRIPT OVERVIEW REPORT")
    print("=" * 60)
    print()

    arc = overview.narrative_arc
    print(f"Type: {arc.type}")
    print(f"Tone: {arc.tone}")
    print(f"Summary: {arc.summary}")
    print(f"Flow: {arc.flow}")
    print(f"Total segments: {overview.total_segments}")
    print(f"Total duration: {overview.total_duration_ms / 1000:.1f}s")
    print()

    # Chapters
    print("-" * 60)
    print(f"## CHAPTERS ({len(overview.chapters)})")
    print("-" * 60)
    for ch in overview.chapters:
        time_start = ch.start_ms // 1000
        time_end = ch.end_ms // 1000
        print(f"\n[{ch.id}] {ch.title} (seg {ch.start_segment}-{ch.end_segment}, {time_start}s-{time_end}s)")
        print(f"    Role: {ch.role} | Importance: {ch.importance}/10")
        if ch.summary:
            print(f"    {ch.summary}")
        if ch.topics:
            print(f"    Topics: {', '.join(ch.topics)}")

    # Key moments
    if overview.key_moments:
        print()
        print("-" * 60)
        print(f"## KEY MOMENTS ({len(overview.key_moments)})")
        print("-" * 60)
        for km in overview.key_moments:
            refs = f" -> refs {km.references}" if km.references else ""
            print(f"  seg {km.segment_index}: [{km.type}] {km.description}{refs}")

    # Dependencies
    if overview.dependencies:
        print()
        print("-" * 60)
        print(f"## DEPENDENCIES ({len(overview.dependencies)})")
        print("-" * 60)
        for dep in overview.dependencies:
            strength_label = {"required": "필수", "strong": "강력", "moderate": "권장"}.get(dep.strength, dep.strength)
            print(f"  [{strength_label}] {dep.type}: seg {dep.setup_segments} → seg {dep.payoff_segments}")
            print(f"    {dep.description}")

    # Pacing
    pacing = overview.pacing_notes
    if pacing.slow_sections or pacing.high_energy_sections:
        print()
        print("-" * 60)
        print("## PACING NOTES")
        print("-" * 60)
        for s in pacing.slow_sections:
            print(f"  [Slow] seg {s.start_segment}-{s.end_segment}: {s.note}")
        for s in pacing.high_energy_sections:
            print(f"  [High Energy] seg {s.start_segment}-{s.end_segment}: {s.note}")

    print()
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="Analyze transcript structure and produce storyline overview (Pass 1)"
    )
    parser.add_argument("srt_file", help="Path to SRT subtitle file")
    parser.add_argument(
        "--provider",
        choices=["claude", "codex"],
        default="codex",
        help="AI provider to use (default: codex)",
    )
    parser.add_argument(
        "--output", "-o",
        help="Output path for storyline JSON (default: <srt_stem>.storyline.json)",
    )
    parser.add_argument(
        "--content-type",
        choices=["lecture", "podcast", "auto"],
        default="auto",
        help="Content type hint (default: auto)",
    )

    args = parser.parse_args()

    srt_path = Path(args.srt_file)
    if not srt_path.exists():
        print(f"Error: SRT file not found: {srt_path}", file=sys.stderr)
        sys.exit(1)

    # Parse SRT
    print(f"Parsing SRT file: {srt_path}")
    segments = parse_srt_file(str(srt_path))
    print(f"Found {len(segments)} subtitle segments")

    # Analyze
    print(f"\nAnalyzing transcript structure with {args.provider.upper()}...")
    if args.provider == "claude":
        overview = analyze_with_claude(segments, content_type=args.content_type)
    else:
        overview = analyze_with_codex(segments, content_type=args.content_type)
    overview.source_srt = str(srt_path)

    # Print report
    print_overview_report(overview)

    # Save
    output_path = args.output or str(srt_path.with_suffix("").with_suffix(".storyline.json"))
    overview_dict = overview.to_dict()

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(overview_dict, f, ensure_ascii=False, indent=2)

    print(f"\nStoryline saved to: {output_path}")
    print(f"  Chapters: {len(overview.chapters)}")
    print(f"  Key moments: {len(overview.key_moments)}")
    print(f"  Dependencies: {len(overview.dependencies)}")


if __name__ == "__main__":
    main()
