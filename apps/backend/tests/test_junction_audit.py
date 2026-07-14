import json
import sys
from pathlib import Path


SKILLS_DIR = Path(__file__).resolve().parents[3] / "skills"
if str(SKILLS_DIR) not in sys.path:
    sys.path.insert(0, str(SKILLS_DIR))

from _common import SubtitleSegment  # noqa: E402
from _common.junction_audit import (  # noqa: E402
    audit_junctions,
    extract_junction_candidates,
    junction_audit_globally_enabled,
)
from avid.cli import _build_review_segments_payload  # noqa: E402
from avid.models.project import Project, TranscriptSegment, Transcription  # noqa: E402


def _segment(index: int, text: str, *, start_ms: int | None = None) -> SubtitleSegment:
    start = start_ms if start_ms is not None else index * 1000
    return SubtitleSegment(
        index=index,
        start_ms=start,
        end_ms=start + 900,
        text=text,
        speaker="speaker_0",
    )


def _decision(index: int, action: str, reason: str = "tangent") -> dict:
    return {
        "segment_index": index,
        "action": action,
        "reason": reason,
        "note": f"original {action} {index}",
    }


def test_extract_junction_candidates_groups_consecutive_cut_block():
    segments = [_segment(i, f"segment {i}") for i in range(1, 7)]
    cuts = [_decision(3, "cut"), _decision(4, "cut")]
    keeps = [_decision(i, "keep") for i in (1, 2, 5, 6)]

    candidates = extract_junction_candidates(segments, cuts, keeps)

    assert len(candidates) == 1
    assert candidates[0]["junction_id"] == "2-5"
    assert candidates[0]["cut_segment_indices"] == [3, 4]
    assert [3] in candidates[0]["minimal_restore_options"]
    assert [4] in candidates[0]["minimal_restore_options"]
    assert [3, 4] in candidates[0]["minimal_restore_options"]


def test_candidate_context_contains_only_retained_neighbors():
    segments = [_segment(i, f"segment {i}") for i in range(1, 5)]
    candidates = extract_junction_candidates(
        segments,
        [_decision(1, "cut"), _decision(3, "cut")],
        [_decision(2, "keep"), _decision(4, "keep")],
    )

    assert len(candidates) == 1
    assert [item["segment_index"] for item in candidates[0]["left_context"]] == [2]
    assert [item["segment_index"] for item in candidates[0]["right_context"]] == [4]


def test_disabled_audit_never_calls_llm():
    segments = [_segment(1, "left"), _segment(2, "bridge"), _segment(3, "right")]
    calls = 0

    def fail_if_called(_prompt: str) -> str:
        nonlocal calls
        calls += 1
        raise AssertionError("LLM must not be called")

    result = audit_junctions(
        segments,
        [_decision(2, "cut")],
        [_decision(1, "keep"), _decision(3, "keep")],
        enabled=False,
        call_llm=fail_if_called,
    )

    assert calls == 0
    assert result.summary["status"] == "disabled"
    assert [item["segment_index"] for item in result.cuts] == [2]


def test_global_kill_switch_defaults_on_and_accepts_false_values(monkeypatch):
    monkeypatch.delenv("JUNCTION_AUDIT_GLOBAL_ENABLED", raising=False)
    assert junction_audit_globally_enabled() is True

    monkeypatch.setenv("JUNCTION_AUDIT_GLOBAL_ENABLED", "false")
    assert junction_audit_globally_enabled() is False


def test_incomplete_llm_response_is_retried_before_applying():
    segments = [_segment(1, "left"), _segment(2, "bridge"), _segment(3, "right")]
    responses = iter([
        json.dumps({"audits": []}),
        json.dumps({
            "audits": [{
                "junction_id": "1-3",
                "verdict": "accept",
                "awkwardness_type": "none",
                "severity": "none",
                "confidence": 0.99,
                "restore_segment_indices": [],
                "reason": "natural join",
            }]
        }),
    ])

    result = audit_junctions(
        segments,
        [_decision(2, "cut")],
        [_decision(1, "keep"), _decision(3, "keep")],
        call_llm=lambda _prompt: next(responses),
    )

    assert result.summary["status"] == "completed"
    assert result.summary["audited_junction_count"] == 1
    assert [entry["status"] for entry in result.artifact["responses"]] == ["error", "ok"]


