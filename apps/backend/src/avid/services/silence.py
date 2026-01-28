"""Silence detection service using skillthon detect-silence skill."""

import asyncio
import json
import subprocess
from pathlib import Path

from avid.models.project import Project


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
        tight: bool = True,
        min_silence_ms: int = 500,
        noise_db: float = -40.0,
    ) -> tuple[Project, Path]:
        """Detect silence and return Project with edit decisions.

        Args:
            video_path: Path to video/audio file
            srt_path: Optional SRT file for gap analysis
            output_dir: Output directory
            mode: Combine mode (or, and, ffmpeg_only, srt_only)
            tight: Use tight mode (minimize cut regions)
            min_silence_ms: Minimum silence duration
            noise_db: Noise threshold in dB

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

        project_output = output_dir / f"{video_path.stem}_silence.avid.json"

        # Build command
        cmd = [
            "python", str(script),
            str(video_path),
            "--mode", mode,
            "--min-silence", str(min_silence_ms),
            "--noise", str(noise_db),
            "--project",
            "--project-output", str(project_output),
        ]

        if srt_path:
            srt_path = Path(srt_path).resolve()
            if not srt_path.exists():
                raise FileNotFoundError(f"SRT file not found: {srt_path}")
            cmd.extend(["--srt", str(srt_path)])

        if tight:
            cmd.append("--tight")

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

        # Load project
        if not project_output.exists():
            raise RuntimeError(f"detect-silence did not produce output: {project_output}")

        project = Project.load(project_output)
        return project, project_output
