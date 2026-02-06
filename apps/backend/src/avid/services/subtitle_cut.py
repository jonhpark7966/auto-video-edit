"""Subtitle cut analysis service using skillthon subtitle-cut skill."""

import asyncio
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


def _get_subtitle_cut_script() -> Path:
    """Get path to subtitle-cut main.py script."""
    root = _find_project_root()
    script = root / "skillthon" / "subtitle-cut-detector" / "skills" / "subtitle-cut" / "main.py"
    if not script.exists():
        raise RuntimeError(f"subtitle-cut script not found: {script}")
    return script


class SubtitleCutService:
    """Analyze subtitles for cut decisions using Claude via subtitle-cut skill."""

    async def analyze(
        self,
        srt_path: Path,
        video_path: Path,
        output_dir: Path | None = None,
        source_id: str | None = None,
        storyline_path: Path | None = None,
    ) -> tuple[Project, Path]:
        """Analyze subtitles and return Project with edit decisions.

        Args:
            srt_path: Path to SRT subtitle file
            video_path: Path to source video file
            output_dir: Output directory
            source_id: Optional source file ID (for project consistency)
            storyline_path: Optional path to storyline.json from Pass 1

        Returns:
            Tuple of (Project with edit_decisions, path to .avid.json)

        Raises:
            RuntimeError: If Claude CLI is not available or analysis fails
        """
        script = _get_subtitle_cut_script()
        # The script imports from its own directory, so we need to set cwd
        script_dir = script.parent

        srt_path = Path(srt_path).resolve()
        video_path = Path(video_path).resolve()

        if not srt_path.exists():
            raise FileNotFoundError(f"SRT file not found: {srt_path}")
        if not video_path.exists():
            raise FileNotFoundError(f"Video file not found: {video_path}")

        if output_dir is None:
            output_dir = srt_path.parent
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        project_output = output_dir / f"{srt_path.stem}_subtitle_cut.avid.json"

        # Build command
        cmd = [
            "python", str(script),
            str(srt_path),
            str(video_path),
            "--output", str(project_output),
        ]

        if source_id:
            cmd.extend(["--source-id", source_id])

        if storyline_path:
            storyline_path = Path(storyline_path).resolve()
            if storyline_path.exists():
                cmd.extend(["--context", str(storyline_path)])

        # Run skill (cwd = script directory for relative imports)
        result = await asyncio.to_thread(
            subprocess.run,
            cmd,
            capture_output=True,
            text=True,
            timeout=180,  # 3 min timeout (Claude can be slow)
            cwd=str(script_dir),
        )

        if result.returncode != 0:
            raise RuntimeError(
                f"subtitle-cut failed (exit {result.returncode}):\n{result.stderr}"
            )

        # Load project
        if not project_output.exists():
            raise RuntimeError(f"subtitle-cut did not produce output: {project_output}")

        project = Project.load(project_output)
        return project, project_output
