"""FCPXML-based evaluation service.

Compares a predicted FCPXML (auto-generated) against a ground truth FCPXML
(human-edited) to measure editing quality.
"""

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class EvalResult:
    """Evaluation result from FCPXML comparison."""

    # Counts
    total_gt_cuts: int = 0
    total_pred_cuts: int = 0
    matched_cuts: int = 0
    missed_cuts: int = 0       # in ground truth but not predicted
    extra_cuts: int = 0        # predicted but not in ground truth

    # Time-based
    gt_cut_duration_ms: int = 0
    pred_cut_duration_ms: int = 0
    overlap_duration_ms: int = 0

    # Derived metrics
    @property
    def precision(self) -> float:
        """Of predicted cuts, how many were correct."""
        if self.total_pred_cuts == 0:
            return 0.0
        return self.matched_cuts / self.total_pred_cuts

    @property
    def recall(self) -> float:
        """Of ground truth cuts, how many were found."""
        if self.total_gt_cuts == 0:
            return 0.0
        return self.matched_cuts / self.total_gt_cuts

    @property
    def f1(self) -> float:
        """F1 score."""
        p, r = self.precision, self.recall
        if p + r == 0:
            return 0.0
        return 2 * p * r / (p + r)

    @property
    def timeline_overlap_ratio(self) -> float:
        """How much of ground truth cut time was covered by predictions."""
        if self.gt_cut_duration_ms == 0:
            return 0.0
        return self.overlap_duration_ms / self.gt_cut_duration_ms

    # Detail lists
    matched_ranges: list[tuple[int, int]] = field(default_factory=list)
    missed_ranges: list[tuple[int, int]] = field(default_factory=list)
    extra_ranges: list[tuple[int, int]] = field(default_factory=list)


def _parse_fcpxml_time(time_str: str, fps: float = 30.0) -> int:
    """Parse FCPXML time string to milliseconds.

    Formats:
    - "3003/30000s" (rational)
    - "10s" (seconds)
    - "0s"
    """
    if not time_str:
        return 0

    # Match rational format: numerator/denominators
    match = re.match(r"(\d+)/(\d+)s", time_str)
    if match:
        num = int(match.group(1))
        den = int(match.group(2))
        return int(num * 1000 / den)

    # Match simple seconds: Ns
    match = re.match(r"(\d+)s", time_str)
    if match:
        return int(match.group(1)) * 1000

    return 0


def parse_fcpxml_clips(fcpxml_path: Path) -> tuple[list[tuple[int, int]], int]:
    """Parse FCPXML and extract kept clip source ranges.

    Returns:
        Tuple of (list of (source_start_ms, source_end_ms) for kept clips,
                  total_duration_ms)
    """
    tree = ET.parse(fcpxml_path)
    root = tree.getroot()

    # Find spine element
    spine = root.find(".//spine")
    if spine is None:
        return [], 0

    # Get fps from format
    fps = 30.0
    format_elem = root.find(".//format")
    if format_elem is not None:
        frame_dur = format_elem.get("frameDuration", "")
        match = re.match(r"(\d+)/(\d+)s", frame_dur)
        if match:
            num = int(match.group(1))
            den = int(match.group(2))
            if num > 0:
                fps = den / num

    # Extract clips
    kept_clips = []
    for clip in spine.findall("asset-clip"):
        enabled = clip.get("enabled", "1")
        if enabled == "0":
            continue  # Skip disabled clips (they're cut segments)

        start_ms = _parse_fcpxml_time(clip.get("start", "0s"), fps)
        duration_ms = _parse_fcpxml_time(clip.get("duration", "0s"), fps)
        end_ms = start_ms + duration_ms

        kept_clips.append((start_ms, end_ms))

    # Get total duration from sequence
    total_duration_ms = 0
    seq = root.find(".//sequence")
    if seq is not None:
        total_duration_ms = _parse_fcpxml_time(seq.get("duration", "0s"), fps)

    # If no sequence duration, estimate from clips
    if total_duration_ms == 0 and kept_clips:
        total_duration_ms = max(end for _, end in kept_clips)

    return kept_clips, total_duration_ms


def _derive_cuts(
    kept_clips: list[tuple[int, int]], total_duration_ms: int
) -> list[tuple[int, int]]:
    """Derive cut ranges from kept clips.

    Cuts are the gaps between kept clips within the total duration.
    """
    if not kept_clips:
        if total_duration_ms > 0:
            return [(0, total_duration_ms)]
        return []

    # Sort by start
    sorted_clips = sorted(kept_clips)
    cuts = []

    # Gap before first clip
    if sorted_clips[0][0] > 0:
        cuts.append((0, sorted_clips[0][0]))

    # Gaps between clips
    for i in range(len(sorted_clips) - 1):
        gap_start = sorted_clips[i][1]
        gap_end = sorted_clips[i + 1][0]
        if gap_end > gap_start:
            cuts.append((gap_start, gap_end))

    # Gap after last clip
    if sorted_clips[-1][1] < total_duration_ms:
        cuts.append((sorted_clips[-1][1], total_duration_ms))

    return cuts


