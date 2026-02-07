"""Media info endpoint."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from avid.api.schemas import MediaInfoResponse

router = APIRouter(prefix="/api/v1/media", tags=["media"])


@router.get("/info", response_model=MediaInfoResponse)
async def get_media_info(
    path: str = Query(..., description="Path to media file"),
) -> MediaInfoResponse:
    from avid.services.media import MediaService

    file_path = Path(path)
    if not file_path.exists():
        raise HTTPException(status_code=422, detail=f"File not found: {path}")

    service = MediaService()
    info = await service.get_media_info(file_path)

    return MediaInfoResponse(
        duration_ms=info.duration_ms,
        width=info.width,
        height=info.height,
        fps=info.fps,
        sample_rate=info.sample_rate,
    )
