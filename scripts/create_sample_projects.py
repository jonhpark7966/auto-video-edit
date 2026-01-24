#!/usr/bin/env python3
"""Create sample projects with random CUT edit decisions."""

import random
import sys
from pathlib import Path

# Add backend src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "apps/backend/src"))

from avid.models.media import MediaFile, MediaInfo
from avid.models.project import Project
from avid.models.timeline import EditDecision, EditReason, EditType, TimeRange

# Source files info
SRCS_DIR = Path(__file__).parent.parent / "srcs"
OUTPUT_DIR = Path(__file__).parent.parent / "sample_projects"


def create_media_file(filename: str, duration_ms: int, width: int, height: int, fps: float) -> MediaFile:
    """Create a MediaFile with given parameters."""
    return MediaFile(
        path=SRCS_DIR / filename,
        original_name=filename,
        info=MediaInfo(
            duration_ms=duration_ms,
            width=width,
            height=height,
            fps=fps,
            sample_rate=48000,
        ),
    )


def generate_random_cuts(
    duration_ms: int,
    num_cuts: int,
    reason: EditReason,
    video_track_id: str,
    audio_track_id: str,
) -> list[EditDecision]:
    """Generate random CUT edit decisions."""
    cuts = []
    # Generate random cut points, ensuring no overlap
    min_cut_duration = 500  # 0.5초 minimum
    max_cut_duration = 3000  # 3초 maximum

    # Generate random start points
    available_range = duration_ms - max_cut_duration
    if available_range <= 0:
        return cuts

    start_points = sorted(random.sample(range(0, available_range, 100), min(num_cuts, available_range // 100)))

    for start in start_points:
        cut_duration = random.randint(min_cut_duration, max_cut_duration)
        end = min(start + cut_duration, duration_ms)

        # Check for overlap with previous cuts
        if cuts and start < cuts[-1].range.end_ms + 1000:  # At least 1초 gap
            continue

        cuts.append(
            EditDecision(
                range=TimeRange(start_ms=start, end_ms=end),
                edit_type=EditType.CUT,
                reason=reason,
                confidence=round(random.uniform(0.7, 0.99), 2),
                active_video_track_id=video_track_id,
                active_audio_track_ids=[audio_track_id],
            )
        )

    return cuts


def main():
    OUTPUT_DIR.mkdir(exist_ok=True)

    # Create media files
    media_a001 = create_media_file(
        "A001_01241117_C310_compressed.mp4",
        duration_ms=75200,
        width=2160,
        height=3840,
        fps=30.0,
    )
    media_c1718 = create_media_file(
        "C1718_compressed.mp4",
        duration_ms=119619,
        width=3840,
        height=2160,
        fps=23.976,
    )

    # ===== Project 1: SILENCE reason only =====
    project1 = Project(name="Sample Project - Silence Cuts")
    tracks1 = project1.add_source_file(media_a001)
    video_track1 = next(t for t in tracks1 if t.is_video)
    audio_track1 = next(t for t in tracks1 if t.is_audio)

    project1.edit_decisions = generate_random_cuts(
        duration_ms=75200,
        num_cuts=5,
        reason=EditReason.SILENCE,
        video_track_id=video_track1.id,
        audio_track_id=audio_track1.id,
    )
    project1.save(OUTPUT_DIR / "project_silence_cuts.avid.json")
    print(f"Created: project_silence_cuts.avid.json ({len(project1.edit_decisions)} cuts)")

    # ===== Project 2: DUPLICATE + FILLER reasons =====
    project2 = Project(name="Sample Project - Duplicate & Filler Cuts")
    tracks2 = project2.add_source_file(media_c1718)
    video_track2 = next(t for t in tracks2 if t.is_video)
    audio_track2 = next(t for t in tracks2 if t.is_audio)

    # Generate DUPLICATE cuts
    duplicate_cuts = generate_random_cuts(
        duration_ms=60000,  # First half
        num_cuts=3,
        reason=EditReason.DUPLICATE,
        video_track_id=video_track2.id,
        audio_track_id=audio_track2.id,
    )
    # Generate FILLER cuts (second half)
    filler_cuts = generate_random_cuts(
        duration_ms=59619,
        num_cuts=4,
        reason=EditReason.FILLER,
        video_track_id=video_track2.id,
        audio_track_id=audio_track2.id,
    )
    # Offset filler cuts to second half
    for cut in filler_cuts:
        cut.range = TimeRange(
            start_ms=cut.range.start_ms + 60000,
            end_ms=cut.range.end_ms + 60000,
        )

    project2.edit_decisions = duplicate_cuts + filler_cuts
    project2.save(OUTPUT_DIR / "project_duplicate_filler_cuts.avid.json")
    print(f"Created: project_duplicate_filler_cuts.avid.json ({len(project2.edit_decisions)} cuts)")

    # ===== Project 3: MANUAL reason (both sources) =====
    project3 = Project(name="Sample Project - Manual Cuts (Multi-source)")
    tracks3_a = project3.add_source_file(media_a001)
    tracks3_b = project3.add_source_file(media_c1718)

    video_track3_a = next(t for t in tracks3_a if t.is_video)
    audio_track3_a = next(t for t in tracks3_a if t.is_audio)
    video_track3_b = next(t for t in tracks3_b if t.is_video)
    audio_track3_b = next(t for t in tracks3_b if t.is_audio)

    # Manual cuts on first source
    cuts_a = generate_random_cuts(
        duration_ms=75200,
        num_cuts=3,
        reason=EditReason.MANUAL,
        video_track_id=video_track3_a.id,
        audio_track_id=audio_track3_a.id,
    )
    # Manual cuts on second source
    cuts_b = generate_random_cuts(
        duration_ms=119619,
        num_cuts=4,
        reason=EditReason.MANUAL,
        video_track_id=video_track3_b.id,
        audio_track_id=audio_track3_b.id,
    )

    project3.edit_decisions = cuts_a + cuts_b
    project3.save(OUTPUT_DIR / "project_manual_cuts.avid.json")
    print(f"Created: project_manual_cuts.avid.json ({len(project3.edit_decisions)} cuts)")

    print(f"\nAll projects saved to: {OUTPUT_DIR}")


if __name__ == "__main__":
    random.seed(42)  # Reproducible randomness
    main()
