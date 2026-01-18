"""Main entry point for AVID application."""

import gradio as gr
import uvicorn
from fastapi import FastAPI

from avid.api.routes import health
from avid.config import settings
from avid.ui.app import create_gradio_app


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="AVID - Auto Video Edit",
        description="Automated video editing pipeline",
        version="0.1.0",
    )

    # Include API routes
    app.include_router(health.router)

    # Mount Gradio app
    gradio_app = create_gradio_app()
    app = gr.mount_gradio_app(app, gradio_app, path="/")

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
