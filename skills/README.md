# Skills

영상 편집 워크플로우를 위한 AI 스킬 모음. Claude CLI 또는 Codex CLI로 호출할 수 있는 모듈형 도구.

## Two-Pass 편집 워크플로우

프로 편집자의 "Paper Edit" 워크플로우를 자동화한 Two-Pass 구조:

```
SRT ──→ [Pass 1: transcript-overview] ──storyline.json──→ [Pass 2: subtitle-cut 또는 podcast-cut] ──→ Project JSON
```

**Pass 1** (transcript-overview): 전체 자막을 읽고 스토리 구조, 챕터, 의존성, 핵심 순간을 분석
**Pass 2** (subtitle-cut / podcast-cut): Pass 1 결과를 context로 받아 맥락을 알고 편집 결정

이를 통해: setup을 자르면 payoff가 의미 없어지는 문제, callback anchor 소실, Q&A 쌍 분리 등을 방지한다.

```bash
# Two-Pass 실행 예시
cd skills/transcript-overview
python main.py test.srt -o test.storyline.json

cd ../subtitle-cut
python main.py test.srt test.mp4 --context test.storyline.json
```

> Pass 2 스킬은 `--context` 없이도 기존처럼 독립 동작한다 (하위 호환).

## Available Skills

### transcript-overview (스토리 구조 분석, Pass 1)

전체 자막을 분석하여 스토리 구조(narrative arc, chapters, key moments, dependencies)를 파악한다.
Pass 2 스킬의 컨텍스트로 사용할 `storyline.json`을 생성한다.

**Usage:**
```bash
cd skills/transcript-overview
python main.py <srt_file> [options]
```

**Options:**
- `--output, -o` — 출력 경로 (default: `<srt_stem>.storyline.json`)
- `--content-type {lecture,podcast,auto}` — 콘텐츠 유형 (default: auto)

**출력**: `storyline.json` — 챕터, 의존성, 핵심 순간, 페이싱 메모 포함.

세그먼트 수에 따라 적응적 처리:
- ≤150: 전체 전송 / 151-400: 압축 형태 / 400+: 2단계 (챕터 경계 → 상세 분석)

See `transcript-overview/SKILL.md` for detailed documentation.

### subtitle-cut (강의/설명 영상)

단일 화자 강의/설명 영상에서 불필요한 구간(중복 발화, 필러, 말실수, 미완성 문장)을 감지하여 편집 결정을 생성한다.
**목표**: 정보 효율성 — 같은 내용의 반복을 제거하고 베스트 테이크만 남긴다.

**Usage:**
```bash
cd skills/subtitle-cut
python main.py <srt_file> <video_file> [options]
```

**Options:**
- `--provider {claude,codex}` - AI provider (default: claude)
- `--edit-type {disabled,cut}` - Edit type for content (default: disabled)
- `--keep-alternatives` - Keep alternative takes for review
- `--context <path>` - storyline.json from Pass 1 (optional)
- `--report-only` - Only print report, don't save

**CUT reasons**: `duplicate`, `incomplete`, `filler`, `fumble`
**KEEP reasons**: `best_take`, `unique`

See `subtitle-cut/SKILL.md` for detailed documentation.

### podcast-cut (팟캐스트/인터뷰)

멀티 화자 팟캐스트/인터뷰에서 재미없는 구간을 감지하여 편집 결정을 생성한다.
**목표**: 재미/몰입 유지 — 지루한 구간을 제거하고 유머/케미/클라이맥스를 보존한다.

**Usage:**
```bash
cd skills/podcast-cut
python main.py <srt_file> <video_file> [options]
```

**Options:**
- `--edit-type {disabled,cut}` - Edit type for content (default: disabled)
- `--min-score <int>` - Minimum entertainment score to keep (default: 4)
- `--context <path>` - storyline.json from Pass 1 (optional)
- `--report-only` - Only print report, don't save

