"""Unit tests for AudioSyncService."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from avid.models.media import MediaFile, MediaInfo
from avid.models.project import Project
from avid.services.audio_sync import AudioSyncService, SyncResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_media_file(
    file_id: str,
    path: str,
    duration_ms: int = 60_000,
    width: int | None = 1920,
    height: int | None = 1080,
    fps: float | None = 30.0,
    sample_rate: int | None = 48000,
) -> MediaFile:
    return MediaFile(
        id=file_id,
        path=Path(path),
        original_name=Path(path).name,
        info=MediaInfo(
            duration_ms=duration_ms,
            width=width,
            height=height,
            fps=fps,
            sample_rate=sample_rate,
        ),
    )


def _make_project_with_main(main_path: str = "/media/main.mp4") -> Project:
    """Create a minimal Project with one main source file."""
    main_file = _make_media_file("main-id", main_path, duration_ms=120_000)
    project = Project(name="Test Project")
    project.add_source_file(main_file)
    return project


# ---------------------------------------------------------------------------
# SyncResult
# ---------------------------------------------------------------------------

class TestSyncResult:
    def test_basic_fields(self):
        r = SyncResult(offset_ms=1500, confidence=0.85, method="mfcc", standard_score=8.5)
        assert r.offset_ms == 1500
        assert r.confidence == 0.85
        assert r.method == "mfcc"

    def test_manual_override(self):
        r = SyncResult(offset_ms=-500, confidence=1.0, method="manual", standard_score=0.0)
        assert r.method == "manual"
        assert r.confidence == 1.0


# ---------------------------------------------------------------------------
# AudioSyncService.find_offset
# ---------------------------------------------------------------------------

class TestFindOffset:
    @pytest.mark.asyncio
    async def test_find_offset_returns_sync_result(self):
        """find_offset should return a SyncResult with converted offset."""
        mock_result = {"time_offset": 1.5, "standard_score": 8.0}

        # Mock the module import inside find_offset
        mock_find_fn = MagicMock(return_value=mock_result)
        mock_module = MagicMock()
        mock_module.find_offset_between_files = mock_find_fn

        with patch.dict("sys.modules", {
            "audio_offset_finder": MagicMock(),
            "audio_offset_finder.audio_offset_finder": mock_module,
        }), patch(
            "avid.services.audio_sync.AudioSyncService._ensure_wav",
            new_callable=AsyncMock,
            side_effect=lambda p, d, prefix: p,
        ), patch(
            "asyncio.to_thread",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            service = AudioSyncService()
            result = await service.find_offset(
                Path("/media/main.wav"), Path("/media/extra.wav"),
            )

        assert result.offset_ms == 1500
        assert result.confidence == 0.8  # 8.0 / 10.0
        assert result.method == "mfcc"
        assert result.standard_score == 8.0

    @pytest.mark.asyncio
    async def test_find_offset_negative(self):
        """Negative offset means extra started before main."""
        mock_result = {"time_offset": -0.5, "standard_score": 12.0}

        mock_find_fn = MagicMock(return_value=mock_result)
        mock_module = MagicMock()
        mock_module.find_offset_between_files = mock_find_fn

        with patch.dict("sys.modules", {
            "audio_offset_finder": MagicMock(),
            "audio_offset_finder.audio_offset_finder": mock_module,
        }), patch(
            "avid.services.audio_sync.AudioSyncService._ensure_wav",
            new_callable=AsyncMock,
            side_effect=lambda p, d, prefix: p,
        ), patch(
            "asyncio.to_thread",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            service = AudioSyncService()
            result = await service.find_offset(
                Path("/media/main.wav"), Path("/media/extra.wav"),
            )

        assert result.offset_ms == -500
        assert result.confidence == 1.0  # 12/10 clamped to 1.0

    @pytest.mark.asyncio
    async def test_find_offset_import_error(self):
        """Should raise RuntimeError if audio-offset-finder not installed."""
        service = AudioSyncService()

        with patch.dict("sys.modules", {
            "audio_offset_finder": None,
            "audio_offset_finder.audio_offset_finder": None,
        }), patch(
            "avid.services.audio_sync.AudioSyncService._ensure_wav",
            new_callable=AsyncMock,
            side_effect=lambda p, d, prefix: p,
        ):
            # The import inside find_offset will fail
            with pytest.raises((RuntimeError, ImportError)):
                await service.find_offset(
                    Path("/media/main.wav"), Path("/media/extra.wav"),
                )


# ---------------------------------------------------------------------------
# AudioSyncService.add_extra_sources
# ---------------------------------------------------------------------------

class TestAddExtraSources:
    @pytest.mark.asyncio
    async def test_auto_detect_adds_source_and_tracks(self):
        """Auto-sync should add source files and set track offsets."""
        project = _make_project_with_main()
        assert len(project.source_files) == 1
        assert len(project.tracks) == 2  # video + audio from main

        extra_path = Path("/media/cam2.mp4").resolve()
        extra_file = _make_media_file("cam2-id", str(extra_path), duration_ms=115_000)
        sync_result = SyncResult(
            offset_ms=1500, confidence=0.85, method="mfcc", standard_score=8.5,
        )

        service = AudioSyncService()

        with patch.object(
            service, "find_offset", new_callable=AsyncMock, return_value=sync_result,
        ), patch.object(
            service._media, "create_media_file",
            new_callable=AsyncMock, return_value=extra_file,
        ):
            results = await service.add_extra_sources(
                project, Path("/media/main.mp4"), [extra_path],
            )

        assert len(results) == 1
        assert results[0].offset_ms == 1500

        # Project should now have 2 source files
        assert len(project.source_files) == 2

        # cam2 tracks should have offset 1500
        cam2_tracks = [t for t in project.tracks if t.source_file_id == "cam2-id"]
        assert len(cam2_tracks) == 2  # video + audio
        for t in cam2_tracks:
            assert t.offset_ms == 1500

    @pytest.mark.asyncio
    async def test_manual_offset_skips_detection(self):
        """Manual offset should skip find_offset entirely."""
        project = _make_project_with_main()

        extra_path = Path("/media/mic.wav").resolve()
        extra_file = _make_media_file(
            "mic-id", str(extra_path), duration_ms=120_000,
            width=None, height=None, fps=None,  # audio-only
        )

        service = AudioSyncService()
        find_offset_mock = AsyncMock()

        with patch.object(service, "find_offset", find_offset_mock), \
             patch.object(
                 service._media, "create_media_file",
                 new_callable=AsyncMock, return_value=extra_file,
             ):
            results = await service.add_extra_sources(
                project, Path("/media/main.mp4"), [extra_path],
                manual_offsets={extra_path.name: 800},
            )

        # find_offset should NOT have been called
        find_offset_mock.assert_not_called()

        assert results[0].offset_ms == 800
        assert results[0].method == "manual"
        assert results[0].confidence == 1.0

        # mic track should have offset 800
        mic_tracks = [t for t in project.tracks if t.source_file_id == "mic-id"]
        assert len(mic_tracks) == 1  # audio only
        assert mic_tracks[0].offset_ms == 800

    @pytest.mark.asyncio
    async def test_multiple_extra_sources(self):
        """Should handle multiple extra sources with mixed auto/manual."""
        project = _make_project_with_main()

        cam2_path = Path("/media/cam2.mp4").resolve()
        mic_path = Path("/media/mic.wav").resolve()

        cam2_file = _make_media_file("cam2-id", str(cam2_path), duration_ms=115_000)
        mic_file = _make_media_file(
            "mic-id", str(mic_path), duration_ms=120_000,
            width=None, height=None, fps=None,
        )

        cam2_sync = SyncResult(offset_ms=1500, confidence=0.9, method="mfcc", standard_score=9.0)

        service = AudioSyncService()

        with patch.object(
            service, "find_offset", new_callable=AsyncMock, return_value=cam2_sync,
        ), patch.object(
            service._media, "create_media_file",
            new_callable=AsyncMock,
            side_effect=[cam2_file, mic_file],
        ):
            results = await service.add_extra_sources(
                project, Path("/media/main.mp4"),
                [cam2_path, mic_path],
                manual_offsets={mic_path.name: 800},
            )

        assert len(results) == 2
        assert results[0].method == "mfcc"   # cam2 auto-detected
        assert results[1].method == "manual"  # mic manual
        assert len(project.source_files) == 3

    @pytest.mark.asyncio
    async def test_empty_extra_sources(self):
        """Empty list should be a no-op."""
        project = _make_project_with_main()
        service = AudioSyncService()

        results = await service.add_extra_sources(
            project, Path("/media/main.mp4"), [],
        )

        assert results == []
        assert len(project.source_files) == 1


# ---------------------------------------------------------------------------
# Backward compatibility
# ---------------------------------------------------------------------------

class TestBackwardCompat:
    def test_project_works_without_extra_sources(self):
        """A single-source project should work unchanged."""
        project = _make_project_with_main()

        assert len(project.source_files) == 1
        assert len(project.get_video_tracks()) == 1
        assert len(project.get_audio_tracks()) == 1
        assert project.get_video_tracks()[0].offset_ms == 0
