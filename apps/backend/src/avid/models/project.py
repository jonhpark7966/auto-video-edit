"""Project model - the main container for all workflow state."""

import json
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field

from avid.models.media import MediaFile
from avid.models.timeline import EditDecision
from avid.models.track import Track, TrackType


class TranscriptSegment(BaseModel):
    """A single segment of transcription with timing."""

    start_ms: int = Field(..., description="Start time in milliseconds")
    end_ms: int = Field(..., description="End time in milliseconds")
    text: str = Field(..., description="Transcribed text")
    confidence: float = Field(
        default=1.0, ge=0.0, le=1.0, description="Transcription confidence"
    )
    speaker: str | None = Field(
        default=None, description="Speaker label from diarization"
    )


class Transcription(BaseModel):
    """Complete transcription result."""

    source_track_id: str = Field(..., description="Audio track used for transcription")
    language: str = Field(default="ko", description="Detected/specified language")
    segments: list[TranscriptSegment] = Field(
        default_factory=list, description="Transcription segments with timing"
    )

    @property
    def full_text(self) -> str:
        """Return full transcription as a single string."""
        return " ".join(seg.text for seg in self.segments)


class Project(BaseModel):
    """Main project container for the entire workflow.

    A Project holds:
    - Source files (video/audio)
    - Tracks extracted from sources (with sync offsets)
    - Transcription results
    - Edit decisions on the unified timeline

    The workflow:
    1. Add source files → tracks are created
    2. Sync tracks → offsets are set
    3. Transcribe → transcription is populated
    4. Detect silence/duplicates → edit_decisions are added
    5. Export to FCPXML
    """

    # Metadata
    name: str = Field(default="Untitled Project", description="Project name")
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    # Source files
    source_files: list[MediaFile] = Field(
        default_factory=list, description="Original media files"
    )

    # Tracks (extracted from source files, with sync info)
    tracks: list[Track] = Field(
        default_factory=list, description="Video/audio tracks with sync offsets"
    )

    # Transcription
    transcription: Transcription | None = Field(
        default=None, description="Transcription result"
    )

    # Edit decisions on unified timeline
    edit_decisions: list[EditDecision] = Field(
        default_factory=list, description="Editing decisions on unified timeline"
    )

    # --- Helper methods ---

    def add_source_file(self, media_file: MediaFile) -> list[Track]:
        """Add a source file and create tracks from it.

        Args:
            media_file: MediaFile to add

        Returns:
            List of created tracks
        """
        self.source_files.append(media_file)
        created_tracks = []

        # Create video track if it's a video file
        if media_file.is_video:
            video_track = Track(
                id=f"{media_file.id}_video",
                source_file_id=media_file.id,
                track_type=TrackType.VIDEO,
                offset_ms=0,
            )
            self.tracks.append(video_track)
            created_tracks.append(video_track)

        # Create audio track if audio exists
        if media_file.info.sample_rate is not None:
            audio_track = Track(
                id=f"{media_file.id}_audio",
                source_file_id=media_file.id,
                track_type=TrackType.AUDIO,
                offset_ms=0,
            )
            self.tracks.append(audio_track)
            created_tracks.append(audio_track)

        self.updated_at = datetime.now()
        return created_tracks

    def get_track(self, track_id: str) -> Track | None:
        """Get a track by ID."""
        for track in self.tracks:
            if track.id == track_id:
                return track
        return None

    def get_source_file(self, file_id: str) -> MediaFile | None:
        """Get a source file by ID."""
        for f in self.source_files:
            if f.id == file_id:
                return f
        return None

    def get_video_tracks(self) -> list[Track]:
        """Get all video tracks."""
        return [t for t in self.tracks if t.is_video]

    def get_audio_tracks(self) -> list[Track]:
        """Get all audio tracks."""
        return [t for t in self.tracks if t.is_audio]

    def set_track_offset(self, track_id: str, offset_ms: int) -> bool:
        """Set sync offset for a track.

        Args:
            track_id: Track ID
            offset_ms: Offset in milliseconds

        Returns:
            True if track was found and updated
        """
        track = self.get_track(track_id)
        if track:
            track.offset_ms = offset_ms
            self.updated_at = datetime.now()
            return True
        return False

    @property
    def duration_ms(self) -> int:
        """Get total duration of unified timeline (max of all tracks with offsets)."""
        if not self.tracks:
            return 0

        max_end = 0
        for track in self.tracks:
            source = self.get_source_file(track.source_file_id)
            if source:
                track_end = track.offset_ms + source.info.duration_ms
                max_end = max(max_end, track_end)

        return max_end

    # --- Serialization ---

    def save(self, path: Path) -> Path:
        """Save project to JSON file.

        Args:
            path: Output file path

        Returns:
            Path to saved file
        """
        path = Path(path)
        if not path.suffix:
            path = path.with_suffix(".avid.json")

        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.model_dump(mode="json"), f, ensure_ascii=False, indent=2, default=str)

        return path

    @classmethod
    def load(cls, path: Path) -> "Project":
        """Load project from JSON file.

        Args:
            path: Path to project file

        Returns:
            Loaded Project
        """
        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        return cls.model_validate(data)

    @classmethod
    def load_and_merge(cls, paths: list[Path], name: str | None = None) -> "Project":
        """Load multiple project files and merge them into one.

        Edit decisions are preserved as-is (may have overlapping ranges).
        Use FCPXMLExporter to handle merging overlapping cuts during export.

        Args:
            paths: List of project file paths to merge
            name: Optional name for merged project

        Returns:
            Merged Project
        """
        if not paths:
            raise ValueError("At least one project path is required")

        # Load first project as base
        merged = cls.load(paths[0])

        # Merge remaining projects
        for path in paths[1:]:
            other = cls.load(path)
            merged.merge_from(other)

        if name:
            merged.name = name

        merged.updated_at = datetime.now()
        return merged

    def merge_from(self, other: "Project") -> None:
        """Merge another project into this one.

        - Source files with same path are consolidated (IDs mapped)
        - Tracks are merged with ID remapping for consolidated sources
        - All edit decisions are appended with track ID remapping
        - Transcription from other is ignored (keeps current)

        Args:
            other: Project to merge from
        """
        # Build mapping from other's IDs to this project's IDs
        # for source files with the same path
        source_id_map: dict[str, str] = {}  # other_id -> self_id
        track_id_map: dict[str, str] = {}   # other_track_id -> self_track_id

        # Map source files by path
        existing_paths = {str(f.path): f.id for f in self.source_files}
        existing_file_ids = {f.id for f in self.source_files}

        for source_file in other.source_files:
            path_str = str(source_file.path)
            if path_str in existing_paths:
                # Same path exists - map the ID
                source_id_map[source_file.id] = existing_paths[path_str]
            elif source_file.id not in existing_file_ids:
                # New source file - add it
                self.source_files.append(source_file)
                existing_file_ids.add(source_file.id)
                existing_paths[path_str] = source_file.id

        # Build track ID mapping based on source ID mapping
        existing_track_ids = {t.id for t in self.tracks}
        for track in other.tracks:
            if track.source_file_id in source_id_map:
                # Source was consolidated - map track ID too
                mapped_source_id = source_id_map[track.source_file_id]
                # Find corresponding track in self
                for self_track in self.tracks:
                    if (self_track.source_file_id == mapped_source_id and
                        self_track.track_type == track.track_type):
                        track_id_map[track.id] = self_track.id
                        break
            elif track.id not in existing_track_ids:
                # New track - add it
                self.tracks.append(track)
                existing_track_ids.add(track.id)

        # Append edit decisions with remapped track IDs
        for decision in other.edit_decisions:
            # Remap video track ID if needed
            video_track_id = decision.active_video_track_id
            if video_track_id and video_track_id in track_id_map:
                video_track_id = track_id_map[video_track_id]

            # Remap audio track IDs if needed
            audio_track_ids = [
                track_id_map.get(aid, aid)
                for aid in decision.active_audio_track_ids
            ]

            # Create remapped decision
            remapped_decision = EditDecision(
                range=decision.range,
                edit_type=decision.edit_type,
                reason=decision.reason,
                confidence=decision.confidence,
                note=decision.note,
                active_video_track_id=video_track_id,
                active_audio_track_ids=audio_track_ids,
                speed_factor=decision.speed_factor,
            )
            self.edit_decisions.append(remapped_decision)

        self.updated_at = datetime.now()