**CUT reasons**: `boring`, `tangent`, `repetitive`, `long_pause`, `crosstalk`, `irrelevant`, `filler`
**KEEP reasons**: `funny`, `witty`, `chemistry`, `reaction`, `callback`, `climax`, `engaging`, `emotional`

각 세그먼트에 `entertainment_score` (1-10)를 부여하여 재미 정도를 정량화한다.

### _common (공통 모듈)

모든 스킬이 공유하는 유틸리티 모듈:

- **srt_parser.py** — SRT 파싱 (`SubtitleSegment`, `parse_srt`, `parse_srt_file`)
- **video_info.py** — ffprobe 기반 비디오 메타데이터 추출
- **cli_utils.py** — `call_claude()`, `call_codex()`, `parse_json_response()`
- **base_models.py** — `AnalysisResult` 공통 데이터 모델
- **context_utils.py** — Two-Pass 컨텍스트 유틸 (`load_storyline`, `format_context_for_prompt`, `filter_context_for_range`)

## 어떤 스킬을 사용해야 하나?

| 영상 유형 | 추천 스킬 | 이유 |
|-----------|----------|------|
| 강의, 튜토리얼, 설명 | `subtitle-cut` | 같은 내용 반복 제거, 베스트 테이크 선택 |
| 팟캐스트, 인터뷰, 대담 | `podcast-cut` | 지루한 구간 제거, 재미있는 순간 보존 |
| 1인 촬영 | `subtitle-cut` | 테이크 반복이 주요 편집 대상 |
| 다인 대화 | `podcast-cut` | 대화 흐름과 케미가 중요 |

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
# Use --provider codex option when running skills (subtitle-cut only)
python skills/subtitle-cut/main.py input.srt video.mp4 --provider codex
```

## Skill Structure

```
skills/
├── _common/                   # 공통 모듈 (SRT 파서, CLI 유틸 등)
│   ├── __init__.py
│   ├── srt_parser.py
│   ├── video_info.py
│   ├── cli_utils.py
│   ├── base_models.py
│   └── context_utils.py       # Two-Pass 컨텍스트 유틸
├── transcript-overview/       # Pass 1: 스토리 구조 분석
│   ├── SKILL.md
│   ├── main.py                # Entry point
│   ├── claude_analyzer.py
│   ├── models.py
│   └── __init__.py
├── subtitle-cut/              # Pass 2: 강의/설명 영상 편집
│   ├── SKILL.md
│   ├── main.py                # Entry point (--context 지원)
│   ├── claude_analyzer.py
│   ├── codex_analyzer.py
│   └── models.py
└── podcast-cut/               # Pass 2: 팟캐스트/인터뷰 편집
    ├── main.py                # Entry point (--context 지원)
    ├── claude_analyzer.py
    └── models.py
```

## Integration with Backend

스킬은 백엔드 서비스에서 subprocess로 호출되거나, 서비스가 직접 Claude CLI를 호출:

```python
# transcript-overview: TranscriptOverviewService가 main.py를 subprocess로 실행
from avid.services.transcript_overview import TranscriptOverviewService

# subtitle-cut: SubtitleCutService가 main.py를 subprocess로 실행
from avid.services.subtitle_cut import SubtitleCutService

# podcast-cut: PodcastCutService가 직접 Claude CLI 호출
from avid.services.podcast_cut import PodcastCutService
```

CLI에서도 직접 사용 가능:
```bash
# Two-Pass 워크플로우
avid-cli transcript-overview <srt> [-o storyline.json]
avid-cli subtitle-cut <video> --srt sub.srt --context storyline.json [-o output.fcpxml]
avid-cli podcast-cut <audio> --srt sub.srt --context storyline.json [-d output_dir] [--final]

# 단독 실행 (하위 호환)
avid-cli subtitle-cut <video> --srt sub.srt [-o output.fcpxml]
avid-cli podcast-cut <audio> [--srt sub.srt] [-d output_dir] [--final]
```
