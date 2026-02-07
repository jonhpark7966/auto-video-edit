# AVID 아키텍처

## 시스템 개요

```
┌──────────────────────────────────────────────────────────────┐
│                        CLI (avid-cli)                         │
│  transcribe │ transcript-overview │ subtitle-cut │ podcast-cut │ silence │ eval  │
└──────┬───────────────┬──────────────────┬────────────────┬───┘
       │               │                  │                │
       ▼               ▼                  ▼                ▼
┌──────────────────────────────────────────────────────────────┐
│                     Service Layer                             │
│  ChalnaTranscription │ TranscriptOverview │ SubtitleCut      │
│  PodcastCut │ SilenceDetection │ Media │ FCPXMLEvaluator     │
└──────┬───────────────┬──────────────────┬────────────────┬───┘
       │               │                  │                │
       ▼               ▼                  ▼                ▼
┌─────────────┐ ┌─────────────────────────────────────┐ ┌──────────┐
│  Chalna API │ │         Skills (subprocess)          │ │  FFmpeg  │
│  (HTTP)     │ │  transcript-overview                 │ │ FFprobe  │
│             │ │  subtitle-cut                        │ │          │
│             │ │  podcast-cut                         │ │          │
│             │ │  detect-silence                      │ │          │
└─────────────┘ └──────┬──────────────────────────────┘ └──────────┘
                       │
                       ▼
               ┌───────────────┐
               │  AI CLI Tools  │
               │  claude / codex│
               └───────────────┘
```

---

## 디렉토리 구조

```
apps/backend/src/avid/
├── cli.py                  # CLI 진입점 (6개 명령어)
├── main.py                 # FastAPI 앱 (현재 /health만)
├── config.py               # 설정 (host, port, dirs)
├── services/               # 비즈니스 로직
│   ├── transcription.py    # ChalnaTranscriptionService
│   ├── transcript_overview.py  # TranscriptOverviewService
│   ├── subtitle_cut.py     # SubtitleCutService
│   ├── podcast_cut.py      # PodcastCutService
│   ├── silence.py          # SilenceDetectionService
│   ├── media.py            # MediaService (ffprobe)
│   └── evaluation.py       # FCPXMLEvaluator
├── models/                 # Pydantic 데이터 모델
│   ├── timeline.py         # EditType, EditReason, TimeRange, EditDecision
│   ├── project.py          # Project, Transcription, TranscriptSegment
│   ├── media.py            # MediaFile, MediaInfo
│   ├── track.py            # Track, TrackType
│   └── pipeline.py         # StageResult, PipelineConfig
└── export/                 # 내보내기
    ├── fcpxml.py           # FCPXMLExporter
    ├── premiere.py         # PremiereXMLExporter
    └── report.py           # Markdown/JSON 보고서

skills/
├── _common/                # 공통 모듈
│   ├── srt_parser.py       # SubtitleSegment, parse_srt, parse_srt_file
│   ├── cli_utils.py        # call_claude(), call_codex(), parse_json_response()
│   ├── video_info.py       # ffprobe 기반 비디오 정보
│   ├── base_models.py      # AnalysisResult
│   ├── context_utils.py    # storyline 컨텍스트 포맷팅/필터링
│   └── parallel.py         # 병렬 chunk 처리기 (ThreadPoolExecutor)
├── transcript-overview/    # Pass 1
│   ├── main.py
│   ├── claude_analyzer.py
│   └── models.py
├── subtitle-cut/           # Pass 2 (강의)
│   ├── main.py
│   ├── claude_analyzer.py
│   ├── codex_analyzer.py
│   └── models.py
└── podcast-cut/            # Pass 2 (팟캐스트)
    ├── main.py
    ├── claude_analyzer.py
    ├── codex_analyzer.py
    └── models.py
```

---

## 서비스 계층

### ChalnaTranscriptionService

Chalna API를 통한 비동기 음성 인식.

- POST `/transcribe/async` → task_id 반환
- GET `/jobs/{task_id}` 폴링 (1초 간격, 최대 3600초)
- 결과를 `ChalnaResult` (segments + full_text)로 변환

### TranscriptOverviewService (Pass 1)

`skills/transcript-overview/main.py`를 subprocess로 실행.
SRT → `storyline.json` (narrative_arc, chapters, dependencies, key_moments).

### SubtitleCutService (Pass 2 — 강의)

`skills/subtitle-cut/main.py`를 subprocess로 실행.
SRT + 영상 → 편집 결정 (duplicate, incomplete, filler, fumble 감지).
무음 갭도 함께 감지하여 Project에 병합.

### PodcastCutService (Pass 2 — 팟캐스트)

`skills/podcast-cut/main.py`를 subprocess로 실행.
SRT 없으면 Chalna로 자동 전사. entertainment_score 기반 편집.

### SilenceDetectionService

`skills/detect-silence/scripts/detect_silence.py`를 subprocess로 실행.
FFmpeg silencedetect + SRT 갭 분석 결합.

### MediaService

FFprobe wrapper. duration, resolution, fps, sample_rate 추출.

### FCPXMLEvaluator

두 FCPXML의 kept clip 구간을 비교. precision, recall, F1, timeline_overlap_ratio 산출.

---

## 스킬 실행 모델

스킬은 **Python 패키지로 import하지 않는다**. `python main.py`를 subprocess로 실행.

