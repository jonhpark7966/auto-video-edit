"""Subtitle cut analysis service using subtitle-cut skill.

Full workflow:
1. Run subtitle-cut skill via subprocess → content decisions (duplicates, filler)
2. Find silence gaps from SRT
3. Populate transcription from SRT
4. Merge content + silence → unified Project
"""

import asyncio
import re
import subprocess
import sys
from pathlib import Path

from avid.models.project import Project, Transcription, TranscriptSegment
from avid.models.timeline import EditDecision, EditReason, EditType, TimeRange


def _find_project_root() -> Path:
    """Find the project root (where skills/ lives)."""
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "skills").is_dir():
            return parent
    raise RuntimeError("Cannot find project root (skills/ directory not found)")


def _get_subtitle_cut_script() -> Path:
    """Get path to subtitle-cut main.py script."""
    root = _find_project_root()
    script = root / "skills" / "subtitle-cut" / "main.py"
    if not script.exists():
        raise RuntimeError(f"subtitle-cut script not found: {script}")
    return script


class SubtitleCutService:
    """Analyze subtitles for cut decisions and silence detection.

    Orchestrates:
    1. subtitle-cut skill subprocess (content analysis)
    2. Silence gap detection from SRT
    3. Transcription population
    """

    def __init__(self, silence_min_gap_ms: int = 500):
        self.silence_min_gap_ms = silence_min_gap_ms

    async def analyze(
        self,
        srt_path: Path,
        video_path: Path,
        output_dir: Path | None = None,
        source_id: str | None = None,
        storyline_path: Path | None = None,
        provider: str = "codex",
        extra_sources: list[Path] | None = None,
        extra_offsets: dict[str, int] | None = None,
    ) -> tuple[Project, Path]:
        """Analyze subtitles and return Project with content + silence decisions.

        Args:
            srt_path: Path to SRT subtitle file
            video_path: Path to source video file
            output_dir: Output directory
            source_id: Optional source file ID
            storyline_path: Optional path to storyline.json from Pass 1
            provider: AI provider ("codex" or "claude")
            extra_sources: Additional media files to sync and include.
            extra_offsets: Manual offset overrides ``{filename: ms}``.

        Returns:
            Tuple of (Project with edit_decisions, path to .avid.json)
        """
        script = _get_subtitle_cut_script()
        script_dir = script.parent

        srt_path = Path(srt_path).resolve()
        video_path = Path(video_path).resolve()

        if not srt_path.exists():
            raise FileNotFoundError(f"SRT file not found: {srt_path}")
        if not video_path.exists():
            raise FileNotFoundError(f"Video file not found: {video_path}")

        if output_dir is None:
            output_dir = srt_path.parent
        output_dir = Path(output_dir).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

        project_output = output_dir / f"{srt_path.stem}_subtitle_cut.avid.json"

        # Step 1: Run subtitle-cut skill
        print("  Step 1: Running subtitle-cut skill...")
        cmd = [
            sys.executable, str(script),
            str(srt_path),
            str(video_path),
            "--provider", provider,
            "--output", str(project_output),
        ]

        if source_id:
            cmd.extend(["--source-id", source_id])

        if storyline_path:
            storyline_path = Path(storyline_path).resolve()
            if storyline_path.exists():
                cmd.extend(["--context", str(storyline_path)])

        result = await asyncio.to_thread(
            subprocess.run,
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
            cwd=str(script_dir),
        )

        if result.returncode != 0:
            detail = result.stderr or result.stdout or "(no output)"
            raise RuntimeError(
                f"subtitle-cut failed (exit {result.returncode}):\n{detail[-2000:]}"
            )

        if not project_output.exists():
            raise RuntimeError(f"subtitle-cut did not produce output: {project_output}")

        project = Project.load(project_output)
        content_count = len(project.edit_decisions)
        print(f"  Content decisions: {content_count}")

        # Step 1b: Sync extra sources (if any)
        if extra_sources:
            from avid.services.audio_sync import AudioSyncService

            print("  Step 1b: Syncing extra sources...")
            sync_service = AudioSyncService()
            await sync_service.add_extra_sources(
                project, video_path, extra_sources, extra_offsets or {},
            )

        # Step 2: Parse SRT and find silence gaps
        print("  Step 2: Finding silence gaps from SRT...")
        srt_segments = _parse_srt(srt_path)

        # Get total video duration for trailing silence detection
        video_track = next(
            (t for t in project.tracks if t.track_type.value == "video"), None
        )
        total_duration_ms = None
        if video_track:
            source = project.get_source_file(video_track.source_file_id)
            if source and source.info and source.info.duration_ms:
                total_duration_ms = source.info.duration_ms

        silence_gaps = _find_silence_gaps(
            srt_segments, self.silence_min_gap_ms, total_duration_ms
        )
        print(f"  Silence gaps: {len(silence_gaps)}")

        # Step 3: Populate transcription
        if project.transcription is None and project.tracks:
            audio_track = next(
                (t for t in project.tracks if t.track_type.value == "audio"), None
            )
            if audio_track:
                project.transcription = Transcription(
                    source_track_id=audio_track.id,
                    language="ko",
                    segments=[
                        TranscriptSegment(
                            start_ms=seg["start_ms"],
                            end_ms=seg["end_ms"],
                            text=seg["text"],
                        )
                        for seg in srt_segments
                    ],
                )

        # Step 4: Add silence CUT decisions
        audio_track = next(
            (t for t in project.tracks if t.track_type.value == "audio"), None
        )

        for gap in silence_gaps:
            project.edit_decisions.append(EditDecision(
                range=TimeRange(start_ms=gap[0], end_ms=gap[1]),
                edit_type=EditType.CUT,
                reason=EditReason.SILENCE,
                confidence=0.95,
                note="SRT gap (no speech)",
                active_video_track_id=video_track.id if video_track else None,
                active_audio_track_ids=[audio_track.id] if audio_track else [],
            ))

        # Sort all decisions by start time
        project.edit_decisions.sort(key=lambda d: d.range.start_ms)

        # Save updated project
        project.save(project_output)
        print(f"  Total: {len(project.edit_decisions)} decisions ({content_count} content + {len(silence_gaps)} silence)")

        return project, project_output


