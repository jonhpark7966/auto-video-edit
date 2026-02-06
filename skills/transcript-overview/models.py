"""Data models for transcript-overview skill.

Defines the storyline structure produced by Pass 1 analysis:
narrative arc, chapters, key moments, dependencies, and pacing notes.
"""

from dataclasses import dataclass, field


@dataclass
class NarrativeArc:
    """Overall narrative structure of the content."""
    type: str = "lecture"  # lecture, podcast, interview
    summary: str = ""
    flow: str = ""  # e.g. "인트로 → 배경 → 핵심 → 사례 → 결론"
    tone: str = "educational"  # educational, entertaining, mixed


@dataclass
class Chapter:
    """A chapter/topic segment in the content."""
    id: str = ""
    title: str = ""
    start_segment: int = 0
    end_segment: int = 0
    start_ms: int = 0
    end_ms: int = 0
    summary: str = ""
    role: str = "main_topic"  # intro, context, main_topic, deep_dive, tangent, transition, climax, conclusion, qa, outro
    importance: int = 5  # 1-10
    topics: list[str] = field(default_factory=list)


@dataclass
class KeyMoment:
    """A key moment that should be preserved."""
    segment_index: int = 0
    type: str = "highlight"  # highlight, emotional_peak, callback, punchline, setup
    description: str = ""
    chapter_id: str = ""
    references: list[int] = field(default_factory=list)  # Referenced segment indices


@dataclass
class Dependency:
    """A dependency pair (setup-payoff, callback, Q&A, etc.)."""
    type: str = "setup_payoff"  # setup_payoff, callback, qa_pair, running_joke
    setup_segments: list[int] = field(default_factory=list)
    payoff_segments: list[int] = field(default_factory=list)
    description: str = ""
    strength: str = "strong"  # required, strong, moderate


@dataclass
class PacingSection:
    """A section with notable pacing characteristics."""
    start_segment: int = 0
    end_segment: int = 0
    note: str = ""


@dataclass
class PacingNotes:
    """Pacing observations for the content."""
    slow_sections: list[PacingSection] = field(default_factory=list)
    high_energy_sections: list[PacingSection] = field(default_factory=list)


@dataclass
class TranscriptOverview:
    """Complete storyline analysis output from Pass 1."""
    version: str = "1.0"
    source_srt: str = ""
    total_segments: int = 0
    total_duration_ms: int = 0
    narrative_arc: NarrativeArc = field(default_factory=NarrativeArc)
    chapters: list[Chapter] = field(default_factory=list)
    key_moments: list[KeyMoment] = field(default_factory=list)
    dependencies: list[Dependency] = field(default_factory=list)
    pacing_notes: PacingNotes = field(default_factory=PacingNotes)

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dict."""
        return {
            "version": self.version,
            "source_srt": self.source_srt,
            "total_segments": self.total_segments,
            "total_duration_ms": self.total_duration_ms,
            "narrative_arc": {
                "type": self.narrative_arc.type,
                "summary": self.narrative_arc.summary,
                "flow": self.narrative_arc.flow,
                "tone": self.narrative_arc.tone,
            },
            "chapters": [
                {
                    "id": ch.id,
                    "title": ch.title,
                    "start_segment": ch.start_segment,
                    "end_segment": ch.end_segment,
                    "start_ms": ch.start_ms,
                    "end_ms": ch.end_ms,
                    "summary": ch.summary,
                    "role": ch.role,
                    "importance": ch.importance,
                    "topics": ch.topics,
                }
                for ch in self.chapters
            ],
            "key_moments": [
                {
                    "segment_index": km.segment_index,
                    "type": km.type,
                    "description": km.description,
                    "chapter_id": km.chapter_id,
                    **({"references": km.references} if km.references else {}),
                }
                for km in self.key_moments
            ],
            "dependencies": [
                {
                    "type": dep.type,
                    "setup_segments": dep.setup_segments,
                    "payoff_segments": dep.payoff_segments,
                    "description": dep.description,
                    "strength": dep.strength,
                }
                for dep in self.dependencies
            ],
            "pacing_notes": {
                "slow_sections": [
                    {
                        "start_segment": s.start_segment,
                        "end_segment": s.end_segment,
                        "note": s.note,
                    }
                    for s in self.pacing_notes.slow_sections
                ],
                "high_energy_sections": [
                    {
                        "start_segment": s.start_segment,
                        "end_segment": s.end_segment,
                        "note": s.note,
                    }
                    for s in self.pacing_notes.high_energy_sections
                ],
            },
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TranscriptOverview":
        """Create from JSON dict."""
        arc_data = data.get("narrative_arc", {})
        narrative_arc = NarrativeArc(
            type=arc_data.get("type", "lecture"),
            summary=arc_data.get("summary", ""),
            flow=arc_data.get("flow", ""),
            tone=arc_data.get("tone", "educational"),
        )

        chapters = [
            Chapter(
                id=ch.get("id", f"ch_{i+1}"),
                title=ch.get("title", ""),
                start_segment=ch.get("start_segment", 0),
                end_segment=ch.get("end_segment", 0),
                start_ms=ch.get("start_ms", 0),
                end_ms=ch.get("end_ms", 0),
                summary=ch.get("summary", ""),
                role=ch.get("role", "main_topic"),
                importance=ch.get("importance", 5),
                topics=ch.get("topics", []),
            )
            for i, ch in enumerate(data.get("chapters", []))
        ]

        key_moments = [
            KeyMoment(
                segment_index=km.get("segment_index", 0),
                type=km.get("type", "highlight"),
                description=km.get("description", ""),
                chapter_id=km.get("chapter_id", ""),
                references=km.get("references", []),
            )
            for km in data.get("key_moments", [])
        ]

        dependencies = [
            Dependency(
                type=dep.get("type", "setup_payoff"),
                setup_segments=dep.get("setup_segments", dep.get("question_segments", [])),
                payoff_segments=dep.get("payoff_segments", dep.get("answer_segments", [])),
                description=dep.get("description", ""),
                strength=dep.get("strength", "strong"),
            )
            for dep in data.get("dependencies", [])
        ]

        pacing_data = data.get("pacing_notes", {})
        pacing_notes = PacingNotes(
            slow_sections=[
                PacingSection(
                    start_segment=s.get("start_segment", 0),
                    end_segment=s.get("end_segment", 0),
                    note=s.get("note", ""),
                )
                for s in pacing_data.get("slow_sections", [])
            ],
            high_energy_sections=[
                PacingSection(
                    start_segment=s.get("start_segment", 0),
                    end_segment=s.get("end_segment", 0),
                    note=s.get("note", ""),
                )
                for s in pacing_data.get("high_energy_sections", [])
            ],
        )

        return cls(
            version=data.get("version", "1.0"),
            source_srt=data.get("source_srt", ""),
            total_segments=data.get("total_segments", 0),
            total_duration_ms=data.get("total_duration_ms", 0),
            narrative_arc=narrative_arc,
            chapters=chapters,
            key_moments=key_moments,
            dependencies=dependencies,
            pacing_notes=pacing_notes,
        )
