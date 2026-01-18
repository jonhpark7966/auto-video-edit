"""Pipeline executor for running stages in sequence."""

import logging
from collections.abc import Callable
from typing import Any

from avid.models.pipeline import PipelineConfig, StageResult, StageStatus
from avid.pipeline.base import PipelineStage, ProgressCallback
from avid.pipeline.context import PipelineContext

logger = logging.getLogger(__name__)

ExecutionCallback = Callable[[str, StageStatus, float], None]


class PipelineExecutor:
    """Executes pipeline stages in sequence."""

    def __init__(self) -> None:
        """Initialize the executor."""
        self._stages: dict[str, PipelineStage] = {}

    def register_stage(self, stage: PipelineStage) -> None:
        """Register a pipeline stage."""
        self._stages[stage.name] = stage
        logger.info(f"Registered pipeline stage: {stage.name}")

    def get_stage(self, name: str) -> PipelineStage | None:
        """Get a registered stage by name."""
        return self._stages.get(name)

    def list_stages(self) -> list[tuple[str, str]]:
        """List all registered stages as (name, display_name) tuples."""
        return [(s.name, s.display_name) for s in self._stages.values()]

    async def execute(
        self,
        context: PipelineContext,
        config: PipelineConfig,
        progress_callback: ExecutionCallback | None = None,
    ) -> dict[str, StageResult]:
        """Execute the pipeline with the given configuration.

        Args:
            context: Shared pipeline context
            config: Pipeline configuration specifying stages to run
            progress_callback: Optional callback (stage_name, status, overall_progress)

        Returns:
            Dictionary mapping stage names to their results
        """
        results: dict[str, StageResult] = {}
        completed_stages: list[str] = []
        total_stages = len(config.stages)

        for i, stage_name in enumerate(config.stages):
            stage = self._stages.get(stage_name)

            if stage is None:
                logger.error(f"Unknown stage: {stage_name}")
                results[stage_name] = StageResult.failure(f"Unknown stage: {stage_name}")
                break

            # Report stage starting
            overall_progress = i / total_stages
            self._report_progress(progress_callback, stage_name, StageStatus.RUNNING, overall_progress)

            # Validate stage
            if not await stage.validate(context):
                logger.warning(f"Stage validation failed: {stage_name}")
                results[stage_name] = StageResult.skipped("Validation failed")
                continue

            # Create stage progress callback
            def stage_progress(progress: float, message: str) -> None:
                stage_overall = (i + progress) / total_stages
                self._report_progress(progress_callback, stage_name, StageStatus.RUNNING, stage_overall)

            # Execute stage
            try:
                options = config.get_stage_options(stage_name)
                result = await stage.execute(context, options, stage_progress)
                results[stage_name] = result

                if result.status == StageStatus.COMPLETED:
                    completed_stages.append(stage_name)
                    if result.data:
                        context.set_stage_data(stage_name, result.data)
                    logger.info(f"Stage completed: {stage_name}")
                elif result.status == StageStatus.FAILED:
                    logger.error(f"Stage failed: {stage_name} - {result.message}")
                    # Rollback completed stages in reverse order
                    await self._rollback(context, completed_stages)
                    break

            except Exception as e:
                logger.exception(f"Stage execution error: {stage_name}")
                results[stage_name] = StageResult.failure(str(e))
                await self._rollback(context, completed_stages)
                break

            # Report stage completed
            self._report_progress(
                progress_callback,
                stage_name,
                results[stage_name].status,
                (i + 1) / total_stages,
            )

        return results

    async def _rollback(self, context: PipelineContext, stages: list[str]) -> None:
        """Rollback completed stages in reverse order."""
        for stage_name in reversed(stages):
            stage = self._stages.get(stage_name)
            if stage:
                try:
                    await stage.rollback(context)
                    logger.info(f"Rolled back stage: {stage_name}")
                except Exception:
                    logger.exception(f"Rollback failed for stage: {stage_name}")

    def _report_progress(
        self,
        callback: ExecutionCallback | None,
        stage_name: str,
        status: StageStatus,
        progress: float,
    ) -> None:
        """Helper to safely report progress."""
        if callback:
            callback(stage_name, status, progress)
