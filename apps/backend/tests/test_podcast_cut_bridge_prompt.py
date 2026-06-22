import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SKILLS_DIR = ROOT / "skills"
PODCAST_DIR = SKILLS_DIR / "podcast-cut"
BACKEND_SRC_DIR = ROOT / "apps" / "backend" / "src"
for candidate in (SKILLS_DIR, PODCAST_DIR, BACKEND_SRC_DIR):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from _common import SubtitleSegment
from avid.export.fcpxml import FCPXMLExporter
from avid.models.project import Project, TranscriptSegment, Transcription


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


codex_analyzer = _load_module("podcast_cut_codex_analyzer", PODCAST_DIR / "codex_analyzer.py")
claude_analyzer = _load_module("podcast_cut_claude_analyzer", PODCAST_DIR / "claude_analyzer.py")
podcast_main = _load_module("podcast_cut_main", PODCAST_DIR / "main.py")


def test_format_segments_for_prompt_includes_ms_gap_and_speaker():
    segments = [
        SubtitleSegment(index=1, start_ms=1000, end_ms=2000, text="first", speaker="A"),
        SubtitleSegment(index=2, start_ms=2050, end_ms=3000, text="second", speaker="A"),
    ]

    prompt = codex_analyzer.format_segments_for_prompt(segments)

    assert "[1] 1000ms-2000ms speaker=A gap_from_prev_ms=unknown gap_to_next_ms=50" in prompt
    assert "[2] 2050ms-3000ms speaker=A gap_from_prev_ms=50 gap_to_next_ms=unknown" in prompt
    assert 'text: "first"' in prompt


def test_podcast_prompts_leave_bridge_decision_to_llm():
    for prompt in (
        codex_analyzer.PODCAST_ANALYSIS_PROMPT,
        claude_analyzer.PODCAST_ANALYSIS_PROMPT,
    ):
        assert "`gap_from_prev_ms`, `gap_to_next_ms`, `speaker`" in prompt
        assert "bridge 발화는 filler처럼 보여도 연결에 필요할 수 있습니다" in prompt
        assert "segmentation/chunk artifact" in prompt
        assert "이전/다음 segment와 합쳐 실제 문장으로 읽은 뒤 CUT/KEEP" in prompt
        assert "note에 앞뒤 연결이 자연스러운 이유" in prompt


def test_podcast_prompts_limit_fumble_to_clear_self_correction():
    for prompt in (
        codex_analyzer.PODCAST_ANALYSIS_PROMPT,
        claude_analyzer.PODCAST_ANALYSIS_PROMPT,
    ):
        assert '"fumble"' in prompt
        assert "곧바로 자기수정/재시작" in prompt
        assert "fragment만으로 fumble 처리하지 마세요" in prompt


def test_bridge_cut_decisions_are_preserved_in_project_json():
    segments = [
        SubtitleSegment(
            index=1216,
            start_ms=2174202,
            end_ms=2175562,
            text="어떤 부작용이 있을",
            speaker="speaker_0",
        ),
        SubtitleSegment(
            index=1217,
            start_ms=2175562,
            end_ms=2176132,
            text="수 있는지.",
            speaker="speaker_0",
        ),
        SubtitleSegment(
            index=1218,
            start_ms=2176200,
            end_ms=2178200,
            text="예를 들어 이런 문제가 있습니다.",
            speaker="speaker_0",
        ),
    ]
    cuts = [
        {
            "segment_index": 1216,
            "reason": "fumble",
            "entertainment_score": 2,
            "note": "LLM decision",
        },
        {
            "segment_index": 1217,
            "reason": "filler",
            "entertainment_score": 2,
            "note": "LLM decision",
        },
    ]

    project = podcast_main.generate_project_json(
        cuts=cuts,
        segments=segments,
        source_video_path="/tmp/source.mp4",
        project_name="bridge regression",
    )

    decisions = project["edit_decisions"]
    assert [decision["source_segment_index"] for decision in decisions] == [1216, 1217]
    assert [decision["reason"] for decision in decisions] == ["fumble", "filler"]
    assert all(decision["origin_kind"] == "content_segment" for decision in decisions)


def test_bridge_protection_postprocessor_is_not_exposed():
    assert not hasattr(podcast_main, "protect_bridge_cuts")


def test_fcpxml_merges_adjacent_enabled_review_segments_for_same_speaker():
    project = Project(
        transcription=Transcription(
            source_track_id="audio",
            segments=[
                TranscriptSegment(index=1, start_ms=1000, end_ms=2000, text="a", speaker="A"),
                TranscriptSegment(index=2, start_ms=2050, end_ms=3000, text="b", speaker="A"),
                TranscriptSegment(index=3, start_ms=3100, end_ms=3500, text="c", speaker="B"),
                TranscriptSegment(index=4, start_ms=3550, end_ms=3900, text="d", speaker="B"),
            ],
        )
    )
    segments = [
        (1, 1000, 2000, "enabled"),
        (2, 2050, 3000, "enabled"),
        (3, 3100, 3500, "disabled"),
        (4, 3550, 3900, "enabled"),
    ]

    merged = FCPXMLExporter()._merge_adjacent_enabled_review_segments(project, segments)

    assert merged == [
        (1000, 3000, "enabled"),
        (3100, 3500, "disabled"),
        (3550, 3900, "enabled"),
    ]


def test_fcpxml_does_not_merge_enabled_review_segments_without_known_same_speaker():
    project = Project(
        transcription=Transcription(
            source_track_id="audio",
            segments=[
                TranscriptSegment(index=1, start_ms=1000, end_ms=2000, text="a", speaker=None),
                TranscriptSegment(index=2, start_ms=2050, end_ms=3000, text="b", speaker=None),
                TranscriptSegment(index=3, start_ms=3050, end_ms=3500, text="c", speaker="A"),
                TranscriptSegment(index=4, start_ms=3550, end_ms=3900, text="d", speaker="B"),
            ],
        )
    )
    segments = [
        (1, 1000, 2000, "enabled"),
        (2, 2050, 3000, "enabled"),
        (3, 3050, 3500, "enabled"),
        (4, 3550, 3900, "enabled"),
    ]

    merged = FCPXMLExporter()._merge_adjacent_enabled_review_segments(project, segments)

    assert merged == [
        (1000, 2000, "enabled"),
        (2050, 3000, "enabled"),
        (3050, 3500, "enabled"),
        (3550, 3900, "enabled"),
    ]