def _parse_srt(srt_path: Path) -> list[dict]:
    """Parse SRT file into segment dicts."""
    content = srt_path.read_text(encoding="utf-8")
    segments = []
    for block in re.split(r"\n\s*\n", content.strip()):
        lines = block.strip().split("\n")
        if len(lines) < 3:
            continue
        time_match = re.match(
            r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[,.](\d{3})",
            lines[1].strip(),
        )
        if not time_match:
            continue
        h1, m1, s1, ms1, h2, m2, s2, ms2 = map(int, time_match.groups())
        start_ms = h1 * 3600000 + m1 * 60000 + s1 * 1000 + ms1
        end_ms = h2 * 3600000 + m2 * 60000 + s2 * 1000 + ms2
        text = " ".join(l.strip() for l in lines[2:] if l.strip())
        segments.append({"start_ms": start_ms, "end_ms": end_ms, "text": text})
    return segments


def _find_silence_gaps(
    segments: list[dict],
    min_gap_ms: int = 500,
    total_duration_ms: int | None = None,
) -> list[tuple[int, int]]:
    """Find silence regions from gaps between SRT segments."""
    if not segments:
        return []

    sorted_segs = sorted(segments, key=lambda s: s["start_ms"])
    gaps = []

    # Silence at beginning
    if sorted_segs[0]["start_ms"] >= min_gap_ms:
        gaps.append((0, sorted_segs[0]["start_ms"]))

    # Gaps between segments
    for i in range(len(sorted_segs) - 1):
        current_end = sorted_segs[i]["end_ms"]
        next_start = sorted_segs[i + 1]["start_ms"]
        gap_ms = next_start - current_end
        if gap_ms >= min_gap_ms:
            gaps.append((current_end, next_start))

    # Silence at end (after last subtitle to end of video)
    if total_duration_ms is not None:
        last_end = sorted_segs[-1]["end_ms"]
        trailing_gap = total_duration_ms - last_end
        if trailing_gap >= min_gap_ms:
            gaps.append((last_end, total_duration_ms))

    return gaps
