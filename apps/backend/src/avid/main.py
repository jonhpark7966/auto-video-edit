"""Main entry point for AVID application."""

import uvicorn
from fastapi import FastAPI

from avid.api.routes import health
from avid.config import settings


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="AVID - Auto Video Edit",
        description="Automated video editing pipeline",
        version="0.1.0",
    )

    # Include API routes
    app.include_router(health.router)

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
