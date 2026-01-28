"""Silence detection service using skillthon detect-silence skill."""

import asyncio
import json
import subprocess
import uuid
from pathlib import Path

from avid.models.media import MediaFile, MediaInfo
from avid.models.project import Project
from avid.models.timeline import EditDecision, EditType, EditReason, TimeRange
from avid.models.track import Track, TrackType


def _find_project_root() -> Path:
    """Find the project root (where skillthon/ lives)."""
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "skillthon").is_dir():
            return parent
    raise RuntimeError("Cannot find project root (skillthon/ directory not found)")


def _get_silence_script() -> Path:
    """Get path to detect-silence script."""
    root = _find_project_root()
    script = root / "skillthon" / "detect-silence" / "skills" / "detect-silence" / "scripts" / "detect_silence.py"
    if not script.exists():
        raise RuntimeError(f"detect-silence script not found: {script}")
    return script


class SilenceDetectionService:
    """Detect silence regions using the detect-silence skillthon skill."""

    async def detect(
        self,
        video_path: Path,
        srt_path: Path | None = None,
        output_dir: Path | None = None,
        mode: str = "or",
        tempo: str = "tight",
        min_duration_ms: int = 500,
        threshold_db: float | None = None,
        padding_ms: int = 100,
    ) -> tuple[Project, Path]:
        """Detect silence and return Project with edit decisions.

        Args:
            video_path: Path to video/audio file
            srt_path: Optional SRT file for gap analysis
            output_dir: Output directory
            mode: Detection mode (ffmpeg, srt, and, or, diff)
            tempo: Tempo preset (relaxed, normal, tight)
            min_duration_ms: Minimum silence duration in ms
            threshold_db: Silence threshold in dB (None = auto)
            padding_ms: Padding before/after speech in ms

        Returns:
            Tuple of (Project with edit_decisions, path to .avid.json)

        Raises:
            RuntimeError: If script fails
        """
        script = _get_silence_script()
        video_path = Path(video_path).resolve()

        if not video_path.exists():
            raise FileNotFoundError(f"Video file not found: {video_path}")

        if output_dir is None:
            output_dir = video_path.parent
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Raw JSON output from detect-silence script
        raw_json_output = output_dir / f"{video_path.stem}_silence_raw.json"
        # Final .avid.json project output
        project_output = output_dir / f"{video_path.stem}_silence.avid.json"

        # Build command
        cmd = [
            "python", str(script),
            str(video_path),
            "--mode", mode,
            "--min-duration", str(min_duration_ms),
            "--padding", str(padding_ms),
            "--output", str(raw_json_output),
        ]

        if srt_path:
            srt_path = Path(srt_path).resolve()
            if not srt_path.exists():
                raise FileNotFoundError(f"SRT file not found: {srt_path}")
            cmd.extend(["--srt", str(srt_path)])

        if tempo:
            cmd.extend(["--tempo", tempo])

        if threshold_db is not None:
            cmd.extend(["--threshold", str(threshold_db)])

        # Run skill
        result = await asyncio.to_thread(
            subprocess.run,
            cmd,
            capture_output=True,
            text=True,
            timeout=300,  # 5 min timeout
        )

        if result.returncode != 0:
            raise RuntimeError(
                f"detect-silence failed (exit {result.returncode}):\n{result.stderr}"
            )

        # Load raw JSON output
        if not raw_json_output.exists():
            raise RuntimeError(f"detect-silence did not produce output: {raw_json_output}")

        with open(raw_json_output, encoding="utf-8") as f:
            raw_data = json.load(f)

        # Convert raw JSON to Project .avid.json
        project = self._convert_to_project(raw_data, video_path)
        project.save(project_output)

        return project, project_output

    @staticmethod
    def _convert_to_project(raw_data: dict, video_path: Path) -> Project:
        """Convert raw detect-silence JSON output to a Project.

        Args:
            raw_data: Raw JSON dict from detect-silence script
            video_path: Path to the source video file

        Returns:
            Project with edit decisions
        """
        # Create MediaFile
        file_id = str(uuid.uuid5(uuid.NAMESPACE_URL, str(video_path)))
        media_info = MediaInfo(duration_ms=raw_data["duration_ms"])
        media_file = MediaFile(
            id=file_id,
            path=video_path,
            original_name=video_path.name,
            info=media_info,
        )

        # Create tracks
        video_track = Track(
            id=f"{file_id}_video",
            source_file_id=file_id,
            track_type=TrackType.VIDEO,
            offset_ms=0,
        )
        audio_track = Track(
            id=f"{file_id}_audio",
            source_file_id=file_id,
            track_type=TrackType.AUDIO,
            offset_ms=0,
        )

        # Convert silence_regions to EditDecisions
        edit_decisions: list[EditDecision] = []
        for region in raw_data.get("silence_regions", []):
            decision = EditDecision(
                range=TimeRange(
                    start_ms=region["start_ms"],
                    end_ms=region["end_ms"],
                ),
                edit_type=EditType.CUT,
                reason=EditReason.SILENCE,
                confidence=region.get("confidence", 1.0),
                active_video_track_id=video_track.id,
                active_audio_track_ids=[audio_track.id],
            )
            edit_decisions.append(decision)

        # Build Project
        project = Project(
            name=f"Silence Detection - {video_path.stem}",
            source_files=[media_file],
            tracks=[video_track, audio_track],
            edit_decisions=edit_decisions,
        )

        return project
