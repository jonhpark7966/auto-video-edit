#!/usr/bin/env python3
"""E2E test: Podcast editing pipeline via AVID API.

Pipeline:
  1. yt-dlp: Download YouTube video (1:24:00 ~ end, 360p)
  2. POST /api/v1/jobs/transcribe  (alignment + LLM refinement)
  3. POST /api/v1/jobs/transcript-overview
  4. POST /api/v1/jobs/podcast-cut  (review mode)
  5. POST /api/v1/jobs/podcast-cut  (final mode)
  6. Summary output + file collection

Prerequisites:
  - AVID API server running at localhost:8000
  - Chalna API server running at localhost:7861
  - yt-dlp installed
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

AVID_BASE = "http://localhost:8000/api/v1/jobs"
CHALNA_HEALTH = "http://localhost:7861/health"

YOUTUBE_URL = "https://youtube.com/live/tLkdtEyNAW0"
START_TIME = "1:24:00"  # download from this timestamp to end

POLL_INTERVAL = 5  # seconds between status polls
POLL_TIMEOUT = 1800  # 30 min max per job


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def elapsed_str(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m}m {s}s"


def check_prerequisites() -> None:
    """Verify that required services and tools are available."""
    # yt-dlp
    if not shutil.which("yt-dlp"):
        sys.exit("ERROR: yt-dlp not found. Install with: pip install yt-dlp")

    # AVID API
    try:
        r = httpx.get(f"{AVID_BASE}", timeout=5)
        r.raise_for_status()
    except Exception as e:
        sys.exit(f"ERROR: AVID API not reachable at {AVID_BASE}: {e}")

    # Chalna
    try:
        r = httpx.get(CHALNA_HEALTH, timeout=5)
        r.raise_for_status()
    except Exception as e:
        sys.exit(f"ERROR: Chalna API not reachable at {CHALNA_HEALTH}: {e}")

    log("All prerequisites OK")


def download_video(output_path: Path) -> None:
    """Download YouTube video segment with yt-dlp."""
    if output_path.exists():
        log(f"Video already exists: {output_path}")
        return

    log(f"Downloading video from {YOUTUBE_URL} (start={START_TIME})...")
    cmd = [
        "yt-dlp",
        "--js-runtimes", "node",
        "--remote-components", "ejs:github",
        "--download-sections", f"*{START_TIME}-inf",
        "-f", "18",
        "-o", str(output_path),
        YOUTUBE_URL,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        log(f"yt-dlp stderr: {result.stderr}")
        sys.exit(f"ERROR: yt-dlp failed (exit {result.returncode})")

    if not output_path.exists():
        sys.exit(f"ERROR: Expected output file not found: {output_path}")

    log(f"Downloaded: {output_path} ({output_path.stat().st_size / 1024 / 1024:.1f} MB)")


def create_job(endpoint: str, payload: dict) -> str:
    """POST to create a job, return job_id."""
    url = f"{AVID_BASE}/{endpoint}"
    log(f"POST {url}")
    r = httpx.post(url, json=payload, timeout=30)
    if r.status_code != 202:
        sys.exit(f"ERROR: {url} returned {r.status_code}: {r.text}")
    data = r.json()
    job_id = data["job_id"]
    log(f"  Job created: {job_id}")
    return job_id


def poll_job(job_id: str) -> dict:
    """Poll job until completed or failed. Returns final status response."""
    url = f"{AVID_BASE}/{job_id}"
    start = time.time()
    last_msg = ""

    while True:
        r = httpx.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()

        status = data["status"]
        msg = data.get("message", "")
        progress = data.get("progress", 0)

        if msg != last_msg:
            log(f"  [{progress:3d}%] {msg}")
            last_msg = msg

        if status == "completed":
            return data
        if status == "failed":
            error = data.get("error", "unknown")
            sys.exit(f"ERROR: Job {job_id} failed: {error}")

        if time.time() - start > POLL_TIMEOUT:
            sys.exit(f"ERROR: Job {job_id} timed out after {POLL_TIMEOUT}s")

        time.sleep(POLL_INTERVAL)


def save_job_output(data: dict, out_dir: Path) -> dict[str, str]:
    """Save job status JSON and copy output files. Returns output_files dict."""
    out_dir.mkdir(parents=True, exist_ok=True)

    # Save job snapshot
    with open(out_dir / "job.json", "w") as f:
        json.dump(data, f, indent=2, default=str)

    output_files = data.get("result", {}).get("output_files", {})

    # Copy each output file into the output directory
    copied = {}
    for name, src_path_str in output_files.items():
        src = Path(src_path_str)
        if src.exists():
            dst = out_dir / src.name
            shutil.copy2(src, dst)
            copied[name] = str(dst)
            log(f"  Saved: {dst.name}")
        else:
            log(f"  WARNING: output file missing: {src_path_str}")
            copied[name] = src_path_str

    return copied


# ---------------------------------------------------------------------------
# Pipeline steps
# ---------------------------------------------------------------------------

def step_transcribe(video_path: Path, run_dir: Path) -> str:
    """Step 1: Transcribe video → SRT. Returns SRT path."""
    log("=" * 60)
    log("STEP 1: Transcribe")
    log("=" * 60)

    t0 = time.time()
    job_id = create_job("transcribe", {
        "input_path": str(video_path),
        "language": "ko",
        "use_alignment": True,
        "use_llm_refinement": True,
    })
    data = poll_job(job_id)
    dt = time.time() - t0

    out_dir = run_dir / "transcribe"
    copied = save_job_output(data, out_dir)

    srt_path = copied.get("srt", "")
    log(f"  Transcription done in {elapsed_str(dt)}")

    summary = data.get("result", {}).get("summary", {})
    log(f"  Segments: {summary.get('segments', '?')}, Language: {summary.get('language', '?')}")

    return srt_path, dt


def step_overview(srt_path: str, run_dir: Path) -> str:
    """Step 2: Transcript overview → storyline.json. Returns storyline path."""
    log("=" * 60)
    log("STEP 2: Transcript Overview")
    log("=" * 60)

    t0 = time.time()
    job_id = create_job("transcript-overview", {
        "srt_path": srt_path,
        "content_type": "auto",
    })
    data = poll_job(job_id)
    dt = time.time() - t0

    out_dir = run_dir / "overview"
    copied = save_job_output(data, out_dir)

    storyline_path = copied.get("storyline", "")
    log(f"  Overview done in {elapsed_str(dt)}")

    summary = data.get("result", {}).get("summary", {})
    log(f"  Chapters: {summary.get('chapters', '?')}")
    log(f"  Arc: {summary.get('narrative_arc', '?')}")

    return storyline_path, dt


def step_podcast_cut(
    audio_path: Path,
    srt_path: str,
    storyline_path: str,
    export_mode: str,
    run_dir: Path,
) -> tuple[dict, float]:
    """Step 3/4: Podcast cut. Returns (output_files, elapsed)."""
    label = f"Podcast Cut ({export_mode})"
    log("=" * 60)
    log(f"STEP: {label}")
    log("=" * 60)

    t0 = time.time()
    job_id = create_job("podcast-cut", {
        "audio_path": str(audio_path),
        "srt_path": srt_path,
        "context_path": storyline_path,
        "export_mode": export_mode,
    })
    data = poll_job(job_id)
    dt = time.time() - t0

    dir_name = f"podcast_cut_{export_mode}"
    out_dir = run_dir / dir_name
    copied = save_job_output(data, out_dir)

    log(f"  {label} done in {elapsed_str(dt)}")

    summary = data.get("result", {}).get("summary", {})
    log(f"  Total decisions: {summary.get('total_decisions', '?')}")
    by_reason = summary.get("by_reason", {})
    for reason, info in by_reason.items():
        log(f"    {reason}: {info}")

    return copied, dt


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    log("AVID E2E Test — Podcast Pipeline")
    log("=" * 60)

    check_prerequisites()

    # Create run directory
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = Path(__file__).parent / "data" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    log(f"Run directory: {run_dir}")

    timings: dict[str, float] = {}

    # Download video
    video_path = run_dir / "source.mp4"
    t0 = time.time()
    download_video(video_path)
    timings["download"] = time.time() - t0

    # Step 1: Transcribe
    srt_path, dt = step_transcribe(video_path, run_dir)
    timings["transcribe"] = dt

    # The transcribe job writes the SRT next to the video.
    # We need the original path (on the server filesystem), not the copied one.
    # Read it from the job.json to get the server-side path.
    transcribe_job = json.loads((run_dir / "transcribe" / "job.json").read_text())
    server_srt_path = transcribe_job.get("result", {}).get("output_files", {}).get("srt", srt_path)

    # Step 2: Transcript Overview
    storyline_path, dt = step_overview(server_srt_path, run_dir)
    timings["overview"] = dt

    # Read server-side storyline path from job.json
    overview_job = json.loads((run_dir / "overview" / "job.json").read_text())
    server_storyline_path = overview_job.get("result", {}).get("output_files", {}).get(
        "storyline", storyline_path
    )

    # Step 3: Podcast Cut (review)
    _, dt = step_podcast_cut(video_path, server_srt_path, server_storyline_path, "review", run_dir)
    timings["podcast_cut_review"] = dt

    # Step 4: Podcast Cut (final)
    _, dt = step_podcast_cut(video_path, server_srt_path, server_storyline_path, "final", run_dir)
    timings["podcast_cut_final"] = dt

    # Summary
    total = sum(timings.values())
    timings["total"] = total

    summary = {
        "run_id": run_id,
        "youtube_url": YOUTUBE_URL,
        "start_time": START_TIME,
        "timings": {k: round(v, 1) for k, v in timings.items()},
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }

    summary_path = run_dir / "summary.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)

    log("")
    log("=" * 60)
    log("PIPELINE COMPLETE")
    log("=" * 60)
    log(f"Total time: {elapsed_str(total)}")
    for step, dt in timings.items():
        if step != "total":
            log(f"  {step:25s} {elapsed_str(dt)}")
    log(f"Results: {run_dir}")
    log(f"Summary: {summary_path}")


if __name__ == "__main__":
    main()
