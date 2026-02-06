#!/usr/bin/env python3
"""Two-Pass full pipeline test.

Tests the complete workflow:
  1. Chalna API → SRT transcription
  2. transcript-overview skill → storyline.json (Pass 1)
  3. subtitle-cut / podcast-cut skill → avid.json (Pass 2)
  4. FCPXMLExporter → FCPXML (disabled + cut) + adjusted SRT

Usage:
    python scripts/test_two_pass.py subtitle samples/C1718_compressed.mp4 -o output/c1718_test/
    python scripts/test_two_pass.py podcast samples/sample_10min.m4a -o output/podcast_test/
    python scripts/test_two_pass.py subtitle samples/C1718_compressed.mp4 --srt samples/C1718_original.srt -o output/c1718_test/
"""

import argparse
import asyncio
import subprocess
import sys
import time
from pathlib import Path

# Add backend src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "apps" / "backend" / "src"))

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _find_skill_script(skill_name: str) -> Path:
    """Find skill main.py script."""
    script = PROJECT_ROOT / "skills" / skill_name / "main.py"
    if not script.exists():
        raise FileNotFoundError(f"Skill script not found: {script}")
    return script


async def step_transcribe(audio_path: Path, output_dir: Path, language: str = "ko") -> Path:
    """Step 1: Transcribe audio via Chalna API."""
    from avid.services.transcription import ChalnaTranscriptionService

    output_srt = output_dir / f"{audio_path.stem}.srt"

    service = ChalnaTranscriptionService()
    print(f"  Chalna API: {service.base_url}")

    if not await service.health_check():
        raise RuntimeError(f"Chalna API not available at {service.base_url}")

    start = time.time()

    def progress_cb(progress: float, status: str) -> None:
        bar_width = 30
        filled = int(bar_width * progress)
        bar = "=" * filled + "-" * (bar_width - filled)
        print(f"\r  [{bar}] {progress*100:.0f}% {status}", end="", flush=True)

    result = await service.transcribe_async(
        audio_path=audio_path,
        language=language,
        progress_callback=progress_cb,
    )
    print()

    # Save as SRT
    lines = []
    for i, seg in enumerate(result.segments, 1):
        start_ms = int(seg.start * 1000)
        end_ms = int(seg.end * 1000)
        h1, m1, s1, ms1 = start_ms // 3600000, (start_ms % 3600000) // 60000, (start_ms % 60000) // 1000, start_ms % 1000
        h2, m2, s2, ms2 = end_ms // 3600000, (end_ms % 3600000) // 60000, (end_ms % 60000) // 1000, end_ms % 1000
        lines.append(f"{i}\n{h1:02d}:{m1:02d}:{s1:02d},{ms1:03d} --> {h2:02d}:{m2:02d}:{s2:02d},{ms2:03d}\n{seg.text}\n")
    output_srt.write_text("\n".join(lines), encoding="utf-8")

    elapsed = time.time() - start
    print(f"  Segments: {len(result.segments)}")
    print(f"  Time: {elapsed:.1f}s")
    print(f"  Output: {output_srt}")
    return output_srt


def step_transcript_overview(srt_path: Path, output_dir: Path, content_type: str = "auto", provider: str = "codex") -> Path:
    """Step 2: Run transcript-overview skill (Pass 1) → storyline.json."""
    script = _find_skill_script("transcript-overview")
    output_path = output_dir / f"{srt_path.stem}.storyline.json"

    cmd = [
        sys.executable, str(script),
        str(srt_path),
        "--provider", provider,
        "--output", str(output_path),
        "--content-type", content_type,
    ]

    start = time.time()
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600, cwd=str(script.parent))

    if result.returncode != 0:
        print(f"  STDERR: {result.stderr}", file=sys.stderr)
        raise RuntimeError(f"transcript-overview failed (exit {result.returncode})")

    # Print stdout (contains the report)
    if result.stdout.strip():
        for line in result.stdout.strip().split("\n"):
            print(f"  {line}")

    elapsed = time.time() - start
    print(f"  Time: {elapsed:.1f}s")
    print(f"  Output: {output_path}")
    return output_path


def step_subtitle_cut(srt_path: Path, video_path: Path, storyline_path: Path, output_dir: Path, provider: str = "codex") -> Path:
    """Step 3a: Run subtitle-cut skill (Pass 2) → avid.json."""
    script = _find_skill_script("subtitle-cut")
    output_path = output_dir / f"{srt_path.stem}.subtitle_cut.avid.json"

    cmd = [
        sys.executable, str(script),
        str(srt_path),
        str(video_path),
        "--provider", provider,
        "--output", str(output_path),
        "--context", str(storyline_path),
    ]

    start = time.time()
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300, cwd=str(script.parent))

    if result.returncode != 0:
        print(f"  STDERR: {result.stderr}", file=sys.stderr)
        raise RuntimeError(f"subtitle-cut failed (exit {result.returncode})")

    if result.stdout.strip():
        for line in result.stdout.strip().split("\n"):
            print(f"  {line}")

    elapsed = time.time() - start
    print(f"  Time: {elapsed:.1f}s")
    print(f"  Output: {output_path}")
    return output_path


