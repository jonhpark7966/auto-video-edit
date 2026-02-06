"""Transcript overview analysis service (Pass 1).

Calls the transcript-overview skill via subprocess to produce a storyline JSON
that describes the narrative arc, chapters, key moments, and dependencies.
"""

import asyncio
import json
import subprocess
import sys
from pathlib import Path


def _find_project_root() -> Path:
    """Find the project root (where skills/ lives)."""
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "skills").is_dir():
            return parent
    raise RuntimeError("Cannot find project root (skills/ directory not found)")


def _get_transcript_overview_script() -> Path:
    """Get path to transcript-overview main.py script."""
    root = _find_project_root()
    script = root / "skills" / "transcript-overview" / "main.py"
    if not script.exists():
        raise RuntimeError(f"transcript-overview script not found: {script}")
    return script


class TranscriptOverviewService:
    """Analyze transcript structure using the transcript-overview skill (Pass 1).

    Usage:
        service = TranscriptOverviewService()
        storyline_path = await service.analyze(srt_path)
        storyline_data = service.load_storyline(storyline_path)
    """

    async def analyze(
        self,
        srt_path: Path,
        output_path: Path | None = None,
        content_type: str = "auto",
        provider: str = "codex",
    ) -> Path:
        """Analyze SRT and produce storyline JSON.

        Args:
            srt_path: Path to SRT subtitle file
            output_path: Output path for storyline JSON (default: <srt_stem>.storyline.json)
            content_type: Content type hint ("lecture", "podcast", "auto")

        Returns:
            Path to the generated storyline JSON file

        Raises:
            RuntimeError: If the skill fails
            FileNotFoundError: If SRT file not found
        """
        script = _get_transcript_overview_script()
        script_dir = script.parent

        srt_path = Path(srt_path).resolve()
        if not srt_path.exists():
            raise FileNotFoundError(f"SRT file not found: {srt_path}")

        if output_path is None:
            output_path = srt_path.with_suffix("").with_suffix(".storyline.json")
        output_path = Path(output_path).resolve()

        # Build command
        cmd = [
            sys.executable, str(script),
            str(srt_path),
            "--provider", provider,
            "--output", str(output_path),
            "--content-type", content_type,
        ]

        # Run skill
        result = await asyncio.to_thread(
            subprocess.run,
            cmd,
            capture_output=True,
            text=True,
            timeout=600,  # 10 min timeout (large transcripts)
            cwd=str(script_dir),
        )

        if result.returncode != 0:
            detail = result.stderr or result.stdout or "(no output)"
            raise RuntimeError(
                f"transcript-overview failed (exit {result.returncode}):\n{detail[-2000:]}"
            )

        if not output_path.exists():
            raise RuntimeError(f"transcript-overview did not produce output: {output_path}")

        return output_path

    def load_storyline(self, path: Path) -> dict:
        """Load storyline JSON from file.

        Args:
            path: Path to storyline JSON

        Returns:
            Storyline dict
        """
        with open(path, encoding="utf-8") as f:
            return json.load(f)
