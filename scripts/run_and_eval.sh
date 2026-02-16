#!/bin/bash
# Run subtitle-cut and evaluate against ground truth.
# Usage: ./run_and_eval.sh [output_label]
#
# Prerequisites:
#   - Source files at /tmp/eogum/22200e46/
#   - Ground truth at /tmp/eogum/eval_segments.json
#   - avid CLI at /home/jonhpark/workspace/auto-video-edit

set -euo pipefail

LABEL="${1:-$(date +%Y%m%d_%H%M%S)}"
AVID_DIR="/home/jonhpark/workspace/auto-video-edit"
SCRIPTS_DIR="$AVID_DIR/scripts"
SOURCE_DIR="/tmp/eogum/22200e46"
OUTPUT_DIR="$SOURCE_DIR/output_ralph_${LABEL}"
GROUND_TRUTH="/tmp/eogum/eval_segments.json"
TRACKING_FILE="$SCRIPTS_DIR/eval_tracking.jsonl"

mkdir -p "$OUTPUT_DIR"

echo "=== Run subtitle-cut (label: $LABEL) ==="
START_TIME=$(date +%s.%N)

cd "$AVID_DIR"
PYTHONPATH=apps/backend/src python3 -m avid.cli subtitle-cut \
    "$SOURCE_DIR/source.mp4" \
    --srt "$SOURCE_DIR/source.srt" \
    --context "$SOURCE_DIR/source.storyline.json" \
    -d "$OUTPUT_DIR" \
    2>&1

END_TIME=$(date +%s.%N)
ELAPSED=$(echo "$END_TIME - $START_TIME" | bc)

AVID_JSON="$OUTPUT_DIR/source_subtitle_cut.avid.json"

if [ ! -f "$AVID_JSON" ]; then
    echo "ERROR: avid.json not generated at $AVID_JSON"
    exit 1
fi

echo ""
echo "=== Evaluate (elapsed: ${ELAPSED}s) ==="

GIT_HASH=$(cd "$AVID_DIR" && git rev-parse --short HEAD)

python3 "$SCRIPTS_DIR/eval_subtitle_cut.py" \
    --avid-json "$AVID_JSON" \
    --ground-truth "$GROUND_TRUTH" \
    --output "$OUTPUT_DIR/eval_result.json" \
    --append-tracking "$TRACKING_FILE" \
    --run-label "${LABEL}_${GIT_HASH}" \
    --elapsed-seconds "$ELAPSED" \
    2>&1

echo ""
echo "=== Results ==="
echo "Output: $OUTPUT_DIR"
echo "Eval: $OUTPUT_DIR/eval_result.json"
echo "Tracking: $TRACKING_FILE"
echo "Elapsed: ${ELAPSED}s"