def step_podcast_cut(srt_path: Path, video_path: Path, storyline_path: Path, output_dir: Path, provider: str = "codex") -> Path:
    """Step 3b: Run podcast-cut skill (Pass 2) → avid.json."""
    script = _find_skill_script("podcast-cut")
    output_path = output_dir / f"{srt_path.stem}.podcast_cut.avid.json"

    cmd = [
        sys.executable, str(script),
        str(srt_path),
        str(video_path),
        "--provider", provider,
        "--output", str(output_path),
        "--context", str(storyline_path),
    ]

    start = time.time()
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300, cwd=str(script.parent))

    if result.returncode != 0:
        print(f"  STDERR: {result.stderr}", file=sys.stderr)
        raise RuntimeError(f"podcast-cut failed (exit {result.returncode})")

    if result.stdout.strip():
        for line in result.stdout.strip().split("\n"):
            print(f"  {line}")

    elapsed = time.time() - start
    print(f"  Time: {elapsed:.1f}s")
    print(f"  Output: {output_path}")
    return output_path


async def step_export(avid_json_path: Path, output_dir: Path, stem: str) -> dict[str, Path]:
    """Step 4: Export FCPXML (disabled + cut) and adjusted SRT."""
    from avid.export.fcpxml import FCPXMLExporter
    from avid.export.report import save_report
    from avid.models.project import Project

    project = Project.load(avid_json_path)
    exporter = FCPXMLExporter()
    outputs: dict[str, Path] = {}

    # Disabled mode (for review in FCP)
    disabled_path = output_dir / f"{stem}_disabled.fcpxml"
    fcpxml_disabled, srt_disabled = await exporter.export(
        project,
        disabled_path,
        show_disabled_cuts=True,
        silence_mode="cut",
        content_mode="disabled",
    )
    outputs["fcpxml_disabled"] = fcpxml_disabled
    if srt_disabled:
        outputs["srt_disabled"] = srt_disabled

    # Cut mode (final)
    cut_path = output_dir / f"{stem}_cut.fcpxml"
    fcpxml_cut, srt_cut = await exporter.export(
        project,
        cut_path,
        show_disabled_cuts=False,
        silence_mode="cut",
        content_mode="cut",
    )
    outputs["fcpxml_cut"] = fcpxml_cut
    if srt_cut:
        outputs["srt_cut"] = srt_cut

    # Report
    report_path = output_dir / f"{stem}.report.md"
    save_report(project, report_path, format="markdown")
    outputs["report"] = report_path

    return outputs


async def run_pipeline(mode: str, input_path: Path, output_dir: Path, srt_path: Path | None, provider: str):
    """Run the full two-pass pipeline."""
    total_start = time.time()

    print("=" * 60)
    print(f"TWO-PASS PIPELINE TEST ({mode.upper()})")
    print("=" * 60)
    print(f"  Input: {input_path}")
    print(f"  Output: {output_dir}")
    print(f"  Provider: {provider}")
    if srt_path:
        print(f"  SRT: {srt_path} (skip transcription)")
    print()

    output_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: Transcribe
    if srt_path and srt_path.exists():
        print(f"[1/4] Transcription: SKIPPED (using {srt_path.name})")
    else:
        print("[1/4] Transcription (Chalna API)...")
        srt_path = await step_transcribe(input_path, output_dir)
    print()

    # Step 2: Transcript Overview (Pass 1)
    content_type = "lecture" if mode == "subtitle" else "podcast"
    print(f"[2/4] Transcript Overview (Pass 1, {content_type})...")
    storyline_path = step_transcript_overview(srt_path, output_dir, content_type=content_type, provider=provider)
    print()

    # Step 3: Skill Analysis (Pass 2)
    if mode == "subtitle":
        print("[3/4] Subtitle Cut (Pass 2)...")
        avid_json_path = step_subtitle_cut(srt_path, input_path, storyline_path, output_dir, provider=provider)
    else:
        print("[3/4] Podcast Cut (Pass 2)...")
        avid_json_path = step_podcast_cut(srt_path, input_path, storyline_path, output_dir, provider=provider)
    print()

    # Step 4: Export
    stem = input_path.stem
    print("[4/4] Exporting FCPXML + SRT...")
    outputs = await step_export(avid_json_path, output_dir, stem)
    print()

    # Summary
    total_elapsed = time.time() - total_start
    print("=" * 60)
    print("RESULTS")
    print("=" * 60)
    print(f"  Total time: {total_elapsed:.1f}s")
    print(f"  SRT: {srt_path}")
    print(f"  Storyline: {storyline_path}")
    print(f"  AVID JSON: {avid_json_path}")
    for name, path in outputs.items():
        print(f"  {name}: {path}")
    print()
    print("Open the FCPXML files in Final Cut Pro to review.")


def main():
    parser = argparse.ArgumentParser(
        description="Two-Pass full pipeline test (Chalna → Overview → Cut → FCPXML)"
    )
    parser.add_argument(
        "mode",
        choices=["subtitle", "podcast"],
        help="Pipeline mode: subtitle (lectures) or podcast",
    )
    parser.add_argument("input", help="Input video/audio file")
    parser.add_argument("-o", "--output-dir", required=True, help="Output directory")
    parser.add_argument("--srt", help="Existing SRT file (skip transcription)")
    parser.add_argument(
        "--provider",
        choices=["claude", "codex"],
        default="codex",
        help="AI provider (default: codex)",
    )

    args = parser.parse_args()

    input_path = Path(args.input).resolve()
    if not input_path.exists():
        print(f"Error: Input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    output_dir = Path(args.output_dir).resolve()
    srt_path = Path(args.srt).resolve() if args.srt else None

    if srt_path and not srt_path.exists():
        print(f"Error: SRT file not found: {srt_path}", file=sys.stderr)
        sys.exit(1)

    asyncio.run(run_pipeline(args.mode, input_path, output_dir, srt_path, args.provider))


if __name__ == "__main__":
    main()
