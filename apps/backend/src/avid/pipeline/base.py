"""Base class for pipeline stages."""

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

from avid.models.pipeline import StageResult
from avid.pipeline.context import PipelineContext

ProgressCallback = Callable[[float, str], None]


class PipelineStage(ABC):
    """Abstract base class for pipeline stages.

    Each stage represents a step in the video editing pipeline,
    such as syncing, transcription, silence detection, etc.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifier for this stage."""
        ...

    @property
    @abstractmethod
    def display_name(self) -> str:
        """Human-readable name for UI display."""
        ...

    @property
    def description(self) -> str:
        """Optional description of what this stage does."""
        return ""

    @abstractmethod
    async def execute(
        self,
        context: PipelineContext,
        options: dict[str, Any],
        progress_callback: ProgressCallback | None = None,
    ) -> StageResult:
        """Execute this pipeline stage.

        Args:
            context: Shared pipeline context with media and timeline data
            options: Stage-specific configuration options
            progress_callback: Optional callback for progress updates (0-1, message)

        Returns:
            StageResult with status and any output data
        """
        ...

    async def rollback(self, context: PipelineContext) -> None:
        """Rollback any changes made by this stage.

        Override this method if the stage makes changes that need
        to be undone on failure.

        Args:
            context: Shared pipeline context
        """
        pass

    async def validate(self, context: PipelineContext) -> bool:
        """Validate that this stage can run with the current context.

        Override to add pre-execution validation.

        Args:
            context: Shared pipeline context

        Returns:
            True if validation passes, False otherwise
        """
        return True

    def _report_progress(
        self,
        callback: ProgressCallback | None,
        progress: float,
        message: str,
    ) -> None:
        """Helper to safely report progress."""
        if callback:
            callback(min(max(progress, 0.0), 1.0), message)
