"""Podcast cut analysis service.

Full workflow for podcast editing:
1. Transcribe with Chalna (or use existing SRT)
2. Run podcast-cut skill via subprocess → avid.json (content decisions)
3. Find silence gaps from SRT
4. Merge content + silence → unified Project
5. Export FCPXML
"""

import asyncio
import json
import os
import re
import subprocess
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

from avid.models.media import MediaFile, MediaInfo
from avid.models.project import Project, Transcription, TranscriptSegment
from avid.models.timeline import EditDecision, EditReason, EditType, TimeRange
from avid.models.track import Track, TrackType


@dataclass
class SilenceRegion:
    """A detected silence region."""
    start_ms: int
    end_ms: int


@dataclass
class SubtitleSegment:
    """A single subtitle segment."""
    index: int
    start_ms: int
    end_ms: int
    text: str


def _find_project_root() -> Path:
    """Find the project root (where skills/ lives)."""
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "skills").is_dir():
            return parent
    raise RuntimeError("Cannot find project root (skills/ directory not found)")


def _get_podcast_cut_script() -> Path:
    """Get path to podcast-cut main.py script."""
    root = _find_project_root()
    script = root / "skills" / "podcast-cut" / "main.py"
    if not script.exists():
        raise RuntimeError(f"podcast-cut script not found: {script}")
    return script


