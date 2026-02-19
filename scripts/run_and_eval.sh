#!/bin/bash
# Run avid skill (subtitle-cut or podcast-cut) and evaluate against ground truth.
#
# Usage: ./run_and_eval.sh [output_label] [reasoning_effort]
#
# Arguments:
#   output_label       - Label for this run (default: timestamp)
#   reasoning_effort   - Codex reasoning effort: low/medium/high (default: medium)
#
# Environment variables (override defaults):
#   SKILL              - "subtitle-cut" or "podcast-cut" (default: subtitle-cut)
#   SOURCE_DIR         - Source directory (default: /tmp/eogum/22200e46)
#   SOURCE_FILE        - Source media filename (default: source.mp4)
#   SOURCE_SRT         - SRT filename (default: source.srt)
#   SOURCE_CONTEXT     - Storyline context filename, empty to skip (default: source.storyline.json)
#   GROUND_TRUTH       - Ground truth JSON path (default: /tmp/eogum/eval_segments.json)
#   TRACKING_FILE      - Tracking JSONL path (default: auto based on skill)

set -euo pipefail

LABEL="${1:-$(date +%Y%m%d_%H%M%S)}"
EFFORT="${2:-medium}"
AVID_DIR="/home/jonhpark/workspace/auto-video-edit"
SCRIPTS_DIR="$AVID_DIR/scripts"

# Configurable via env vars
SKILL="${SKILL:-subtitle-cut}"
SOURCE_DIR="${SOURCE_DIR:-/tmp/eogum/22200e46}"
SOURCE_FILE="${SOURCE_FILE:-source.mp4}"
SOURCE_SRT="${SOURCE_SRT:-source.srt}"
SOURCE_CONTEXT="${SOURCE_CONTEXT:-source.storyline.json}"
GROUND_TRUTH="${GROUND_TRUTH:-/tmp/eogum/eval_segments.json}"
TRACKING_FILE="${TRACKING_FILE:-$SCRIPTS_DIR/eval_tracking_${SKILL}.jsonl}"

OUTPUT_DIR="$SOURCE_DIR/output_ralph_${LABEL}"

export CODEX_REASONING_EFFORT="$EFFORT"

mkdir -p "$OUTPUT_DIR"

echo "=== Run $SKILL (label: $LABEL, effort: $EFFORT) ==="
echo "  Source: $SOURCE_DIR/$SOURCE_FILE"
echo "  SRT: $SOURCE_DIR/$SOURCE_SRT"
echo "  Ground truth: $GROUND_TRUTH"
START_TIME=$(date +%s.%N)

# Build CLI command
CLI_ARGS=(
    "$SOURCE_DIR/$SOURCE_FILE"
    --srt "$SOURCE_DIR/$SOURCE_SRT"
    -d "$OUTPUT_DIR"
)

# Add context if file exists
if [ -n "$SOURCE_CONTEXT" ] && [ -f "$SOURCE_DIR/$SOURCE_CONTEXT" ]; then
    CLI_ARGS+=(--context "$SOURCE_DIR/$SOURCE_CONTEXT")
    echo "  Context: $SOURCE_DIR/$SOURCE_CONTEXT"
fi

cd "$AVID_DIR"
PYTHONPATH=apps/backend/src python3 -m avid.cli "$SKILL" "${CLI_ARGS[@]}" 2>&1

END_TIME=$(date +%s.%N)
ELAPSED=$(echo "$END_TIME - $START_TIME" | bc)

# Find the generated avid.json (different naming per skill)
AVID_JSON=""
STEM="${SOURCE_FILE%.*}"
for pattern in \
    "$OUTPUT_DIR/${STEM}.podcast.avid.json" \
    "$OUTPUT_DIR/${STEM}_subtitle_cut.avid.json" \
    "$OUTPUT_DIR/${STEM}.avid.json"; do
    if [ -f "$pattern" ]; then
        AVID_JSON="$pattern"
        break
    fi
done

if [ -z "$AVID_JSON" ]; then
    echo "ERROR: No avid.json found in $OUTPUT_DIR"
    ls -la "$OUTPUT_DIR"/*.json 2>/dev/null || true
    exit 1
fi

echo ""
echo "=== Evaluate (elapsed: ${ELAPSED}s, effort: $EFFORT) ==="
echo "  avid.json: $AVID_JSON"

GIT_HASH=$(cd "$AVID_DIR" && git rev-parse --short HEAD)

python3 "$SCRIPTS_DIR/eval_subtitle_cut.py" \
    --avid-json "$AVID_JSON" \
    --ground-truth "$GROUND_TRUTH" \
    --output "$OUTPUT_DIR/eval_result.json" \
    --append-tracking "$TRACKING_FILE" \
    --run-label "${LABEL}_${GIT_HASH}_effort-${EFFORT}" \
    --elapsed-seconds "$ELAPSED" \
    2>&1

echo ""
echo "=== Results ==="
echo "Skill: $SKILL"
echo "Output: $OUTPUT_DIR"
echo "Eval: $OUTPUT_DIR/eval_result.json"
echo "Tracking: $TRACKING_FILE"
echo "Elapsed: ${ELAPSED}s"
echo "Effort: $EFFORT"
