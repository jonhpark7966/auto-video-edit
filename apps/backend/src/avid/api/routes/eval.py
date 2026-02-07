"""Evaluation endpoint."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException

from avid.api.schemas import EvalRequest, EvalResponse

router = APIRouter(prefix="/api/v1", tags=["eval"])


@router.post("/eval", response_model=EvalResponse)
async def evaluate(req: EvalRequest) -> EvalResponse:
    from avid.services.evaluation import FCPXMLEvaluator

    pred = Path(req.predicted_path)
    gt = Path(req.ground_truth_path)

    if not pred.exists():
        raise HTTPException(status_code=422, detail=f"predicted_path not found: {pred}")
    if not gt.exists():
        raise HTTPException(status_code=422, detail=f"ground_truth_path not found: {gt}")

    evaluator = FCPXMLEvaluator()
    result = evaluator.evaluate(
        predicted_fcpxml=pred,
        ground_truth_fcpxml=gt,
        overlap_threshold_ms=req.threshold_ms,
    )

    return EvalResponse(
        total_gt_cuts=result.total_gt_cuts,
        total_pred_cuts=result.total_pred_cuts,
        matched_cuts=result.matched_cuts,
        missed_cuts=result.missed_cuts,
        extra_cuts=result.extra_cuts,
        precision=result.precision,
        recall=result.recall,
        f1=result.f1,
        gt_cut_duration_ms=result.gt_cut_duration_ms,
        pred_cut_duration_ms=result.pred_cut_duration_ms,
        overlap_duration_ms=result.overlap_duration_ms,
        timeline_overlap_ratio=result.timeline_overlap_ratio,
    )
