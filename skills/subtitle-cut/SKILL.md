---
name: subtitle-cut
description: |
  Analyze SRT subtitle files to detect unnecessary segments (duplicates, fumbles, incomplete sentences)
  and generate automatic cut editing decisions for video editing workflows.
  Supports both Claude CLI and Codex CLI as AI providers.
  Use when user wants to detect repeated takes, hesitations, or incomplete speech segments.
argument-hint: <srt_file> <video_file> [--provider {claude,codex}] [--edit-type {disabled,cut}]
disable-model-invocation: false
user-invocable: true
allowed-tools: Bash, Read, Write, Glob
---

# Subtitle Cut Detector

Analyze SRT subtitle files to detect unnecessary segments and generate automated cut decisions for video editing.

## Requirements

- Python 3.11+
- Claude CLI (`claude`) or Codex CLI (`codex`)
- Optional: ffprobe (for video metadata extraction)

## Quick Start

```bash
cd ${CLAUDE_PLUGIN_ROOT}/skills/subtitle-cut
python main.py $ARGUMENTS
```

## Usage Examples

### Basic detection with Claude (default)
```
/subtitle-cut video.srt video.mp4
```

### Use Codex CLI instead
```
/subtitle-cut video.srt video.mp4 --provider codex
```

### Auto-cut content segments (instead of disabled)
```
/subtitle-cut video.srt video.mp4 --edit-type cut
```

### Keep alternative takes for user review
```
/subtitle-cut video.srt video.mp4 --keep-alternatives
```

### Report only (no output file)
```
/subtitle-cut video.srt video.mp4 --report-only
```

## Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `srt_file` | Required | Path to SRT subtitle file |
| `video_file` | Required | Path to original video file |
| `--provider` | `claude` | AI provider: `claude` or `codex` |
| `--edit-type` | `disabled` | Edit type: `disabled` (review in FCP) or `cut` (auto-cut) |
| `--keep-alternatives` | false | Keep good alternative takes for user selection |
| `--output` | `<srt_name>.avid.json` | Output project JSON path |
| `--report-only` | false | Only print analysis report, don't save project |

## Detection Types

### 1. Duplicates
Detects when the same content is said multiple times:
- Groups by semantic similarity
- Auto-selects best take based on:
  - Sentence completeness
  - Content completeness
  - Natural delivery

### 2. Fumbles/False Starts
Detects hesitations and restarts:
- Segments shorter than 2 seconds with less than 10 characters
- Immediate restarts after short segments

### 3. Incomplete Sentences
Detects sentences cut mid-speech:
- Endings with particles or connectors
- Trailing conjunctions

## Output

### Project JSON (`.avid.json`)
Generates project JSON compatible with auto-video-edit workflows:
- Contains edit decisions in `edit_decisions`
- Includes `note` field with detailed reasoning for each decision
- Reasons: "duplicate" or "filler"
- Can be exported to FCPXML

### Analysis Report
- Total segment count
- Cut/keep decisions with detailed notes
- Items requiring user selection
- Detailed explanation for each decision

## Edit Type Modes

### `--edit-type disabled` (Default)
- Content segments are marked as DISABLED in FCPXML
- User can review in Final Cut Pro before making final cuts
- Recommended for careful editing

### `--edit-type cut`
- Content segments are directly CUT
- Faster workflow for trusted AI decisions
- Use with caution

## Integration with auto-video-edit

This skill integrates with the auto-video-edit pipeline:

```python
from avid.pipeline.stages.subtitle_cut import SubtitleCutStage

# In pipeline configuration
stages = [
    TranscriptionStage(),
    SilenceStage(),
    SubtitleCutStage(),  # Uses this skill
]
```