def test_regression_restores_511_but_leaves_513_cut():
    segments = [
        _segment(510, "우리가 해볼까?", start_ms=0),
        _segment(511, "마이너스의 농담을 했던 그런 기억이 납니다.", start_ms=900),
        _segment(512, "그런 식으로 막 회사들도 다 나오고 있는데", start_ms=1800),
        _segment(513, "예", start_ms=2700),
    ]
    cuts = [_decision(511, "cut", "minor_meta_joke"), _decision(513, "cut", "filler")]
    keeps = [_decision(510, "keep"), _decision(512, "keep")]

    def auditor(_prompt: str) -> str:
        return json.dumps({
            "audits": [{
                "junction_id": "510-512",
                "verdict": "restore",
                "awkwardness_type": "anecdote_closure_missing",
                "severity": "major",
                "confidence": 0.94,
                "restore_segment_indices": [511],
                "reason": "농담의 마무리가 사라져 접합이 부자연스럽다.",
            }]
        }, ensure_ascii=False)

    result = audit_junctions(
        segments,
        cuts,
        keeps,
        call_llm=auditor,
        model="gpt-test",
        provider="codex",
    )

    assert [item["segment_index"] for item in result.cuts] == [513]
    restored = next(item for item in result.keeps if item["segment_index"] == 511)
    assert restored["junction_repair"]["original_action"] == "cut"
    assert restored["junction_repair"]["repaired_to"] == "keep"
    assert restored["junction_repair"]["user_apply_junction_repair"] is True
    assert result.summary["restored_segment_count"] == 1

    second = audit_junctions(
        segments,
        result.cuts,
        result.keeps,
        call_llm=lambda _prompt: json.dumps({"audits": []}),
    )
    assert [item["segment_index"] for item in second.cuts] == [513]
    assert sum(item["segment_index"] == 511 for item in second.keeps) == 1


def test_regression_restores_555_cause_effect_bridge():
    segments = [
        _segment(554, "로봇 쪽은 스케일이 데이터 단에서 어렵거든요.", start_ms=0),
        _segment(555, "그래서 관련 데이터를 수집하는 업체들이 꽤 있었고요.", start_ms=1000),
        _segment(556, "네, 이렇게 회사들 부스가 있었고", start_ms=2000),
    ]

    result = audit_junctions(
        segments,
        [_decision(555, "cut", "minor_detail")],
        [_decision(554, "keep"), _decision(556, "keep")],
        call_llm=lambda _prompt: json.dumps({
            "audits": [{
                "junction_id": "554-556",
                "verdict": "restore",
                "awkwardness_type": "cause_effect_link_missing",
                "severity": "major",
                "confidence": 0.91,
                "restore_segment_indices": [555],
                "reason": "원인에서 사례로 넘어가는 인과 연결이 사라진다.",
            }]
        }, ensure_ascii=False),
    )

    assert result.cuts == []
    assert any(item["segment_index"] == 555 for item in result.keeps)


def test_partial_restore_is_idempotent_on_a_second_pass():
    segments = [
        _segment(1, "left"),
        _segment(2, "required bridge"),
        _segment(3, "dispensable detail"),
        _segment(4, "right"),
    ]
    first = audit_junctions(
        segments,
        [_decision(2, "cut"), _decision(3, "cut")],
        [_decision(1, "keep"), _decision(4, "keep")],
        call_llm=lambda _prompt: json.dumps({
            "audits": [{
                "junction_id": "1-4",
                "verdict": "restore",
                "awkwardness_type": "grammar_completion_missing",
                "severity": "major",
                "confidence": 0.95,
                "restore_segment_indices": [2],
                "reason": "segment 2 is the minimum bridge",
            }]
        }),
    )
    second_calls = 0

    def second_auditor(_prompt: str) -> str:
        nonlocal second_calls
        second_calls += 1
        return json.dumps({"audits": []})

    second = audit_junctions(
        segments,
        first.cuts,
        first.keeps,
        call_llm=second_auditor,
    )

    assert second_calls == 0
    assert [item["segment_index"] for item in second.cuts] == [3]
    assert [item["segment_index"] for item in second.keeps] == [1, 2, 4]


def test_hard_cut_is_never_auto_restored_and_requires_manual_review():
    segments = [_segment(1, "left"), _segment(2, "다시 갈게요"), _segment(3, "right")]
    result = audit_junctions(
        segments,
        [_decision(2, "cut", "retake_signal")],
        [_decision(1, "keep"), _decision(3, "keep")],
        call_llm=lambda _prompt: json.dumps({
            "audits": [{
                "junction_id": "1-3",
                "verdict": "restore",
                "awkwardness_type": "grammar_completion_missing",
                "severity": "major",
                "confidence": 0.99,
                "restore_segment_indices": [2],
                "reason": "join is awkward",
            }]
        }),
    )

    assert [item["segment_index"] for item in result.cuts] == [2]
    assert result.summary["restored_segment_count"] == 0
    assert result.summary["manual_review_count"] == 1
    assert result.cuts[0]["junction_repair"]["requires_manual_review"] is True


def test_review_payload_exposes_project_junction_audit_stats(tmp_path):
    project = Project(
        transcription=Transcription(
            source_track_id="audio",
            segments=[
                TranscriptSegment(index=1, start_ms=0, end_ms=900, text="hello")
            ],
        ),
        junction_audit={
            "enabled": True,
            "status": "completed",
            "restored_segment_count": 4,
        },
    )

    payload = _build_review_segments_payload(tmp_path / "project.avid.json", project)

    assert payload["stats"]["junction_audit"]["restored_segment_count"] == 4
