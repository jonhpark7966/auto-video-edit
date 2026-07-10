import asyncio
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[3]
SKILLS_DIR = ROOT / "skills"
PODCAST_DIR = SKILLS_DIR / "podcast-cut"
BACKEND_SRC_DIR = ROOT / "apps" / "backend" / "src"
for candidate in (SKILLS_DIR, PODCAST_DIR, BACKEND_SRC_DIR):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from _common import SubtitleSegment
from avid import cli
from avid.services.podcast_cut import PodcastCutService
from prompt_profiles import (
    AI_FRONTIER_PROMPT_SHA256,
    load_edit_decision_prompt,
    render_edit_decision_prompt,
)


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


codex_analyzer = _load_module(
    "podcast_profile_codex_analyzer",
    PODCAST_DIR / "codex_analyzer.py",
)
claude_analyzer = _load_module(
    "podcast_profile_claude_analyzer",
    PODCAST_DIR / "claude_analyzer.py",
)
podcast_main = _load_module(
    "podcast_profile_main",
    PODCAST_DIR / "main.py",
)


def _analysis_response(segment_index: int) -> str:
    return json.dumps(
        {
            "analysis": [
                {
                    "segment_index": segment_index,
                    "action": "keep",
                    "reason": "test",
                    "entertainment_score": 5,
                    "note": "test",
                }
            ]
        }
    )


def test_ai_frontier_prompt_asset_hash_and_format_contract():
    prompt_path = PODCAST_DIR / "prompts" / "ai_frontier.md"
    prompt_bytes = prompt_path.read_bytes()

    assert hashlib.sha256(prompt_bytes).hexdigest() == AI_FRONTIER_PROMPT_SHA256
    template = load_edit_decision_prompt(
        "ai_frontier",
        podcast_prompt="unused {segments}",
    )
    assert template.count("{segments}") == 1

    rendered = render_edit_decision_prompt(
        "ai_frontier",
        "[7] sample segment",
        podcast_prompt="unused {segments}",
    )
    assert "[7] sample segment" in rendered
    example = rendered.split("```json\n", 1)[1].split("\n```", 1)[0]
    assert json.loads(example)["analysis"][0]["segment_index"] == 1


def test_podcast_profile_preserves_each_provider_existing_template():
    for analyzer in (codex_analyzer, claude_analyzer):
        assert load_edit_decision_prompt(
            "podcast",
            podcast_prompt=analyzer.PODCAST_ANALYSIS_PROMPT,
        ) == analyzer.PODCAST_ANALYSIS_PROMPT


@pytest.mark.parametrize(
    ("analyzer", "call_name", "analyze_name"),
    [
        (codex_analyzer, "call_codex", "analyze_with_codex"),
        (claude_analyzer, "call_claude", "analyze_with_claude"),
    ],
)
def test_default_profile_renders_the_existing_podcast_prompt_unchanged(
    monkeypatch,
    analyzer,
    call_name,
    analyze_name,
):
    captured = []

    def fake_provider_call(prompt, timeout):
        captured.append(prompt)
        return _analysis_response(1)

    monkeypatch.setattr(analyzer, call_name, fake_provider_call)
    segments = [
        SubtitleSegment(
            index=1,
            start_ms=0,
            end_ms=1000,
            text="unchanged podcast prompt",
            speaker="speaker_0",
        )
    ]

    getattr(analyzer, analyze_name)(segments)

    expected = analyzer.PODCAST_ANALYSIS_PROMPT.format(
        segments=analyzer.format_segments_for_prompt(segments)
    )
    expected = analyzer._apply_edit_intensity_guidance(expected, "normal")
    assert captured == [expected]


def test_unknown_prompt_profile_is_rejected():
    with pytest.raises(ValueError, match="Unsupported prompt profile"):
        load_edit_decision_prompt(
            "unknown",
            podcast_prompt="base {segments}",
        )