```python
# 서비스에서 스킬 호출 패턴
script_dir = Path(__file__).parent / "../../skills/subtitle-cut"
result = subprocess.run(
    ["python", "main.py", str(srt_path), str(video_path), "--context", str(storyline_path)],
    cwd=script_dir,
    capture_output=True, text=True, timeout=1800,
)
```

스킬 내부에서 AI CLI 호출:
```python
# skills/_common/cli_utils.py
def call_claude(prompt, timeout=120):
    result = subprocess.run(
        ["claude", "-p", prompt, "--output-format", "text"],
        capture_output=True, text=True, timeout=timeout,
    )
    return result.stdout

def call_codex(prompt, timeout=120):
    result = subprocess.run(
        ["codex", "--quiet", "--approval-mode", "full-auto", "-p", prompt],
        capture_output=True, text=True, timeout=timeout,
    )
    return result.stdout
```

---

## 병렬 Chunk 처리

대규모 자막을 chunk로 분할하여 AI API를 병렬 호출.

```
segments ──→ [chunk 분할 (overlap 포함)] ──→ ThreadPoolExecutor ──→ [결과 병합 + dedup]
```

`skills/_common/parallel.py`:
- segments를 chunk_size로 분할 (chunk_overlap으로 겹침)
- `ThreadPoolExecutor(max_workers=5)`로 `analyze_fn` 병렬 호출
- chunk_num 순 정렬 후 segment_index 기준 중복 제거
- 실패 chunk은 skip, 나머지 계속 처리

| 스킬 | 단일 호출 | 병렬 처리 | chunk_size | overlap |
|------|-----------|-----------|------------|---------|
| subtitle-cut | ≤150 (3단계 프롬프트) | >150 (2단계) | 80 | 5 |
| podcast-cut | ≤80 | >80 | 80 | 5 |

---

## Two-Pass 아키텍처

```
SRT ──→ [Pass 1: transcript-overview] ──storyline.json──→ [Pass 2: subtitle-cut / podcast-cut] ──→ FCPXML
```

**Pass 1** — 전체 자막을 읽고 스토리 구조 분석:
- narrative_arc, chapters, dependencies, key_moments, pacing_notes
- 세그먼트 수에 따라 적응적 처리 (≤150 / 151-400 / 400+)

**Pass 2** — Pass 1 결과를 `--context`로 받아 편집 결정:
- subtitle-cut: ≤150이면 전체 context 주입, >150이면 chunk별 필터링
- podcast-cut: 항상 chunk별 필터링 (`filter_context_for_range`)

방지 효과:
- setup → payoff 쌍 보존
- callback anchor 유지
- Q&A 쌍 분리 방지

> `--context`는 선택 파라미터. Pass 2는 단독 실행도 가능 (하위 호환).

---

## 데이터 흐름

### subtitle-cut (강의 영상)

```
video + srt ──→ SubtitleCutService
                  ├─ skills/subtitle-cut/main.py (subprocess)
                  │    ├─ SRT 파싱 → segments
                  │    ├─ [≤150] 단일 Claude/Codex 호출 (3단계 프롬프트)
                  │    └─ [>150] 병렬 chunk 처리 (2단계 프롬프트)
                  ├─ SRT 갭에서 무음 감지
                  ├─ content + silence → EditDecision 병합
                  └─ Project + FCPXML + SRT 출력
```

### podcast-cut (팟캐스트)

```
audio [+ srt] ──→ PodcastCutService
                    ├─ [SRT 없으면] ChalnaTranscriptionService로 전사
                    ├─ skills/podcast-cut/main.py (subprocess)
                    │    ├─ SRT 파싱 → segments
                    │    ├─ [≤80] 단일 Claude/Codex 호출
                    │    └─ [>80] 병렬 chunk 처리
                    ├─ SRT 갭에서 무음 감지
                    ├─ content + silence → EditDecision 병합
                    └─ Project + FCPXML + SRT + Report 출력
```

---

## FCPXML 내보내기

`FCPXMLExporter`는 Project의 EditDecision을 FCPXML 타임라인으로 변환.

두 가지 모드:
- **review** (기본): silence=cut, content=disabled → FCP에서 비활성 상태로 리뷰
- **final** (`--final`): silence=cut, content=cut → 모든 편집 적용

CONTENT_REASONS (content_mode 적용 대상):
- 강의: DUPLICATE, FILLER, INCOMPLETE, FUMBLE
- 팟캐스트: BORING, TANGENT, REPETITIVE, LONG_PAUSE, CROSSTALK, IRRELEVANT, DRAGGING

`merge_short_gaps_ms` (기본 500ms): disabled 구간 사이의 짧은 갭도 disabled로 병합.

---

## 미사용 모듈

현재 코드에 존재하지만 CLI 워크플로우에서 사용되지 않는 모듈:

| 모듈 | 위치 | 상태 |
|------|------|------|
| Pipeline (executor, stages, context) | `pipeline/` | 스캐폴딩. CLI는 서비스를 직접 호출. |
| Gradio UI | `ui/app.py` | 독립 실행 가능하나 CLI와 통합되지 않음. |
| PremiereXMLExporter | `export/premiere.py` | 구현 완료, CLI에서 미노출. |
| Service interfaces | `services/interfaces.py` | Protocol 정의. 실제 서비스와 시그니처 불일치. |
