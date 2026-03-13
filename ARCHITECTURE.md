# AVID 아키텍처

> Stable CLI boundary: [apps/backend/CLI_INTERFACE.md](apps/backend/CLI_INTERFACE.md)
> Testing plan: [apps/backend/TESTING.md](apps/backend/TESTING.md)
> Last updated: 2026-03-13


## 시스템 개요

```
┌──────────────────────────────────────────────────────────────┐
│                        CLI (avid-cli)                         │
│ transcribe │ transcript-overview │ subtitle-cut │ podcast-cut │
│ review-segments │ apply-evaluation │ rebuild-multicam │ clear-extra-sources │ export-project │
│ reexport (deprecated) │ version │ doctor │
└──────┬───────────────┬──────────────────┬────────────────┬───┘
       │               │                  │                │
       ▼               ▼                  ▼                ▼
┌──────────────────────────────────────────────────────────────┐
│                     Service Layer                             │
│  ChalnaTranscription │ TranscriptOverview │ SubtitleCut      │
│  PodcastCut │ AudioSync │ ProjectPatch │ Export │ Media      │
└──────┬───────────────┬──────────────────┬────────────────┬───┘
       │               │                  │                │
       ▼               ▼                  ▼                ▼
┌─────────────┐ ┌─────────────────────────────────────┐ ┌──────────┐
│  Chalna API │ │         Skills (subprocess)          │ │  FFmpeg  │
│  (HTTP)     │ │  transcript-overview                 │ │ FFprobe  │
│             │ │  subtitle-cut                        │ │          │
│             │ │  podcast-cut                         │ │          │
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
├── cli.py                  # CLI 진입점 (초기 처리 + 후처리 + 운영 명령)
├── main.py                 # FastAPI 앱 (현재 /health만)
├── config.py               # 설정 (host, port, dirs)
├── provider_runtime.py     # Claude/Codex 기본 모델/effort 및 probe 로직
├── services/               # 비즈니스 로직
│   ├── transcription.py    # ChalnaTranscriptionService
│   ├── transcript_overview.py  # TranscriptOverviewService
│   ├── subtitle_cut.py     # SubtitleCutService
│   ├── podcast_cut.py      # PodcastCutService
│   ├── media.py            # MediaService (ffprobe)
│   └── audio_sync.py       # AudioSyncService (멀티소스 오디오 싱크)
├── models/                 # Pydantic 데이터 모델
│   ├── timeline.py         # EditType, EditReason, TimeRange, EditDecision
│   ├── project.py          # Project, Transcription, TranscriptSegment
│   ├── media.py            # MediaFile, MediaInfo
│   └── track.py            # Track, TrackType
└── export/                 # 내보내기
    ├── fcpxml.py           # FCPXMLExporter
    ├── premiere.py         # PremiereXMLExporter (TODO: Premiere Pro 지원)
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
SRT 갭(≥500ms)에서 무음 구간도 감지하여 Project에 병합.

### PodcastCutService (Pass 2 — 팟캐스트)

`skills/podcast-cut/main.py`를 subprocess로 실행.
SRT 없으면 Chalna로 자동 전사. entertainment_score 기반 편집.
SRT 갭(≥500ms)에서 무음 구간도 감지하여 Project에 병합.

### MediaService

FFprobe wrapper. duration, resolution, fps, sample_rate 추출.

### AudioSyncService (멀티소스)

`audio-offset-finder`(BBC, MFCC 교차상관)를 사용하여 추가 소스의 시간 오프셋을 자동 검출.

- `find_offset(main, extra)` → `SyncResult(offset_ms, confidence, method)`
- `add_extra_sources(project, main, extras, manual_offsets)` → 프로젝트에 소스 추가 + offset 설정
- 영상 입력 시 자동으로 오디오 추출 (temp WAV)
- 수동 오프셋 지원 (`manual_offsets` dict)
- 선택 의존성: `pip install 'avid[sync]'`

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
def call_claude(prompt, timeout=300, model=None, effort=None):
    return run_provider_prompt(
        "claude",
        prompt,
        timeout=timeout,
        model=model,
        effort=effort,
    )

def call_codex(prompt, timeout=300, model=None, effort=None):
    return run_provider_prompt(
        "codex",
        prompt,
        timeout=timeout,
        model=model,
        effort=effort,
    )
```

provider 기본 프로필과 `doctor --probe-providers` 동작은 `apps/backend/PROVIDER_RUNTIME_SPEC.md`를 기준으로 한다.

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

## 실제 End-to-End 워크플로우

`avid` 의 실제 운영 경로는 아래 순서를 따른다.

