#!/usr/bin/env python3
"""Test merging multiple projects and exporting to FCPXML."""

import asyncio
import sys
from pathlib import Path

# Add backend src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "apps/backend/src"))

from avid.export import FCPXMLExporter
from avid.models.project import Project

SAMPLE_DIR = Path(__file__).parent.parent / "sample_projects"


def check_overlaps(project: Project) -> None:
    """Check and report overlapping edit decisions."""
    from collections import defaultdict

    # Group decisions by track
    by_track: dict[str, list] = defaultdict(list)
    for d in project.edit_decisions:
        by_track[d.active_video_track_id].append(d)

    for track_id, decisions in by_track.items():
        print(f"\nTrack: {track_id}")
        print(f"  Total edit decisions: {len(decisions)}")

        # Sort by start time
        sorted_decisions = sorted(decisions, key=lambda d: d.range.start_ms)

        # Find overlaps
        overlaps = []
        for i, d1 in enumerate(sorted_decisions):
            for d2 in sorted_decisions[i + 1 :]:
                # Check if d1 and d2 overlap
                if d1.range.end_ms > d2.range.start_ms:
                    overlaps.append((d1, d2))

        if overlaps:
            print(f"  Overlapping pairs found: {len(overlaps)}")
            for d1, d2 in overlaps:
                overlap_start = max(d1.range.start_ms, d2.range.start_ms)
                overlap_end = min(d1.range.end_ms, d2.range.end_ms)
                print(
                    f"    - [{d1.range.start_ms}-{d1.range.end_ms}] ({d1.reason}) "
                    f"& [{d2.range.start_ms}-{d2.range.end_ms}] ({d2.reason})"
                )
                print(f"      Overlap: {overlap_start}-{overlap_end} ({overlap_end - overlap_start}ms)")
        else:
            print("  No overlaps")


async def main():
    # Load individual projects
    project_files = [
        SAMPLE_DIR / "project_silence_cuts.avid.json",
        SAMPLE_DIR / "project_manual_cuts.avid.json",
    ]

    print("=" * 60)
    print("Testing Project Merge")
    print("=" * 60)

    # Merge projects that share A001 source
    print("\n1. Loading and merging projects...")
    merged = Project.load_and_merge(
        project_files, name="Merged Project - Silence + Manual"
    )

    print(f"   Merged project: {merged.name}")
    print(f"   Source files: {len(merged.source_files)}")
    print(f"   Tracks: {len(merged.tracks)}")
    print(f"   Edit decisions: {len(merged.edit_decisions)}")

    # Check for overlaps
    print("\n2. Checking for overlapping edit decisions...")
    check_overlaps(merged)

    # Save merged project
    merged_path = SAMPLE_DIR / "project_merged_silence_manual.avid.json"
    merged.save(merged_path)
    print(f"\n3. Saved merged project: {merged_path.name}")

    # Export to FCPXML
    exporter = FCPXMLExporter()

    # Export without disabled cuts (clean timeline)
    output_path = merged_path.with_suffix("").with_suffix(".fcpxml")
    await exporter.export(merged, output_path)
    print(f"\n4. Exported FCPXML: {output_path.name}")

    # Export with disabled cuts visible
    output_path_disabled = merged_path.with_suffix("").with_suffix(
        ".with_disabled.fcpxml"
    )
    await exporter.export(merged, output_path_disabled, show_disabled_cuts=True)
    print(f"   Exported FCPXML: {output_path_disabled.name} (with disabled cuts)")

    print("\n" + "=" * 60)
    print("Merge test completed!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
