---
name: detect-silence
description: |
  Detect silent sections in audio/video files using FFmpeg and optionally SRT transcripts.
  Use when user wants to find silence, remove gaps, or analyze audio for editing.
  Supports multiple detection modes: FFmpeg only, SRT gaps only, AND (both agree), OR (either), DIFF (disagreements).
argument-hint: [media-file] [--srt file.srt] [--mode and|or|diff]
disable-model-invocation: false
user-invocable: true
allowed-tools: Bash, Read, Write, Glob
---

# Silence Detection Tool

Detect silent sections in audio or video files using FFmpeg's silencedetect filter,
optionally combined with SRT transcript gap analysis.

## Requirements

- Python 3.11+
- FFmpeg (system package)
- pydantic (`pip install pydantic`)

## Quick Start

```bash
python /home/notorioush2/auto-video-edit/.claude/skills/detect-silence/scripts/detect_silence.py $ARGUMENTS
```

## Usage Examples

### Basic detection (FFmpeg only)
```
/detect-silence video.mp4
```

### With SRT comparison (AND mode - conservative)
```
/detect-silence video.mp4 --srt subtitles.srt --mode and
```

### Aggressive detection (OR mode)
```
/detect-silence video.mp4 --srt subtitles.srt --mode or
```

### Find disagreements for manual review (DIFF mode)
```
/detect-silence video.mp4 --srt subtitles.srt --mode diff
```

### Custom thresholds
```
/detect-silence audio.wav --threshold -35 --min-duration 300 --padding 150
```

## Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--threshold` | `-40` dB | Silence volume threshold |
| `--min-duration` | `500` ms | Minimum silence length |
| `--padding` | `100` ms | Margin before/after speech |
| `--srt` | None | SRT file for gap-based detection |
| `--mode` | `ffmpeg` | Combine mode: `ffmpeg`, `srt`, `and`, `or`, `diff` |
| `--output` | `silence_result.json` | Output filename |

## Detection Modes

- **ffmpeg**: FFmpeg silencedetect only (default)
- **srt**: SRT gaps only (requires --srt)
- **and**: Both FFmpeg AND SRT agree (conservative, high confidence)
- **or**: Either FFmpeg OR SRT detects (aggressive, catches more)
- **diff**: Show disagreements only (for manual review)

## Output

The script generates:
- **JSON file**: Machine-readable silence regions with metadata
- **Console report**: Human-readable summary with statistics

## Output Format

The JSON output can be used for further processing:

```python
import json

with open("silence_result.json") as f:
    result = json.load(f)

# Access silence regions
for region in result['silence_regions']:
    print(f"{region['start_ms']}ms - {region['end_ms']}ms ({region['source']})")

# Statistics
print(f"Total silence: {result['statistics']['silence_percent']}%")
```
