"""Podcast cut analysis service.

Full workflow for podcast editing:
1. Call chalna for SRT generation
2. Analyze story structure and chapters
3. Split into semantic chunks
4. Analyze each chunk for entertainment value
5. Find silence gaps from SRT (gaps between segments)
6. Merge results into unified Project
"""

import asyncio
import json
import re
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path

from avid.models.media import MediaFile, MediaInfo
from avid.models.project import Project, Transcription, TranscriptSegment
from avid.models.timeline import EditDecision, EditReason, EditType, TimeRange
from avid.models.track import Track, TrackType


# Chunk configuration
MAX_SEGMENTS_PER_CHUNK = 60
CHUNK_OVERLAP = 3


@dataclass
class ChapterInfo:
    """Information about a chapter/topic in the podcast."""
    title: str
    start_segment: int
    end_segment: int
    summary: str


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


class PodcastCutService:
    """Full podcast editing workflow service.

    This service orchestrates:
    1. Transcription via chalna
    2. Story structure analysis
    3. Entertainment-based editing analysis
    4. Silence detection
    5. Final project generation

    Usage:
        service = PodcastCutService()
        project, outputs = await service.process(
            audio_path=Path("podcast.m4a"),
            output_dir=Path("./output"),
        )
    """

    def __init__(
        self,
        chalna_host: str = "localhost",
        chalna_port: int = 8000,
        silence_min_gap_ms: int = 500,
    ):
        """Initialize the service.

        Args:
            chalna_host: Chalna server host
            chalna_port: Chalna server port
            silence_min_gap_ms: Minimum gap between SRT segments to consider as silence (ms)
        """
        self.chalna_host = chalna_host
        self.chalna_port = chalna_port
        self.silence_min_gap_ms = silence_min_gap_ms

    async def process(
        self,
        audio_path: Path,
        output_dir: Path | None = None,
        srt_path: Path | None = None,
        skip_transcription: bool = False,
        export_mode: str = "review",
        storyline_path: Path | None = None,
    ) -> tuple[Project, dict[str, Path]]:
        """Process a podcast audio file through the full workflow.

        Args:
            audio_path: Path to audio/video file
            output_dir: Output directory (default: same as audio)
            srt_path: Existing SRT file (skip transcription if provided)
            skip_transcription: Skip transcription step
            export_mode: "review" (disabled for review) or "final" (all cuts applied)
            storyline_path: Optional path to storyline.json from Pass 1.
                           If not provided and SRT exists, auto-generates via TranscriptOverviewService.

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

        # Step 2: Load or generate storyline context (Pass 1)
        storyline_data = None
        if storyline_path and Path(storyline_path).exists():
            print(f"Step 2: Loading existing storyline: {storyline_path}")
            with open(storyline_path, encoding="utf-8") as f:
                storyline_data = json.load(f)
            # Extract chapters from storyline
            chapters = [
                ChapterInfo(
                    title=ch.get("title", ""),
                    start_segment=ch.get("start_segment", 0),
                    end_segment=ch.get("end_segment", 0),
                    summary=ch.get("summary", ""),
                )
                for ch in storyline_data.get("chapters", [])
            ]
            print(f"  Loaded {len(chapters)} chapters from storyline")
        else:
            print("Step 2: Analyzing story structure...")
            chapters = await self._analyze_chapters(segments)
            print(f"  Found {len(chapters)} chapters/topics")

        # Step 3: Analyze entertainment value in chunks
        print("Step 3: Analyzing entertainment value...")
        content_decisions = await self._analyze_entertainment(segments, chapters, storyline_data)
        print(f"  Generated {len(content_decisions)} content edit decisions")

        # Step 4: Find silence gaps from SRT
        print("Step 4: Finding silence gaps from SRT...")
        silence_regions = self._find_silence_gaps(segments)
        print(f"  Found {len(silence_regions)} silence gaps")

        # Step 5: Build project
        print("Step 5: Building project...")
        project = self._build_project(
            audio_path=audio_path,
            segments=segments,
            content_decisions=content_decisions,
            silence_regions=silence_regions,
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
            # Final mode: all edits are applied (cut)
            show_disabled = False
            content_mode = "cut"
        else:
            # Review mode: content edits shown as disabled for review
            show_disabled = True
            content_mode = "disabled"

        fcpxml_result, srt_result = await exporter.export(
            project,
            fcpxml_path,
            show_disabled_cuts=show_disabled,
            silence_mode="cut",         # Silence is always cut
            content_mode=content_mode,
        )
        outputs["fcpxml"] = fcpxml_result
        if srt_result:
            outputs["srt_adjusted"] = srt_result
            print(f"  Adjusted SRT: {srt_result}")

        print(f"\nComplete: {len(project.edit_decisions)} total edit decisions")
        return project, outputs

    async def _transcribe_with_chalna(
        self,
        audio_path: Path,
        output_dir: Path,
    ) -> Path:
        """Call chalna CLI to generate SRT.

        Args:
            audio_path: Path to audio file
            output_dir: Output directory

        Returns:
            Path to generated SRT file
        """
        output_srt = output_dir / f"{audio_path.stem}.srt"

        # Try CLI first
        cmd = [
            "chalna", "transcribe",
            str(audio_path),
            "-o", str(output_srt),
            "--no-speaker",  # Single track mode
        ]

        try:
            result = await asyncio.to_thread(
                subprocess.run,
                cmd,
                capture_output=True,
                text=True,
                timeout=600,  # 10 min timeout
            )

            if result.returncode == 0 and output_srt.exists():
                return output_srt

            # CLI failed, try REST API
            raise RuntimeError(f"chalna CLI failed: {result.stderr}")

        except FileNotFoundError:
            # chalna CLI not found, try REST API
            return await self._transcribe_with_chalna_api(audio_path, output_dir)

    async def _transcribe_with_chalna_api(
        self,
        audio_path: Path,
        output_dir: Path,
    ) -> Path:
        """Call chalna REST API to generate SRT.

        Args:
            audio_path: Path to audio file
            output_dir: Output directory

        Returns:
            Path to generated SRT file
        """
        import aiohttp

        output_srt = output_dir / f"{audio_path.stem}.srt"
        url = f"http://{self.chalna_host}:{self.chalna_port}/transcribe"

        async with aiohttp.ClientSession() as session:
            with open(audio_path, "rb") as f:
                data = aiohttp.FormData()
                data.add_field("file", f, filename=audio_path.name)
                data.add_field("output_format", "srt")

                async with session.post(url, data=data) as resp:
                    if resp.status != 200:
                        raise RuntimeError(f"Chalna API error: {await resp.text()}")

                    srt_content = await resp.text()

        with open(output_srt, "w", encoding="utf-8") as f:
            f.write(srt_content)

        return output_srt

    def _parse_srt(self, srt_path: Path) -> list[SubtitleSegment]:
        """Parse SRT file into segments.

        Args:
            srt_path: Path to SRT file

        Returns:
            List of SubtitleSegment objects
        """
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

    async def _analyze_chapters(
        self,
        segments: list[SubtitleSegment],
    ) -> list[ChapterInfo]:
        """Analyze story structure to identify chapters/topics.

        Args:
            segments: List of subtitle segments

        Returns:
            List of ChapterInfo objects
        """
        if len(segments) <= MAX_SEGMENTS_PER_CHUNK:
            # Small enough, treat as single chapter
            return [ChapterInfo(
                title="Main Content",
                start_segment=0,
                end_segment=len(segments) - 1,
                summary="Single segment podcast",
            )]

        # Format segments for Claude
        segments_text = "\n".join(
            f"[{seg.index}] ({seg.start_ms // 1000}s): {seg.text[:80]}"
            for seg in segments
        )

        prompt = f'''아래 팟캐스트 자막을 보고 주제가 바뀌는 지점을 찾아주세요.
각 챕터/토픽의 시작 세그먼트 번호와 제목을 알려주세요.

## 자막:
{segments_text}

## 출력 형식 (JSON):
```json
{{
  "chapters": [
    {{"start_segment": 1, "title": "인트로", "summary": "오프닝 인사"}},
    {{"start_segment": 45, "title": "몰트북 소개", "summary": "AI 소셜 네트워크 설명"}},
    {{"start_segment": 120, "title": "클로드 코드 팁", "summary": "요금제 효율성 논의"}}
  ]
}}
```

JSON만 출력하세요.'''

        response = await self._call_claude(prompt)
        data = self._parse_json_response(response)

        chapters = []
        chapter_list = data.get("chapters", [])

        for i, ch in enumerate(chapter_list):
            start_seg = ch.get("start_segment", 0)
            # End is next chapter's start - 1, or end of segments
            end_seg = (
                chapter_list[i + 1]["start_segment"] - 1
                if i + 1 < len(chapter_list)
                else len(segments) - 1
            )

            chapters.append(ChapterInfo(
                title=ch.get("title", f"Chapter {i + 1}"),
                start_segment=start_seg,
                end_segment=end_seg,
                summary=ch.get("summary", ""),
            ))

        return chapters if chapters else [ChapterInfo(
            title="Main Content",
            start_segment=0,
            end_segment=len(segments) - 1,
            summary="",
        )]

    async def _analyze_entertainment(
        self,
        segments: list[SubtitleSegment],
        chapters: list[ChapterInfo],
        storyline_data: dict | None = None,
    ) -> list[EditDecision]:
        """Analyze segments for entertainment value.

        Processes in chunks based on chapter boundaries.

        Args:
            segments: All subtitle segments
            chapters: Chapter information
            storyline_data: Optional storyline dict from Pass 1

        Returns:
            List of EditDecision objects for boring segments
        """
        all_decisions = []
        segment_map = {seg.index: seg for seg in segments}

        for chapter in chapters:
            # Get segments for this chapter
            chapter_segments = [
                seg for seg in segments
                if chapter.start_segment <= seg.index <= chapter.end_segment
            ]

            if not chapter_segments:
                continue

            # Process in chunks if needed
            for i in range(0, len(chapter_segments), MAX_SEGMENTS_PER_CHUNK - CHUNK_OVERLAP):
                chunk = chapter_segments[i:i + MAX_SEGMENTS_PER_CHUNK]
                chunk_decisions = await self._analyze_chunk(chunk, chapter.title, storyline_data)
                all_decisions.extend(chunk_decisions)

        return all_decisions

    async def _analyze_chunk(
        self,
        segments: list[SubtitleSegment],
        chapter_context: str,
        storyline_data: dict | None = None,
    ) -> list[EditDecision]:
        """Analyze a chunk of segments for entertainment value.

        Args:
            segments: Chunk of segments to analyze
            chapter_context: Context about current chapter
            storyline_data: Optional storyline dict for context injection

        Returns:
            List of EditDecision objects
        """
        segments_text = "\n".join(
            f'[{seg.index}] ({seg.start_ms // 1000}s - {seg.end_ms // 1000}s): "{seg.text}"'
            for seg in segments
        )

        # Build context prefix from storyline if available
        context_prefix = ""
        if storyline_data and segments:
            context_prefix = self._format_chunk_context(storyline_data, segments)

        prompt = f'''{context_prefix}당신은 인기 팟캐스트 편집자입니다.

## 현재 챕터: {chapter_context}

## 자막 세그먼트들:
{segments_text}

## 판단 기준
CUT할 것 (지루한 부분):
- boring: 에너지 낮은 단답, 흥미 없는 긴 설명
- filler: 의미 없는 필러워드 ("어", "음", "그")
- repetitive: 같은 말 반복
- irrelevant: 시청자 무관 내용 (녹화 시간, 화면 설정)

KEEP할 것 (재미있는 부분):
- funny, witty, chemistry, reaction, engaging, climax

## 출력 (CUT할 것만)
```json
{{
  "cuts": [
    {{"segment_index": 4, "reason": "filler", "note": "의미 없는 짧은 대답"}},
    {{"segment_index": 7, "reason": "irrelevant", "note": "녹화 관련 잡담"}}
  ]
}}
```

**중요**: 확실히 지루한 것만 자르세요. 애매하면 유지!
JSON만 출력하세요.'''

        try:
            response = await self._call_claude(prompt, timeout=180)
            data = self._parse_json_response(response)
        except Exception as e:
            print(f"  Warning: Chunk analysis failed: {e}")
            return []

        segment_map = {seg.index: seg for seg in segments}
        decisions = []

        for cut in data.get("cuts", []):
            seg_idx = cut.get("segment_index")
            seg = segment_map.get(seg_idx)
            if not seg:
                continue

            reason_str = cut.get("reason", "boring")
            try:
                reason = EditReason(reason_str)
            except ValueError:
                reason = EditReason.MANUAL

            decisions.append(EditDecision(
                range=TimeRange(start_ms=seg.start_ms, end_ms=seg.end_ms),
                edit_type=EditType.MUTE,  # Disabled for review
                reason=reason,
                confidence=0.85,
                note=cut.get("note", ""),
            ))

        return decisions

    def _format_chunk_context(self, storyline: dict, segments: list[SubtitleSegment]) -> str:
        """Format filtered storyline context for a chunk of segments.

        Args:
            storyline: Full storyline dict
            segments: Chunk of segments

        Returns:
            Context prefix string for the prompt
        """
        if not segments:
            return ""

        start_idx = segments[0].index
        end_idx = segments[-1].index

        lines = ["## 스토리 구조 컨텍스트 (반드시 참고!)\n"]

        # Narrative arc (always include)
        arc = storyline.get("narrative_arc", {})
        if arc.get("summary"):
            lines.append(f"### 전체 요약\n{arc['summary']}")
        if arc.get("flow"):
            lines.append(f"흐름: {arc['flow']}\n")

        # Filtered chapters
        chapters = [
            ch for ch in storyline.get("chapters", [])
            if ch.get("start_segment", 0) <= end_idx and ch.get("end_segment", 0) >= start_idx
        ]
        if chapters:
            lines.append("### 관련 챕터")
            for ch in chapters:
                imp = ch.get("importance", 5)
                lines.append(f"[{ch.get('id', '')}] {ch.get('title', '')} (seg {ch.get('start_segment')}-{ch.get('end_segment')}, importance: {imp})")
            lines.append("")

        # Filtered dependencies
        deps = [
            dep for dep in storyline.get("dependencies", [])
            if any(start_idx <= s <= end_idx for s in dep.get("setup_segments", []) + dep.get("payoff_segments", []))
        ]
        if deps:
            lines.append("### 의존성 (함께 유지)")
            for dep in deps:
                strength_label = {"required": "필수", "strong": "강력", "moderate": "권장"}.get(dep.get("strength", ""), dep.get("strength", ""))
                lines.append(f"- [{strength_label}] seg {dep.get('setup_segments', [])} → seg {dep.get('payoff_segments', [])}: {dep.get('description', '')}")
            lines.append("")

        # Filtered key moments
        kms = [
            km for km in storyline.get("key_moments", [])
            if start_idx <= km.get("segment_index", 0) <= end_idx
        ]
        if kms:
            lines.append("### 핵심 순간 (반드시 유지)")
            for km in kms:
                lines.append(f"- seg {km.get('segment_index')}: [{km.get('type', '')}] {km.get('description', '')}")
            lines.append("")

        # Podcast editing principles
        lines.append("### 편집 원칙 (팟캐스트)")
        lines.append("- 의존성이 있는 세그먼트는 함께 유지 (setup을 자르면 payoff가 의미 없음)")
        lines.append("- 핵심 순간은 반드시 유지")
        lines.append("- 지루해 보여도 이후 payoff가 있는 setup은 유지")
        lines.append("- 콜백 유머의 원본을 자르면 안 됨")
        lines.append("- Q&A 쌍은 함께 유지")
        lines.append("- 고에너지 구간 사이의 쉼은 자르지 마세요\n\n")

        return "\n".join(lines)

    def _find_silence_gaps(self, segments: list[SubtitleSegment]) -> list[SilenceRegion]:
        """Find silence regions from gaps between SRT segments.

        Chalna SRT already provides accurate speech timestamps.
        Gaps between segments are silence regions.

        Args:
            segments: Parsed SRT segments (must be sorted by start time)

        Returns:
            List of SilenceRegion objects
        """
        if not segments:
            return []

        # Sort segments by start time (should already be sorted)
        sorted_segments = sorted(segments, key=lambda s: s.start_ms)

        regions = []

        # Check for silence at the beginning (before first segment)
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

        return regions

    def _build_project(
        self,
        audio_path: Path,
        segments: list[SubtitleSegment],
        content_decisions: list[EditDecision],
        silence_regions: list[SilenceRegion],
    ) -> Project:
        """Build final Project with all edit decisions.

        Args:
            audio_path: Path to source audio
            segments: Subtitle segments
            content_decisions: Content-based edit decisions
            silence_regions: Detected silence regions

        Returns:
            Complete Project object
        """
        # Get audio duration
        duration_ms = self._get_duration(audio_path)

        # Create MediaFile
        file_id = str(uuid.uuid5(uuid.NAMESPACE_URL, str(audio_path)))
        media_info = MediaInfo(
            duration_ms=duration_ms,
            sample_rate=44100,  # Default
        )
        media_file = MediaFile(
            id=file_id,
            path=audio_path,
            original_name=audio_path.name,
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

        # Create transcription
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

        # Build all edit decisions
        all_decisions = []

        # Add silence cuts (CUT type) - gaps from SRT
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

        # Add content decisions (MUTE type) with track info
        for decision in content_decisions:
            decision.active_video_track_id = video_track.id
            decision.active_audio_track_ids = [audio_track.id]
            all_decisions.append(decision)

        # Sort by start time
        all_decisions.sort(key=lambda d: d.range.start_ms)

        # Build project
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

    async def _call_claude(self, prompt: str, timeout: int = 120) -> str:
        """Call Claude CLI."""
        result = await asyncio.to_thread(
            subprocess.run,
            ["claude", "-p", prompt, "--output-format", "text"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        if result.returncode != 0:
            raise RuntimeError(f"Claude CLI error: {result.stderr}")

        return result.stdout.strip()

    def _parse_json_response(self, response: str) -> dict:
        """Parse JSON from Claude response."""
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            pass

        start = response.find("{")
        end = response.rfind("}") + 1
        if start == -1 or end == 0:
            raise ValueError(f"No JSON found: {response[:200]}")

        return json.loads(response[start:end])
