"""Base class for timeline exporters."""

from abc import ABC, abstractmethod
from pathlib import Path

from avid.models.timeline import Timeline


class TimelineExporter(ABC):
    """Abstract base class for timeline exporters.

    Each exporter generates a file format compatible with
    a specific video editing application.
    """

    @property
    @abstractmethod
    def format_name(self) -> str:
        """Human-readable format name (e.g., 'Final Cut Pro')."""
        ...

    @property
    @abstractmethod
    def file_extension(self) -> str:
        """File extension including dot (e.g., '.fcpxml')."""
        ...

    @abstractmethod
    async def export(self, timeline: Timeline, output_path: Path) -> Path:
        """Export the timeline to the target format.

        Args:
            timeline: Timeline to export
            output_path: Path for the output file

        Returns:
            Path to the exported file
        """
        ...

    def get_output_filename(self, base_name: str) -> str:
        """Generate output filename with correct extension."""
        return f"{base_name}{self.file_extension}"
