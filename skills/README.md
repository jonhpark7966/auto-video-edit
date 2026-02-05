# Skills

This directory contains skills for the auto-video-edit workflow. Skills are modular AI-powered tools that can be invoked via Claude CLI or Codex CLI.

## Available Skills

### subtitle-cut

Analyze SRT subtitle files to detect unnecessary segments (duplicates, fumbles, incomplete sentences) and generate automatic cut editing decisions.

**Usage:**
```bash
cd skills/subtitle-cut
python main.py <srt_file> <video_file> [options]
```

**Options:**
- `--provider {claude,codex}` - AI provider (default: claude)
- `--edit-type {disabled,cut}` - Edit type for content (default: disabled)
- `--keep-alternatives` - Keep alternative takes for review
- `--report-only` - Only print report, don't save

See `subtitle-cut/SKILL.md` for detailed documentation.

## Installing Skills for Claude CLI

Skills can be registered with Claude CLI for direct invocation:

```bash
# Navigate to the skills directory
cd /path/to/auto-video-edit/skills

# Use as a Claude plugin (if using claude-code with plugins)
# Add to your .claude/plugins.json
```

## Installing Skills for Codex CLI

```bash
# Use --provider codex option when running skills
python skills/subtitle-cut/main.py input.srt video.mp4 --provider codex
```

## Skill Structure

Each skill follows this structure:

```
skills/
└── <skill-name>/
    ├── SKILL.md           # Skill definition (Claude/Codex compatible)
    ├── main.py            # Entry point
    ├── __init__.py        # Python module exports
    └── *.py               # Additional modules
```

## Integration with Pipeline

Skills are integrated into the avid pipeline as stages:

```python
from avid.pipeline.stages.subtitle_cut import SubtitleCutStage

# Pipeline with skill integration
stages = [
    TranscriptionStage(),
    SilenceStage(),
    SubtitleCutStage(),  # Uses subtitle-cut skill
]
```