```
source media
  └─→ transcribe
        └─→ transcript-overview
              └─→ subtitle-cut / podcast-cut
                    └─→ review-segments
                          └─→ apply-evaluation
                                └─→ rebuild-multicam
                                      └─→ export-project
                                            └─→ FCPXML + adjusted SRT
```

의미:
- `transcribe` 부터 `subtitle-cut` / `podcast-cut` 까지가 초기 편집 단계다.
- `review-segments` 는 엔진이 직접 review payload 를 만들어 다른 UI 도 같은 shape 를 그대로 쓸 수 있게 한다.
- `apply-evaluation` 은 사람이 평가한 keep/cut 결정을 기존 `edit_decisions` 위에 덮어쓴다.
- `rebuild-multicam` 은 기존 extra source 를 다시 구성한다.
- `clear-extra-sources` 는 유지보수용 명령이며, 기본 workflow 단계는 아니다.
- `export-project` 가 최종 FCPXML / adjusted SRT 생성을 담당한다.
- `reexport` 는 위 단계를 한 번에 감싼 deprecated compatibility command 다.

---

## Two-Pass 초기 편집 단계

```
SRT ──→ [Pass 1: transcript-overview] ──storyline.json──→ [Pass 2: subtitle-cut / podcast-cut] ──→ Project
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
> FCPXML 최종 생성은 이제 `subtitle-cut` / `podcast-cut` 내부 출력만이 아니라 `export-project` 단계까지 포함한 broader workflow 로 이해하는 것이 맞다.

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
                  └─ Project + 초기 FCPXML + SRT 출력
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
                    └─ Project + 초기 FCPXML + SRT + Report 출력
```

### 후처리 데이터 흐름

```
project.avid.json
  ├─→ apply-evaluation → eval-applied.project.avid.json
  ├─→ rebuild-multicam → multicam.project.avid.json
  ├─→ clear-extra-sources → cleared.project.avid.json
  └─→ export-project → final FCPXML + adjusted SRT
```

후처리 명령의 역할:
- `apply-evaluation`: human keep/cut override 를 기존 `edit_decisions` 에 반영
- `rebuild-multicam`: 기존 extra source 를 제거한 뒤 새 extra source / manual offset 을 project 에 반영
- `clear-extra-sources`: 기존 extra source 제거만 수행
- `export-project`: 저장된 project JSON 기준으로 최종 산출물 생성

### 멀티소스 데이터 흐름

```
main.mp4 + cam2.mp4 + mic.wav ──→ PodcastCutService / SubtitleCutService
                                      ├─ 단일 소스 분석 (기존 흐름)
                                      ├─ AudioSyncService.add_extra_sources()
                                      │    ├─ find_offset(main, cam2) → offset_ms=1500
                                      │    ├─ find_offset(main, mic) → offset_ms=800
                                      │    └─ project.add_source_file() + set_track_offset()
                                      └─ FCPXMLExporter
                                           ├─ _get_extra_source_tracks() → (track, media, lane) 목록
                                           └─ _add_connected_clips() → 각 asset-clip에 자식 추가
```

FCPXML 구조:
```xml
<spine>
  <asset-clip ref="main" duration="..." start="...">
    <asset-clip ref="cam2" lane="-1" offset="..." start="..." />
    <asset-clip ref="mic"  lane="-2" offset="..." start="..." />
  </asset-clip>
</spine>
```

---

## FCPXML 내보내기

`FCPXMLExporter`는 Project의 EditDecision을 FCPXML 타임라인으로 변환.

두 가지 모드:
- **review** (기본): silence=cut, content=disabled → FCP에서 비활성 상태로 리뷰
- **final** (`--final`): silence=cut, content=cut → 모든 편집 적용

CONTENT_REASONS (content_mode 적용 대상):
- 강의: DUPLICATE, FILLER, INCOMPLETE, FUMBLE
- 팟캐스트: BORING, TANGENT, REPETITIVE, LONG_PAUSE, CROSSTALK, IRRELEVANT, DRAGGING, META_COMMENT

`merge_short_gaps_ms` (기본 500ms): disabled 구간 사이의 짧은 갭도 disabled로 병합.

---

## TODO 모듈

| 모듈 | 위치 | 상태 |
|------|------|------|
| PremiereXMLExporter | `export/premiere.py` | 구현 완료, CLI 미노출. Premiere Pro 지원 시 연결 예정. |
| mc-clip 멀티캠 | `export/fcpxml.py` | Phase 2 예정. 현재는 connected clip(lane 기반), 앵글 전환은 미구현. |