def _ranges_overlap(r1: tuple[int, int], r2: tuple[int, int]) -> int:
    """Calculate overlap in ms between two ranges."""
    start = max(r1[0], r2[0])
    end = min(r1[1], r2[1])
    return max(0, end - start)


class FCPXMLEvaluator:
    """Compare predicted FCPXML against ground truth FCPXML."""

    def evaluate(
        self,
        predicted_fcpxml: Path,
        ground_truth_fcpxml: Path,
        overlap_threshold_ms: int = 200,
    ) -> EvalResult:
        """Compare two FCPXMLs and compute metrics.

        Args:
            predicted_fcpxml: Auto-generated FCPXML
            ground_truth_fcpxml: Human-edited ground truth FCPXML
            overlap_threshold_ms: Minimum overlap to consider a match

        Returns:
            EvalResult with all metrics
        """
        predicted_fcpxml = Path(predicted_fcpxml)
        ground_truth_fcpxml = Path(ground_truth_fcpxml)

        if not predicted_fcpxml.exists():
            raise FileNotFoundError(f"Predicted FCPXML not found: {predicted_fcpxml}")
        if not ground_truth_fcpxml.exists():
            raise FileNotFoundError(f"Ground truth FCPXML not found: {ground_truth_fcpxml}")

        # Parse both FCPXMLs
        pred_clips, pred_total = parse_fcpxml_clips(predicted_fcpxml)
        gt_clips, gt_total = parse_fcpxml_clips(ground_truth_fcpxml)

        # Use the larger total duration
        total_ms = max(pred_total, gt_total)

        # Derive cuts (inverse of kept clips)
        pred_cuts = _derive_cuts(pred_clips, total_ms)
        gt_cuts = _derive_cuts(gt_clips, total_ms)

        # Match cuts
        result = EvalResult(
            total_gt_cuts=len(gt_cuts),
            total_pred_cuts=len(pred_cuts),
        )

        # Calculate total cut durations
        result.gt_cut_duration_ms = sum(e - s for s, e in gt_cuts)
        result.pred_cut_duration_ms = sum(e - s for s, e in pred_cuts)

        # Match predicted cuts to ground truth cuts
        matched_gt = set()
        for pred in pred_cuts:
            best_overlap = 0
            best_gt_idx = -1

            for gt_idx, gt in enumerate(gt_cuts):
                if gt_idx in matched_gt:
                    continue
                overlap = _ranges_overlap(pred, gt)
                if overlap > best_overlap:
                    best_overlap = overlap
                    best_gt_idx = gt_idx

            if best_overlap >= overlap_threshold_ms and best_gt_idx >= 0:
                result.matched_cuts += 1
                result.overlap_duration_ms += best_overlap
                result.matched_ranges.append(pred)
                matched_gt.add(best_gt_idx)
            else:
                result.extra_cuts += 1
                result.extra_ranges.append(pred)

        # Missed cuts
        for gt_idx, gt in enumerate(gt_cuts):
            if gt_idx not in matched_gt:
                result.missed_cuts += 1
                result.missed_ranges.append(gt)

        return result

    def format_report(self, result: EvalResult) -> str:
        """Format evaluation result as a human-readable report."""
        lines = [
            "=" * 60,
            "FCPXML EVALUATION REPORT",
            "=" * 60,
            "",
            f"Ground Truth cuts: {result.total_gt_cuts}",
            f"Predicted cuts:    {result.total_pred_cuts}",
            "",
            f"Matched:  {result.matched_cuts}",
            f"Missed:   {result.missed_cuts}  (in GT but not predicted)",
            f"Extra:    {result.extra_cuts}  (predicted but not in GT)",
            "",
            f"Precision:  {result.precision:.3f}",
            f"Recall:     {result.recall:.3f}",
            f"F1 Score:   {result.f1:.3f}",
            "",
            f"GT cut duration:   {result.gt_cut_duration_ms / 1000:.2f}s",
            f"Pred cut duration: {result.pred_cut_duration_ms / 1000:.2f}s",
            f"Overlap duration:  {result.overlap_duration_ms / 1000:.2f}s",
            f"Timeline overlap:  {result.timeline_overlap_ratio:.3f}",
        ]

        if result.missed_ranges:
            lines.append("")
            lines.append("--- Missed Cuts ---")
            for start, end in result.missed_ranges:
                lines.append(f"  {start/1000:.2f}s - {end/1000:.2f}s")

        if result.extra_ranges:
            lines.append("")
            lines.append("--- Extra Cuts ---")
            for start, end in result.extra_ranges:
                lines.append(f"  {start/1000:.2f}s - {end/1000:.2f}s")

        lines.append("")
        lines.append("=" * 60)
        return "\n".join(lines)
