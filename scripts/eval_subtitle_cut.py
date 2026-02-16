#!/usr/bin/env python3
"""Evaluate subtitle-cut results against human ground truth.

Usage:
    python eval_subtitle_cut.py --avid-json <path> --ground-truth <path> [--output <path>] [--append-tracking <path>]

Outputs JSON with confusion matrix, metrics, error breakdown, and timing info.
"""

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path


def get_ai_decision(seg_start: int, seg_end: int, edit_decisions: list) -> tuple[str, str]:
    """Get AI's decision for a segment by overlap matching."""
    for ed in edit_decisions:
        ed_start = ed["range"]["start_ms"]
        ed_end = ed["range"]["end_ms"]
        if ed_start < seg_end and ed_end > seg_start:
            edit_type = ed.get("edit_type", "")
            action = "cut" if edit_type in ("cut", "mute") else "keep"
            return action, ed.get("reason", "")
    return "keep", ""


def evaluate(avid_json_path: str, ground_truth_path: str) -> dict:
    """Run full evaluation. Returns metrics dict."""
    with open(avid_json_path) as f:
        avid_data = json.load(f)
    with open(ground_truth_path) as f:
        eval_segments = json.load(f)

    segments = avid_data.get("transcription", {}).get("segments", [])
    edit_decisions = avid_data.get("edit_decisions", [])

    if not segments:
        return {"error": "No transcription segments found in avid.json"}

    tp = tn = fp = fn = 0
    fp_reasons: Counter = Counter()
    fn_reasons: Counter = Counter()
    fp_ms: Counter = Counter()
    fn_ms: Counter = Counter()
    disagreements = []

    for i, seg in enumerate(segments):
        s, e = seg["start_ms"], seg["end_ms"]
        dur = e - s
        ai_action, ai_reason = get_ai_decision(s, e, edit_decisions)

        es = eval_segments[i] if i < len(eval_segments) else None
        if es and es.get("human"):
            truth_action = es["human"]["action"]
            human_reason = es["human"].get("reason", "")
        else:
            truth_action = ai_action  # implicit agreement
            human_reason = ""

        if ai_action == "cut" and truth_action == "cut":
            tp += 1
        elif ai_action == "keep" and truth_action == "keep":
            tn += 1
        elif ai_action == "cut" and truth_action == "keep":
            fp += 1
            fp_reasons[ai_reason or "unknown"] += 1
            fp_ms[ai_reason or "unknown"] += dur
            disagreements.append({
                "index": i, "type": "FP",
                "text": seg.get("text", "")[:60],
                "ai_reason": ai_reason, "human_reason": human_reason,
            })
        elif ai_action == "keep" and truth_action == "cut":
            fn += 1
            fn_reasons[human_reason or "unknown"] += 1
            fn_ms[human_reason or "unknown"] += dur
            disagreements.append({
                "index": i, "type": "FN",
                "text": seg.get("text", "")[:60],
                "ai_reason": ai_reason, "human_reason": human_reason,
            })

    total = tp + tn + fp + fn
    accuracy = (tp + tn) / total if total > 0 else 0
    precision = tp / (tp + fp) if (tp + fp) > 0 else 1.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 1.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0

    # Count content decisions (non-silence)
    content_cuts = sum(1 for ed in edit_decisions if ed.get("reason") != "silence")
    silence_cuts = sum(1 for ed in edit_decisions if ed.get("reason") == "silence")

    # Reason breakdown for all AI cuts
    ai_reason_counts = Counter(ed.get("reason", "unknown") for ed in edit_decisions)

    return {
        "total_segments": len(segments),
        "human_reviewed": sum(1 for es in eval_segments if es and es.get("human")),
        "confusion_matrix": {"tp": tp, "tn": tn, "fp": fp, "fn": fn},
        "metrics": {
            "accuracy": round(accuracy, 4),
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
        },
        "total_errors": fp + fn,
        "content_cuts": content_cuts,
        "silence_cuts": silence_cuts,
        "ai_reason_counts": dict(ai_reason_counts),
        "fp_reasons": dict(fp_reasons),
        "fn_reasons": dict(fn_reasons),
        "fp_total_ms": sum(fp_ms.values()),
        "fn_total_ms": sum(fn_ms.values()),
        "disagreements": disagreements,
    }


def main():
    parser = argparse.ArgumentParser(description="Evaluate subtitle-cut against ground truth")
    parser.add_argument("--avid-json", required=True, help="Path to avid.json with AI edit decisions")
    parser.add_argument("--ground-truth", required=True, help="Path to eval_segments.json (human ground truth)")
    parser.add_argument("--output", "-o", help="Output JSON path (default: stdout)")
    parser.add_argument("--append-tracking", help="Append result to JSONL tracking file")
    parser.add_argument("--run-label", default="", help="Label for this run (e.g. git commit hash)")
    parser.add_argument("--elapsed-seconds", type=float, default=0, help="Elapsed time for this run")
    args = parser.parse_args()

    result = evaluate(args.avid_json, args.ground_truth)

    if args.run_label:
        result["run_label"] = args.run_label
    if args.elapsed_seconds:
        result["elapsed_seconds"] = args.elapsed_seconds
    result["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%S")

    # Output
    result_json = json.dumps(result, ensure_ascii=False, indent=2)

    if args.output:
        Path(args.output).write_text(result_json, encoding="utf-8")
        print(f"Results written to {args.output}", file=sys.stderr)
    else:
        print(result_json)

    # Append to tracking file
    if args.append_tracking:
        tracking_line = json.dumps(result, ensure_ascii=False)
        with open(args.append_tracking, "a", encoding="utf-8") as f:
            f.write(tracking_line + "\n")
        print(f"Appended to tracking: {args.append_tracking}", file=sys.stderr)

    # Print summary to stderr
    m = result["metrics"]
    cm = result["confusion_matrix"]
    print(f"\n=== Eval Summary ===", file=sys.stderr)
    print(f"Accuracy: {m['accuracy']:.1%}  Precision: {m['precision']:.1%}  Recall: {m['recall']:.1%}  F1: {m['f1']:.1%}", file=sys.stderr)
    print(f"TP={cm['tp']} TN={cm['tn']} FP={cm['fp']} FN={cm['fn']}  Errors={result['total_errors']}", file=sys.stderr)
    if result["fp_reasons"]:
        print(f"FP reasons: {result['fp_reasons']}", file=sys.stderr)
    if result["fn_reasons"]:
        print(f"FN reasons: {result['fn_reasons']}", file=sys.stderr)

    # Exit code: 0 if F1 >= 0.99, 1 otherwise
    sys.exit(0 if m["f1"] >= 0.99 else 1)


if __name__ == "__main__":
    main()