class PodcastCutService:
    """Full podcast editing workflow service.

    This service orchestrates:
    1. Transcription via Chalna
    2. Podcast-cut skill subprocess (content analysis)
    3. Silence detection from SRT gaps
    4. Final project generation with FCPXML export

    Usage:
        service = PodcastCutService()
        project, outputs = await service.process(
            audio_path=Path("podcast.m4a"),
            output_dir=Path("./output"),
        )
    """

    def __init__(
        self,
        chalna_url: str | None = None,
        silence_min_gap_ms: int = 500,
    ):
        """Initialize the service.

        Args:
            chalna_url: Chalna API URL (default: CHALNA_API_URL env or http://localhost:7861)
            silence_min_gap_ms: Minimum gap between SRT segments to consider as silence (ms)
        """
        self.chalna_url = (
            chalna_url
            or os.environ.get("CHALNA_API_URL")
            or "http://localhost:7861"
        )
        self.silence_min_gap_ms = silence_min_gap_ms

    async def process(
        self,
        audio_path: Path,
        output_dir: Path | None = None,
        srt_path: Path | None = None,
        skip_transcription: bool = False,
        export_mode: str = "review",
        storyline_path: Path | None = None,
        provider: str = "codex",
        extra_sources: list[Path] | None = None,
        extra_offsets: dict[str, int] | None = None,
    ) -> tuple[Project, dict[str, Path]]:
        """Process a podcast audio file through the full workflow.

        Args:
            audio_path: Path to audio/video file
            output_dir: Output directory (default: same as audio)
            srt_path: Existing SRT file (skip transcription if provided)
            skip_transcription: Skip transcription step
            export_mode: "review" (disabled for review) or "final" (all cuts applied)
            storyline_path: Optional path to storyline.json from Pass 1.
            provider: AI provider to use ("codex" or "claude")
            extra_sources: Additional media files to sync and include.
            extra_offsets: Manual offset overrides ``{filename: ms}``.

        Returns:
            Tuple of (Project, dict of output paths)
        """
        audio_path = Path(audio_path).resolve()
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        if output_dir is None:
            output_dir = audio_path.parent
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        outputs: dict[str, Path] = {}

        # Step 1: Transcription
        if srt_path and srt_path.exists():
            print(f"Using existing SRT: {srt_path}")
        elif not skip_transcription:
            print("Step 1: Transcribing with chalna...")
            srt_path = await self._transcribe_with_chalna(audio_path, output_dir)
            outputs["srt_raw"] = srt_path
        else:
            raise ValueError("No SRT provided and transcription skipped")

        # Parse SRT
        segments = self._parse_srt(srt_path)
        print(f"  Parsed {len(segments)} segments")

        # Step 2: Run podcast-cut skill via subprocess
        print("Step 2: Running podcast-cut skill...")
        skill_output = output_dir / f"{audio_path.stem}_podcast_skill.avid.json"
        await self._run_podcast_cut_skill(
            srt_path=srt_path,
            audio_path=audio_path,
            output_path=skill_output,
            provider=provider,
            storyline_path=storyline_path,
        )

        # Step 3: Parse skill output → content decisions
        print("Step 3: Parsing skill output...")
        content_decisions = self._parse_skill_output(skill_output)
        print(f"  Generated {len(content_decisions)} content edit decisions")

        # Step 4: Find silence gaps from SRT
        print("Step 4: Finding silence gaps from SRT...")
        total_duration_ms = self._get_duration(audio_path)
        silence_regions = self._find_silence_gaps(segments, total_duration_ms)
        print(f"  Found {len(silence_regions)} silence gaps")

        # Step 5: Build project
        print("Step 5: Building project...")
        project = self._build_project(
            audio_path=audio_path,
            segments=segments,
            content_decisions=content_decisions,
            silence_regions=silence_regions,
        )

        # Step 5b: Sync extra sources (if any)
        if extra_sources:
            from avid.services.audio_sync import AudioSyncService

            print("Step 5b: Syncing extra sources...")
            sync_service = AudioSyncService()
            await sync_service.add_extra_sources(
                project, audio_path, extra_sources, extra_offsets or {},
            )

        # Save project
        project_path = output_dir / f"{audio_path.stem}.podcast.avid.json"
        project.save(project_path)
        outputs["project"] = project_path

        # Step 6: Export FCPXML and adjusted SRT
        print("Step 6: Exporting FCPXML and adjusted SRT...")
        from avid.export.fcpxml import FCPXMLExporter

        fcpxml_path = output_dir / f"{audio_path.stem}.final.fcpxml"
        exporter = FCPXMLExporter()

        # Determine export settings based on mode
        if export_mode == "final":
            show_disabled = False
            content_mode = "cut"
        else:
            show_disabled = True
            content_mode = "disabled"

        fcpxml_result, srt_result = await exporter.export(
            project,
            fcpxml_path,
            show_disabled_cuts=show_disabled,
            silence_mode="cut",
            content_mode=content_mode,
        )
        outputs["fcpxml"] = fcpxml_result
        if srt_result:
            outputs["srt_adjusted"] = srt_result
            print(f"  Adjusted SRT: {srt_result}")

        print(f"\nComplete: {len(project.edit_decisions)} total edit decisions")
        return project, outputs

    async def _run_podcast_cut_skill(
        self,
        srt_path: Path,
        audio_path: Path,
        output_path: Path,
        provider: str = "codex",
        storyline_path: Path | None = None,
    ) -> None:
        """Run podcast-cut skill as subprocess.

        Args:
            srt_path: Path to SRT file
            audio_path: Path to audio/video file
            output_path: Output path for avid.json
            provider: AI provider ("codex" or "claude")
            storyline_path: Optional storyline.json path

        Raises:
            RuntimeError: If skill fails
        """
        script = _get_podcast_cut_script()
        script_dir = script.parent

        srt_path = Path(srt_path).resolve()
        audio_path = Path(audio_path).resolve()
        output_path = Path(output_path).resolve()

        cmd = [
            sys.executable, str(script),
            str(srt_path),
            str(audio_path),
            "--provider", provider,
            "--output", str(output_path),
        ]

        if storyline_path:
            storyline_path = Path(storyline_path).resolve()
            if storyline_path.exists():
                cmd.extend(["--context", str(storyline_path)])

        result = await asyncio.to_thread(
            subprocess.run,
            cmd,
            capture_output=True,
            text=True,
            timeout=1800,  # 30 min timeout
            cwd=str(script_dir),
        )

        if result.returncode != 0:
            detail = result.stderr or result.stdout or "(no output)"
            raise RuntimeError(
                f"podcast-cut failed (exit {result.returncode}):\n{detail[-2000:]}"
            )

        if not output_path.exists():
            raise RuntimeError(f"podcast-cut did not produce output: {output_path}")

    def _parse_skill_output(self, avid_json_path: Path) -> list[EditDecision]:
        """Parse podcast-cut skill output avid.json into EditDecision list.

        Validates each entry defensively — malformed entries are skipped with
        a warning so the rest of the workflow can proceed.

        Args:
            avid_json_path: Path to the skill's output avid.json

        Returns:
            List of EditDecision objects
        """
        with open(avid_json_path, encoding="utf-8") as f:
            data = json.load(f)

        decisions = []
        skipped = 0
        for i, ed in enumerate(data.get("edit_decisions", [])):
            range_data = ed.get("range")
            if not isinstance(range_data, dict):
                print(f"  Warning: skipping edit_decisions[{i}] — missing 'range'")
                skipped += 1
                continue

            try:
                start_ms = int(range_data["start_ms"])
                end_ms = int(range_data["end_ms"])
            except (KeyError, TypeError, ValueError):
                print(f"  Warning: skipping edit_decisions[{i}] — invalid start_ms/end_ms")
                skipped += 1
                continue

            if end_ms <= start_ms:
                print(f"  Warning: skipping edit_decisions[{i}] — end_ms ({end_ms}) <= start_ms ({start_ms})")
                skipped += 1
                continue

            reason_str = ed.get("reason", "manual")
            try:
                reason = EditReason(reason_str)
            except ValueError:
                reason = EditReason.MANUAL

            edit_type_str = ed.get("edit_type", "mute")
            try:
                edit_type = EditType(edit_type_str)
            except ValueError:
                edit_type = EditType.MUTE

            confidence = ed.get("confidence", 0.9)
            try:
                confidence = max(0.0, min(1.0, float(confidence)))
            except (TypeError, ValueError):
                confidence = 0.9

            decisions.append(EditDecision(
                range=TimeRange(start_ms=start_ms, end_ms=end_ms),
                edit_type=edit_type,
                reason=reason,
                confidence=confidence,
                note=ed.get("note", ""),
            ))

        if skipped:
            print(f"  Warning: skipped {skipped} malformed entries from {avid_json_path}")

        return decisions

    _VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".flv", ".wmv"}

    def _extract_audio(self, video_path: Path, output_dir: Path) -> Path:
        """Extract audio from video file using ffmpeg."""
        wav_path = output_dir / f"{video_path.stem}_audio.wav"
        cmd = [
            "ffmpeg", "-y", "-i", str(video_path),
            "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
            str(wav_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg audio extraction failed:\n{result.stderr[-1000:]}")
        return wav_path

    async def _transcribe_with_chalna(
        self,
        audio_path: Path,
        output_dir: Path,
    ) -> Path:
        """Transcribe audio using Chalna API (async job + polling).

        Extracts audio first if input is a video file.

        Args:
            audio_path: Path to audio/video file
            output_dir: Output directory

        Returns:
            Path to generated SRT file
        """
        from avid.services.transcription import ChalnaTranscriptionService

        output_srt = output_dir / f"{audio_path.stem}.srt"

        # Extract audio if input is a video file
        upload_path = audio_path
        temp_audio = None
        if audio_path.suffix.lower() in self._VIDEO_EXTENSIONS:
            print("  Extracting audio from video...")
            upload_path = self._extract_audio(audio_path, output_dir)
            temp_audio = upload_path

        service = ChalnaTranscriptionService(base_url=self.chalna_url)

        # Check health first
        if not await service.health_check():
            raise RuntimeError(f"Chalna API not available at {self.chalna_url}")

        try:
            result = await service.transcribe_async(
                audio_path=upload_path,
                language="ko",
            )
        finally:
            if temp_audio and temp_audio.exists():
                temp_audio.unlink()

        # Convert to SRT
        lines = []
        for i, seg in enumerate(result.segments, 1):
            start_ms = int(seg.start * 1000)
            end_ms = int(seg.end * 1000)
            start_str = self._ms_to_srt_time(start_ms)
            end_str = self._ms_to_srt_time(end_ms)
            lines.append(f"{i}\n{start_str} --> {end_str}\n{seg.text}\n")

        with open(output_srt, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        return output_srt

    @staticmethod
    def _ms_to_srt_time(ms: int) -> str:
        """Format milliseconds as SRT timestamp."""
        hours = ms // 3600000
        ms %= 3600000
        minutes = ms // 60000
        ms %= 60000
        seconds = ms // 1000
        millis = ms % 1000
        return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"

    def _parse_srt(self, srt_path: Path) -> list[SubtitleSegment]:
        """Parse SRT file into segments."""
        with open(srt_path, encoding="utf-8") as f:
            content = f.read()

        segments = []
        blocks = re.split(r"\n\s*\n", content.strip())

        for block in blocks:
            if not block.strip():
                continue

            lines = block.strip().split("\n")
            if len(lines) < 3:
                continue

            try:
                index = int(lines[0].strip())
            except ValueError:
                continue

            time_match = re.match(
                r"(\d{2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,.]\d{3})",
                lines[1].strip(),
            )
            if not time_match:
                continue

            start_ms = self._parse_timestamp(time_match.group(1))
            end_ms = self._parse_timestamp(time_match.group(2))
            text = " ".join(line.strip() for line in lines[2:] if line.strip())

            segments.append(SubtitleSegment(
                index=index,
                start_ms=start_ms,
                end_ms=end_ms,
                text=text,
            ))

        return segments

    def _parse_timestamp(self, timestamp: str) -> int:
        """Parse SRT timestamp to milliseconds."""
        match = re.match(r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})", timestamp.strip())
        if not match:
            raise ValueError(f"Invalid timestamp: {timestamp}")

        h, m, s, ms = map(int, match.groups())
        return h * 3600000 + m * 60000 + s * 1000 + ms

    def _find_silence_gaps(
        self,
        segments: list[SubtitleSegment],
        total_duration_ms: int | None = None,
    ) -> list[SilenceRegion]:
        """Find silence regions from gaps between SRT segments.

        Args:
            segments: Parsed SRT segments (must be sorted by start time)
            total_duration_ms: Total duration of the media file for trailing silence

        Returns:
            List of SilenceRegion objects
        """
        if not segments:
            return []

        sorted_segments = sorted(segments, key=lambda s: s.start_ms)

        regions = []

        # Check for silence at the beginning
        if sorted_segments[0].start_ms >= self.silence_min_gap_ms:
            regions.append(SilenceRegion(
                start_ms=0,
                end_ms=sorted_segments[0].start_ms,
            ))

        # Find gaps between consecutive segments
        for i in range(len(sorted_segments) - 1):
            current_end = sorted_segments[i].end_ms
            next_start = sorted_segments[i + 1].start_ms

            gap_ms = next_start - current_end
            if gap_ms >= self.silence_min_gap_ms:
                regions.append(SilenceRegion(
                    start_ms=current_end,
                    end_ms=next_start,
                ))

        # Check for silence at the end (after last subtitle)
        if total_duration_ms is not None:
            last_end = sorted_segments[-1].end_ms
            trailing_gap = total_duration_ms - last_end
            if trailing_gap >= self.silence_min_gap_ms:
                regions.append(SilenceRegion(
                    start_ms=last_end,
                    end_ms=total_duration_ms,
                ))

        return regions

    def _build_project(
        self,
        audio_path: Path,
        segments: list[SubtitleSegment],
        content_decisions: list[EditDecision],
        silence_regions: list[SilenceRegion],
    ) -> Project:
        """Build final Project with all edit decisions."""
        file_id = str(uuid.uuid5(uuid.NAMESPACE_URL, str(audio_path)))
        media_info = self._get_media_info(audio_path)
        media_file = MediaFile(
            id=file_id,
            path=audio_path,
            original_name=audio_path.name,
            info=media_info,
        )

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

        transcription = Transcription(
            source_track_id=audio_track.id,
            language="ko",
            segments=[
                TranscriptSegment(
                    start_ms=seg.start_ms,
                    end_ms=seg.end_ms,
                    text=seg.text,
                )
                for seg in segments
            ],
        )

        all_decisions = []

        # Add silence cuts
        for region in silence_regions:
            all_decisions.append(EditDecision(
                range=TimeRange(start_ms=region.start_ms, end_ms=region.end_ms),
                edit_type=EditType.CUT,
                reason=EditReason.SILENCE,
                confidence=0.95,
                note="SRT gap (no speech)",
                active_video_track_id=video_track.id,
                active_audio_track_ids=[audio_track.id],
            ))

        # Add content decisions with track info
        for decision in content_decisions:
            decision.active_video_track_id = video_track.id
            decision.active_audio_track_ids = [audio_track.id]
            all_decisions.append(decision)

        all_decisions.sort(key=lambda d: d.range.start_ms)

        project = Project(
            name=f"Podcast Edit - {audio_path.stem}",
            source_files=[media_file],
            tracks=[video_track, audio_track],
            transcription=transcription,
            edit_decisions=all_decisions,
        )

        return project

    def _get_duration(self, audio_path: Path) -> int:
        """Get audio duration in milliseconds using ffprobe."""
        cmd = [
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            str(audio_path),
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            return 600000  # Default 10 min

        try:
            data = json.loads(result.stdout)
            duration = float(data["format"]["duration"])
            return int(duration * 1000)
        except (KeyError, ValueError, json.JSONDecodeError):
            return 600000

    def _get_media_info(self, path: Path) -> MediaInfo:
        """Get full media info using ffprobe (video dimensions, fps, sample rate)."""
        cmd = [
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_format", "-show_streams", str(path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            return MediaInfo(duration_ms=self._get_duration(path), sample_rate=44100)

        try:
            data = json.loads(result.stdout)
        except (json.JSONDecodeError, ValueError):
            return MediaInfo(duration_ms=self._get_duration(path), sample_rate=44100)

        duration_sec = float(data.get("format", {}).get("duration", 0))
        width = None
        height = None
        fps = None
        sample_rate = None

        for stream in data.get("streams", []):
            if stream.get("codec_type") == "video":
                width = stream.get("width")
                height = stream.get("height")
                fps_str = stream.get("r_frame_rate", "0/1")
                if "/" in fps_str:
                    num, den = fps_str.split("/")
                    fps = float(num) / float(den) if float(den) != 0 else None
            elif stream.get("codec_type") == "audio":
                sample_rate = int(stream.get("sample_rate", 0)) or None

        return MediaInfo(
            duration_ms=int(duration_sec * 1000),
            width=width,
            height=height,
            fps=fps,
            sample_rate=sample_rate,
        )
