"""Edit decision report generator.

Generates human-readable reports of edit decisions with detailed reasoning.
"""

from pathlib import Path

from avid.models.project import Project
from avid.models.timeline import EditDecision, EditReason, EditType


def _ms_to_timestamp(ms: int) -> str:
    """Convert milliseconds to HH:MM:SS.mmm format."""
    hours = ms // 3600000
    minutes = (ms % 3600000) // 60000
    seconds = (ms % 60000) // 1000
    millis = ms % 1000

    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{millis:03d}"
    return f"{minutes:02d}:{seconds:02d}.{millis:03d}"


def _reason_to_korean(reason: EditReason) -> str:
    """Convert EditReason to Korean display text."""
    mapping = {
        EditReason.SILENCE: "무음",
        EditReason.DUPLICATE: "중복",
        EditReason.FILLER: "필러/불완전",
        EditReason.MANUAL: "수동",
    }
    return mapping.get(reason, reason.value)


def _edit_type_to_korean(edit_type: EditType) -> str:
    """Convert EditType to Korean display text."""
    mapping = {
        EditType.CUT: "잘라내기",
        EditType.SPEEDUP: "속도 증가",
        EditType.MUTE: "비활성화",
    }
    return mapping.get(edit_type, edit_type.value)


def generate_edit_report(
    project: Project,
    include_keeps: bool = False,
) -> str:
    """Generate edit decision report in Markdown format.

    Args:
        project: Project with edit decisions
        include_keeps: If True, also list segments that were kept (not cut)

    Returns:
        Markdown formatted report string
    """
    lines = [
        "# 편집 보고서",
        "",
        f"**프로젝트**: {project.name}",
        f"**생성일**: {project.created_at.strftime('%Y-%m-%d %H:%M')}",
        "",
    ]

    if not project.edit_decisions:
        lines.append("편집 결정이 없습니다.")
        return "\n".join(lines)

    # Group by reason
    by_reason: dict[EditReason, list[EditDecision]] = {}
    for decision in project.edit_decisions:
        if decision.reason not in by_reason:
            by_reason[decision.reason] = []
        by_reason[decision.reason].append(decision)

    # Summary
    lines.append("## 요약")
    lines.append("")
    lines.append("| 유형 | 개수 | 총 시간 |")
    lines.append("|------|------|---------|")

    total_decisions = 0
    total_duration_ms = 0

    for reason in [EditReason.SILENCE, EditReason.DUPLICATE, EditReason.FILLER, EditReason.MANUAL]:
        if reason in by_reason:
            decisions = by_reason[reason]
            count = len(decisions)
            duration_ms = sum(d.range.duration_ms for d in decisions)
            duration_str = _ms_to_timestamp(duration_ms)
            reason_korean = _reason_to_korean(reason)
            lines.append(f"| {reason_korean} | {count}개 | {duration_str} |")
            total_decisions += count
            total_duration_ms += duration_ms

    lines.append(f"| **합계** | **{total_decisions}개** | **{_ms_to_timestamp(total_duration_ms)}** |")
    lines.append("")

    # Detailed sections by reason
    for reason in [EditReason.SILENCE, EditReason.DUPLICATE, EditReason.FILLER, EditReason.MANUAL]:
        if reason not in by_reason:
            continue

        decisions = by_reason[reason]
        reason_korean = _reason_to_korean(reason)

        lines.append(f"## {reason_korean} ({len(decisions)}개)")
        lines.append("")

        for i, decision in enumerate(sorted(decisions, key=lambda d: d.range.start_ms), 1):
            start_str = _ms_to_timestamp(decision.range.start_ms)
            end_str = _ms_to_timestamp(decision.range.end_ms)
            duration_str = _ms_to_timestamp(decision.range.duration_ms)
            edit_type_korean = _edit_type_to_korean(decision.edit_type)

            lines.append(f"### {i}. {start_str} - {end_str} ({duration_str})")
            lines.append("")
            lines.append(f"- **편집 타입**: {edit_type_korean}")
            lines.append(f"- **신뢰도**: {decision.confidence:.0%}")

            if decision.note:
                lines.append(f"- **이유**: {decision.note}")

            lines.append("")

    return "\n".join(lines)


def generate_edit_report_json(project: Project) -> dict:
    """Generate edit decision report as structured JSON.

    Args:
        project: Project with edit decisions

    Returns:
        Dictionary with report data
    """
    # Group by reason
    by_reason: dict[str, list[dict]] = {}

    for decision in project.edit_decisions:
        reason_key = decision.reason.value
        if reason_key not in by_reason:
            by_reason[reason_key] = []

        by_reason[reason_key].append({
            "start_ms": decision.range.start_ms,
            "end_ms": decision.range.end_ms,
            "duration_ms": decision.range.duration_ms,
            "edit_type": decision.edit_type.value,
            "confidence": decision.confidence,
            "note": decision.note,
        })

    # Calculate summary
    summary = {}
    total_count = 0
    total_duration_ms = 0

    for reason, decisions in by_reason.items():
        count = len(decisions)
        duration_ms = sum(d["duration_ms"] for d in decisions)
        summary[reason] = {
            "count": count,
            "duration_ms": duration_ms,
        }
        total_count += count
        total_duration_ms += duration_ms

    return {
        "project_name": project.name,
        "created_at": project.created_at.isoformat(),
        "summary": {
            "total_count": total_count,
            "total_duration_ms": total_duration_ms,
            "by_reason": summary,
        },
        "decisions": by_reason,
    }


def save_report(
    project: Project,
    output_path: Path,
    format: str = "markdown",
) -> Path:
    """Save edit report to file.

    Args:
        project: Project with edit decisions
        output_path: Output file path
        format: "markdown" or "json"

    Returns:
        Path to saved report file
    """
    import json

    output_path = Path(output_path)

    if format == "json":
        if not output_path.suffix:
            output_path = output_path.with_suffix(".json")

        report = generate_edit_report_json(project)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

    else:  # markdown
        if not output_path.suffix:
            output_path = output_path.with_suffix(".md")

        report = generate_edit_report(project)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(report)

    return output_path
