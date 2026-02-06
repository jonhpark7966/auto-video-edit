#!/usr/bin/env python3
"""Main entry point for podcast cut skill.

Uses Claude or Codex CLI to analyze podcast transcripts for entertainment value
and decide what to cut based on engagement, not information efficiency.

Usage:
    python main.py <srt_file> <video_file> [options]

Options:
    --provider {claude,codex}   AI provider to use (default: claude)
    --edit-type {disabled,cut}  Default edit type for content edits (default: disabled)
    --output <path>             Output path for project JSON
    --source-id <id>            Use existing source file ID
    --report-only               Only print analysis report, don't save project
    --min-score <int>           Minimum entertainment score to keep (default: 4)
"""

import argparse
import json
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path

# Add skills directory to path for imports
skills_dir = Path(__file__).parent.parent
if str(skills_dir) not in sys.path:
    sys.path.insert(0, str(skills_dir))

from _common import parse_srt_file, get_video_info, load_storyline
from claude_analyzer import analyze_with_claude
from codex_analyzer import analyze_with_codex


def generate_deterministic_uuid(file_path: str) -> str:
    """Generate a deterministic UUID based on file path."""
    abs_path = os.path.abspath(file_path)
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, abs_path))


def reason_to_edit_reason(reason: str) -> str:
    """Convert podcast reason to EditReason string for AVID compatibility.

    Maps podcast-specific reasons to the extended EditReason enum.
    """
    # Direct mappings - these should match the extended EditReason enum
    direct_reasons = {
        # Cut reasons
        "boring", "tangent", "repetitive", "long_pause",
        "crosstalk", "irrelevant", "filler",
        # Keep reasons
        "funny", "witty", "chemistry", "reaction",
        "callback", "climax", "engaging", "emotional",
    }

    if reason in direct_reasons:
        return reason

    # Fallback for unknown reasons
    return "manual"


def generate_project_json(
    cuts: list[dict],
    segments: list,
    source_video_path: str,
    project_name: str,
    video_info: dict | None = None,
    source_file_id: str | None = None,
    edit_type: str = "disabled",
) -> dict:
    """Generate project JSON from podcast analysis.

    Args:
        cuts: List of cut decisions from analyzer
        segments: List of SubtitleSegment objects
        source_video_path: Path to source video
        project_name: Name for the project
        video_info: Video metadata (optional)
        source_file_id: Existing source file ID (optional)
        edit_type: "cut" or "disabled" - determines how content edits are handled
    """
    if source_file_id is None:
        source_file_id = generate_deterministic_uuid(source_video_path)

    if video_info is None:
        video_info = {
            "duration_ms": 120000,
            "width": 1920,
            "height": 1080,
            "fps": 30.0,
            "sample_rate": 48000,
        }

    project = {
        "name": project_name,
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
        "source_files": [
            {
                "id": source_file_id,
                "path": os.path.abspath(source_video_path),
                "original_name": Path(source_video_path).name,
                "info": video_info,
            }
        ],
        "tracks": [
            {
                "id": f"{source_file_id}_video",
                "source_file_id": source_file_id,
                "track_type": "video",
                "offset_ms": 0,
            },
            {
                "id": f"{source_file_id}_audio",
                "source_file_id": source_file_id,
                "track_type": "audio",
                "offset_ms": 0,
            },
        ],
        "transcription": None,
        "edit_decisions": [],
    }

    video_track_id = f"{source_file_id}_video"
    audio_track_id = f"{source_file_id}_audio"

    # Create segment lookup
    segment_map = {seg.index: seg for seg in segments}

    for cut in cuts:
        seg_idx = cut["segment_index"]
        seg = segment_map.get(seg_idx)
        if not seg:
            continue

        # Convert edit_type: "disabled" -> "mute" (for avid model compatibility)
        actual_edit_type = "mute" if edit_type == "disabled" else edit_type

        # Include entertainment_score in the note if present
        note = cut.get("note", "")
        entertainment_score = cut.get("entertainment_score")
        if entertainment_score is not None:
            note = f"[Score: {entertainment_score}/10] {note}"

        edit_decision = {
            "range": {
                "start_ms": seg.start_ms,
                "end_ms": seg.end_ms,
            },
            "edit_type": actual_edit_type,
            "reason": reason_to_edit_reason(cut.get("reason", "manual")),
            "confidence": 0.9,
            "note": note,
            "active_video_track_id": video_track_id,
            "active_audio_track_ids": [audio_track_id],
            "speed_factor": 1.0,
        }
        project["edit_decisions"].append(edit_decision)

    return project


