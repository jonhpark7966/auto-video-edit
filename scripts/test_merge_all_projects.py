#!/usr/bin/env python3
"""Test merging ALL sample projects and exporting to FCPXML."""

import asyncio
import sys
from pathlib import Path

# Add backend src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "apps/backend/src"))

from avid.export import FCPXMLExporter
from avid.models.project import Project

SAMPLE_DIR = Path(__file__).parent.parent / "sample_projects"


def print_edit_decisions(project: Project) -> None:
    """Print all edit decisions grouped by track."""
    from collections import defaultdict

    by_track: dict[str, list] = defaultdict(list)
    for d in project.edit_decisions:
        by_track[d.active_video_track_id].append(d)

    for track_id, decisions in sorted(by_track.items()):
        # Get source name
        track = project.get_track(track_id)
        source = project.get_source_file(track.source_file_id) if track else None
        source_name = source.original_name if source else "Unknown"

        print(f"\n  [{source_name}] - {len(decisions)} cuts")
        sorted_decisions = sorted(decisions, key=lambda d: d.range.start_ms)
        for d in sorted_decisions:
            print(f"    {d.range.start_ms:>6} - {d.range.end_ms:<6} ({d.reason.value})")


async def main():
    print("=" * 70)
    print("Merging ALL Sample Projects")
    print("=" * 70)

    # Find all .avid.json files (exclude merged ones)
    all_projects = sorted([
        p for p in SAMPLE_DIR.glob("*.avid.json")
        if "merged" not in p.name
    ])

    print(f"\nFound {len(all_projects)} project files:")
    for p in all_projects:
        print(f"  - {p.name}")

    # Load and merge all
    print("\n" + "-" * 70)
    print("Merging projects...")
    merged = Project.load_and_merge(all_projects, name="All Projects Merged")

    print(f"\nMerged Result:")
    print(f"  Source files: {len(merged.source_files)}")
    for sf in merged.source_files:
        print(f"    - {sf.original_name}")
    print(f"  Tracks: {len(merged.tracks)}")
    print(f"  Edit decisions: {len(merged.edit_decisions)}")

    print_edit_decisions(merged)

    # Check overlaps
    print("\n" + "-" * 70)
    print("Checking overlaps...")

    from collections import defaultdict
    by_track: dict[str, list] = defaultdict(list)
    for d in merged.edit_decisions:
        by_track[d.active_video_track_id].append(d)

    total_overlaps = 0
    for track_id, decisions in by_track.items():
        sorted_decisions = sorted(decisions, key=lambda d: d.range.start_ms)
        for i, d1 in enumerate(sorted_decisions):
            for d2 in sorted_decisions[i + 1:]:
                if d1.range.end_ms > d2.range.start_ms:
                    total_overlaps += 1
                    overlap_start = max(d1.range.start_ms, d2.range.start_ms)
                    overlap_end = min(d1.range.end_ms, d2.range.end_ms)
                    print(f"  Overlap: [{d1.range.start_ms}-{d1.range.end_ms}] ({d1.reason.value}) "
                          f"& [{d2.range.start_ms}-{d2.range.end_ms}] ({d2.reason.value})")
                    print(f"           → {overlap_start}-{overlap_end} ({overlap_end - overlap_start}ms)")

    if total_overlaps == 0:
        print("  No overlaps found")
    else:
        print(f"\n  Total overlapping pairs: {total_overlaps}")

    # Save merged project
    print("\n" + "-" * 70)
    merged_path = SAMPLE_DIR / "project_all_merged.avid.json"
    merged.save(merged_path)
    print(f"Saved: {merged_path.name}")

    # Export to FCPXML
    exporter = FCPXMLExporter()

    output_path = merged_path.with_suffix("").with_suffix(".fcpxml")
    await exporter.export(merged, output_path)
    print(f"Exported: {output_path.name}")

    output_path_disabled = merged_path.with_suffix("").with_suffix(".with_disabled.fcpxml")
    await exporter.export(merged, output_path_disabled, show_disabled_cuts=True)
    print(f"Exported: {output_path_disabled.name} (with disabled cuts)")

    print("\n" + "=" * 70)
    print("Done!")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
