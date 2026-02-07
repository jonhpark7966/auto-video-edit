"""Main entry point for AVID application."""

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

import uvicorn
from fastapi import FastAPI

from avid.api.deps import init_job_manager
from avid.api.routes import eval, health, jobs, media
from avid.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialize resources on startup, clean up on shutdown."""
    init_job_manager(max_concurrent=settings.max_concurrent_jobs)
    yield


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="AVID - Auto Video Edit",
        description="Automated video editing pipeline",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Include API routes
    app.include_router(health.router)
    app.include_router(jobs.router)
    app.include_router(eval.router)
    app.include_router(media.router)

    return app


app = create_app()


def main() -> None:
    """Run the application."""
    settings.ensure_directories()
    uvicorn.run(
        "avid.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )


if __name__ == "__main__":
    main()