@pytest.mark.parametrize(
    ("analyzer", "call_name", "analyze_name"),
    [
        (codex_analyzer, "call_codex", "analyze_with_codex"),
        (claude_analyzer, "call_claude", "analyze_with_claude"),
    ],
)
def test_ai_frontier_single_pass_keeps_common_prompt_composition(
    monkeypatch,
    analyzer,
    call_name,
    analyze_name,
):
    captured = []

    def fake_provider_call(prompt, timeout):
        captured.append((prompt, timeout))
        return _analysis_response(1)

    monkeypatch.setattr(analyzer, call_name, fake_provider_call)
    segments = [
        SubtitleSegment(
            index=1,
            start_ms=0,
            end_ms=1000,
            text="profile marker segment",
            speaker="mixed",
        )
    ]
    analyze = getattr(analyzer, analyze_name)

    result = analyze(
        segments,
        storyline_context={"narrative_arc": {"summary": "PROFILE STORY"}},
        edit_intensity="heavy",
        edit_decision_version="boundary_aware_v1",
        prompt_profile="ai_frontier",
    )

    assert [item["segment_index"] for item in result.keeps] == [1]
    assert len(captured) == 1
    prompt, timeout = captured[0]
    assert timeout == 600
    assert "You are an edit-decision model for podcast highlight editing." in prompt
    assert "당신은 유명 유튜브 하이라이트 편집자입니다" not in prompt
    assert "profile marker segment" in prompt
    assert "PROFILE STORY" in prompt
    assert "## Mixed speaker handling" in prompt
    assert "## Boundary-aware edit decision rules" in prompt
    assert "## 컷 편집 강도 지시 (최우선)" in prompt


@pytest.mark.parametrize(
    ("analyzer", "call_name"),
    [
        (codex_analyzer, "call_codex"),
        (claude_analyzer, "call_claude"),
    ],
)
def test_ai_frontier_profile_reaches_chunk_prompt(monkeypatch, analyzer, call_name):
    captured = []

    def fake_provider_call(prompt, timeout):
        captured.append(prompt)
        return _analysis_response(9)

    monkeypatch.setattr(analyzer, call_name, fake_provider_call)
    segments = [
        SubtitleSegment(
            index=9,
            start_ms=0,
            end_ms=1000,
            text="chunk profile marker",
            speaker="speaker_0",
        )
    ]

    cuts, keeps = analyzer.analyze_chunk(
        segments,
        1,
        1,
        prompt_profile="ai_frontier",
    )

    assert cuts == []
    assert [item["segment_index"] for item in keeps] == [9]
    assert "You are an edit-decision model for podcast highlight editing." in captured[0]
    assert "chunk profile marker" in captured[0]


def test_podcast_cut_service_forwards_prompt_profile_to_skill(monkeypatch, tmp_path):
    captured = []
    output_path = tmp_path / "skill.avid.json"

    def fake_run(command, **kwargs):
        captured.append((command, kwargs))
        output_path.write_text("{}", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    asyncio.run(
        PodcastCutService()._run_podcast_cut_skill(
            srt_path=tmp_path / "source.srt",
            audio_path=tmp_path / "source.mp4",
            output_path=output_path,
            prompt_profile="ai_frontier",
        )
    )

    command, _ = captured[0]
    profile_index = command.index("--prompt-profile")
    assert command[profile_index + 1] == "ai_frontier"


def test_podcast_skill_main_forwards_prompt_profile_to_analyzer(monkeypatch, tmp_path):
    srt_path = tmp_path / "source.srt"
    srt_path.write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nhello\n",
        encoding="utf-8",
    )
    captured = []

    def fake_analyze(segments, **kwargs):
        captured.append((segments, kwargs))
        return SimpleNamespace(cuts=[], keeps=[])

    monkeypatch.setattr(podcast_main, "analyze_with_codex", fake_analyze)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "podcast-cut",
            str(srt_path),
            str(tmp_path / "source.mp4"),
            "--provider",
            "codex",
            "--prompt-profile",
            "ai_frontier",
            "--report-only",
        ],
    )

    podcast_main.main()

    assert captured[0][1]["prompt_profile"] == "ai_frontier"


@pytest.mark.parametrize(
    ("arguments", "expected_profile"),
    [
        (["podcast-cut", "source.mp4"], "podcast"),
        (
            ["podcast-cut", "source.mp4", "--prompt-profile", "ai_frontier"],
            "ai_frontier",
        ),
    ],
)
def test_avid_cli_podcast_prompt_profile_contract(
    monkeypatch,
    arguments,
    expected_profile,
):
    captured = []

    def fake_run_handler(args, handler, *, is_async):
        captured.append(args)
        return {}

    monkeypatch.setattr(cli, "_run_handler", fake_run_handler)
    monkeypatch.setattr(cli, "_write_machine_output", lambda args, payload: None)
    monkeypatch.setattr(sys, "argv", ["avid-cli", *arguments])

    cli.main()

    assert captured[0].prompt_profile == expected_profile