def print_analysis_report(
    cuts: list[dict],
    keeps: list[dict],
    segments: list,
) -> None:
    """Print podcast analysis report with entertainment scores."""
    segment_map = {seg.index: seg for seg in segments}

    print("=" * 60)
    print("PODCAST ANALYSIS REPORT")
    print("=" * 60)
    print()
    print(f"Total segments: {len(segments)}")
    print(f"Segments to CUT: {len(cuts)}")
    print(f"Segments to KEEP: {len(keeps)}")

    # Calculate average entertainment scores
    if cuts:
        avg_cut_score = sum(c.get("entertainment_score", 5) for c in cuts) / len(cuts)
        print(f"Avg entertainment score (cuts): {avg_cut_score:.1f}")
    if keeps:
        avg_keep_score = sum(k.get("entertainment_score", 5) for k in keeps) / len(keeps)
        print(f"Avg entertainment score (keeps): {avg_keep_score:.1f}")
    print()

    if cuts:
        print("-" * 60)
        print("## CUTS (segments to remove)")
        print("-" * 60)
        for cut in sorted(cuts, key=lambda x: x.get("entertainment_score", 5)):
            seg = segment_map.get(cut["segment_index"])
            if not seg:
                continue
            time_str = f"{seg.start_ms // 1000}s - {seg.end_ms // 1000}s"
            score = cut.get("entertainment_score", "?")
            reason = cut.get("reason", "unknown")
            print(f"\n[{seg.index}] {time_str} ({reason}) [Score: {score}/10]")
            print(f"    \"{seg.text[:60]}{'...' if len(seg.text) > 60 else ''}\"")
            if cut.get("note"):
                print(f"    -> {cut['note']}")

    if keeps:
        print()
        print("-" * 60)
        print("## KEEPS (segments to preserve)")
        print("-" * 60)
        # Sort by entertainment score (highest first)
        for keep in sorted(keeps, key=lambda x: x.get("entertainment_score", 5), reverse=True):
            seg = segment_map.get(keep["segment_index"])
            if not seg:
                continue
            time_str = f"{seg.start_ms // 1000}s - {seg.end_ms // 1000}s"
            score = keep.get("entertainment_score", "?")
            reason = keep.get("reason", "unknown")

            # Highlight high-score segments
            highlight = " ★" if score and score >= 8 else ""
            print(f"\n[{seg.index}] {time_str} ({reason}) [Score: {score}/10]{highlight}")
            print(f"    \"{seg.text[:60]}{'...' if len(seg.text) > 60 else ''}\"")
            if keep.get("note"):
                print(f"    -> {keep['note']}")

    print()
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="Analyze podcast transcripts for entertainment value and generate edit decisions"
    )
    parser.add_argument("srt_file", help="Path to SRT subtitle file")
    parser.add_argument("video_file", help="Path to source video file")
    parser.add_argument(
        "--provider",
        choices=["claude", "codex"],
        default="codex",
        help="AI provider to use (default: codex)",
    )
    parser.add_argument(
        "--edit-type",
        choices=["disabled", "cut"],
        default="disabled",
        help="Default edit type for content edits (default: disabled)",
    )
    parser.add_argument("--output", "-o", help="Output path for project JSON")
    parser.add_argument("--source-id", help="Use existing source file ID")
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="Only print analysis report, don't save project",
    )
    parser.add_argument(
        "--min-score",
        type=int,
        default=4,
        help="Minimum entertainment score to keep (default: 4)",
    )
    parser.add_argument(
        "--context",
        help="Path to storyline.json from transcript-overview (Pass 1)",
    )

    args = parser.parse_args()

    srt_path = Path(args.srt_file)
    video_path = Path(args.video_file)

    if not srt_path.exists():
        print(f"Error: SRT file not found: {srt_path}", file=sys.stderr)
        sys.exit(1)

    # Parse SRT
    print(f"Parsing SRT file: {srt_path}")
    segments = parse_srt_file(str(srt_path))
    print(f"Found {len(segments)} subtitle segments")

    # Load storyline context if provided
    storyline_context = None
    if args.context:
        context_path = Path(args.context)
        if context_path.exists():
            print(f"Loading storyline context: {context_path}")
            storyline_context = load_storyline(str(context_path))
            print(f"  Chapters: {len(storyline_context.get('chapters', []))}")
            print(f"  Dependencies: {len(storyline_context.get('dependencies', []))}")
            print(f"  Key moments: {len(storyline_context.get('key_moments', []))}")
        else:
            print(f"Warning: Context file not found: {context_path}", file=sys.stderr)

    # Analyze with chosen provider
    print(f"\nAnalyzing podcast with {args.provider.upper()} for entertainment value...")
    if args.provider == "claude":
        result = analyze_with_claude(segments, storyline_context=storyline_context)
    else:
        result = analyze_with_codex(segments, storyline_context=storyline_context)

    # Print report
    print_analysis_report(result.cuts, result.keeps, segments)

    if args.report_only:
        return

    # Get video info
    video_info = None
    if video_path.exists():
        print("\nExtracting video metadata...")
        video_info = get_video_info(str(video_path))
        if video_info:
            print(f"  Duration: {video_info['duration_ms'] / 1000:.1f}s")
            print(f"  Resolution: {video_info['width']}x{video_info['height']}")
            print(f"  FPS: {video_info['fps']}")

    # Generate project
    output_path = args.output or str(srt_path.with_suffix("").with_suffix(".podcast.avid.json"))

    project = generate_project_json(
        cuts=result.cuts,
        segments=segments,
        source_video_path=str(video_path),
        project_name=f"Podcast Analysis - {srt_path.stem}",
        video_info=video_info,
        source_file_id=args.source_id,
        edit_type=args.edit_type,
    )

    # Save
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(project, f, ensure_ascii=False, indent=2)

    print(f"\nProject saved to: {output_path}")
    print(f"Edit decisions: {len(project['edit_decisions'])} cuts")
    print(f"Edit type: {args.edit_type}")


if __name__ == "__main__":
    main()
