# AVID — 자동 영상 편집 스펙

## 한 줄 요약

영상의 불필요한 발화와 SRT 자막 갭(무음)을 자동 감지하여 Final Cut Pro용 편집 타임라인(FCPXML)을 생성하는 CLI 도구.

---

## CLI 명령어 (API)

모든 기능은 `avid-cli` 명령어로 접근한다.

### transcribe — 음성 인식

Chalna API로 오디오를 전사하여 SRT 자막을 생성한다.

```
avid-cli transcribe <video|audio> [-l LANG] [--chalna-url URL] [-d OUTPUT_DIR]
```

| 파라미터 | 기본값 | 설명 |
|----------|--------|------|
| `input` | (필수) | 영상/오디오 파일 |
| `-l, --language` | `ko` | 언어 코드 |
| `--chalna-url` | `http://localhost:7861` | Chalna API URL (env: `CHALNA_API_URL`) |
| `-d, --output-dir` | 입력 파일 위치 | 출력 디렉토리 |

**출력**: `{stem}.srt`

---

### transcript-overview — 스토리 구조 분석 (Pass 1)

전체 자막을 분석하여 내러티브 구조, 챕터, 의존성, 핵심 순간을 파악한다.
Pass 2 스킬의 컨텍스트(`--context`)로 사용할 `storyline.json`을 생성한다.

```
avid-cli transcript-overview <srt> [-o OUTPUT] [--content-type TYPE] [--provider PROVIDER]
```

| 파라미터 | 기본값 | 설명 |
|----------|--------|------|
| `input` | (필수) | SRT 자막 파일 |
| `-o, --output` | `{stem}.storyline.json` | 출력 경로 |
| `--content-type` | `auto` | `lecture` / `podcast` / `auto` |
| `--provider` | `codex` | `claude` / `codex` |

**출력**: `storyline.json`
```json
{
  "narrative_arc": "string",
  "chapters": [{ "title": "...", "segment_range": [1, 50], "summary": "..." }],
  "dependencies": [{ "setup": 10, "payoff": 45, "type": "..." }],
  "key_moments": [{ "segment_index": 30, "type": "climax", "description": "..." }],
  "pacing_notes": "string"
}
```

세그먼트 수에 따라 적응적 처리:
- ≤150: 전체 전송 단일 호출
- 151-400: 압축 형태
- 400+: 2단계 (챕터 경계 → 상세 분석)

---

### subtitle-cut — 강의/설명 영상 편집 (Pass 2)

단일 화자 강의/설명 영상에서 중복 발화, 필러, 말실수, 미완성 문장을 감지한다.

```
avid-cli subtitle-cut <video> --srt <srt> [--context <storyline.json>] [--provider PROVIDER] [-o OUTPUT] [-d OUTPUT_DIR] [--final] [--extra-source FILE] [--offset MS]
```

| 파라미터 | 기본값 | 설명 |
|----------|--------|------|
| `input` | (필수) | 영상 파일 |
| `--srt` | (필수) | SRT 자막 파일 |
| `--context` | (선택) | Pass 1의 storyline.json |
| `--provider` | `codex` | `claude` / `codex` |
| `-o, --output` | `{stem}_subtitle_cut.fcpxml` | FCPXML 출력 경로 |
| `-d, --output-dir` | 입력 파일 위치 | 출력 디렉토리 |
| `--final` | `false` | true면 content edit을 cut으로, false면 disabled로 |
| `--extra-source` | (선택, 반복) | 추가 소스 파일 (카메라, 마이크 등) |
| `--offset` | 자동 감지 | 수동 오프셋 ms (`--extra-source` 순서 대응) |

**출력**:
- `{stem}_subtitle_cut.fcpxml` — 편집 타임라인
- `{stem}_subtitle_cut.srt` — 조정된 자막
- `{stem}_subtitle_cut.avid.json` — 프로젝트 JSON

**CUT 이유**: `duplicate`, `incomplete`, `filler`, `fumble`
**KEEP 이유**: `best_take`, `unique`

세그먼트 수에 따라 적응적 처리:
- ≤150: 단일 호출, 3단계 프롬프트 (테이크 구분 → 판단 → 흐름 검토)
- &gt;150: 병렬 chunk 처리, 2단계 프롬프트 (흐름 검토 생략)

---

### podcast-cut — 팟캐스트/인터뷰 편집 (Pass 2)

멀티 화자 팟캐스트에서 재미없는 구간을 감지하고 하이라이트를 보존한다.

```
avid-cli podcast-cut <audio|video> [--srt <srt>] [--context <storyline.json>] [--provider PROVIDER] [-d OUTPUT_DIR] [--final] [--extra-source FILE] [--offset MS]
```

| 파라미터 | 기본값 | 설명 |
|----------|--------|------|
| `input` | (필수) | 오디오/영상 파일 |
| `--srt` | (선택) | SRT 자막 (없으면 Chalna로 자동 생성) |
| `--context` | (선택) | Pass 1의 storyline.json |
| `--provider` | `codex` | `claude` / `codex` |
| `-d, --output-dir` | 입력 파일 위치 | 출력 디렉토리 |
| `--final` | `false` | true면 content edit을 cut으로, false면 disabled로 |
| `--extra-source` | (선택, 반복) | 추가 소스 파일 (카메라, 마이크 등) |
| `--offset` | 자동 감지 | 수동 오프셋 ms (`--extra-source` 순서 대응) |

**출력**:
- `{stem}_podcast_cut.fcpxml` — 편집 타임라인
- `{stem}_podcast_cut.srt` — 조정된 자막
- `{stem}.report.md` — 편집 보고서
- `{stem}_podcast_cut.avid.json` — 프로젝트 JSON

**CUT 이유**: `boring`, `tangent`, `repetitive`, `long_pause`, `crosstalk`, `irrelevant`, `filler`, `dragging`
**KEEP 이유**: `funny`, `witty`, `chemistry`, `reaction`, `callback`, `climax`, `engaging`, `emotional`

각 세그먼트에 `entertainment_score` (1-10)를 부여한다.

세그먼트 수에 따라 적응적 처리:
- ≤80: 단일 호출
- &gt;80: 병렬 chunk 처리 (chunk_size=80, overlap=5)

---

## Two-Pass 편집 워크플로우

프로 편집자의 "Paper Edit" 워크플로우를 자동화한 구조.

```
SRT ──→ [Pass 1: transcript-overview] ──storyline.json──→ [Pass 2: subtitle-cut 또는 podcast-cut] ──→ FCPXML
```

**Pass 1**: 전체 자막을 읽고 스토리 구조, 챕터, 의존성, 핵심 순간을 분석
**Pass 2**: Pass 1 결과를 context로 받아 맥락을 알고 편집 결정

이를 통해 방지하는 문제:
- setup을 자르면 payoff가 의미 없어지는 문제
- callback anchor 소실
- Q&A 쌍 분리

> Pass 2 스킬은 `--context` 없이도 독립 동작한다 (하위 호환).

---

## 데이터 모델

### Project (프로젝트 JSON)

모든 편집 결과는 `.avid.json` 형식으로 저장된다.

```json
{
  "name": "project name",
  "created_at": "2026-02-07T12:00:00",
  "source_files": [{ "id": "uuid", "path": "/path/to/video.mp4", "info": { "duration_ms": 60000 } }],
  "tracks": [{ "id": "uuid_video", "source_file_id": "uuid", "track_type": "video" }],
  "transcription": {
    "source_track_id": "uuid_audio",
    "language": "ko",
    "segments": [{ "start_ms": 0, "end_ms": 3000, "text": "안녕하세요" }]
  },
  "edit_decisions": [
    { "range": { "start_ms": 5000, "end_ms": 8000 }, "edit_type": "cut", "reason": "duplicate", "confidence": 0.95 }
  ]
}
```

### EditType

| 값 | 설명 |
|----|------|
| `cut` | 구간 제거 |
| `speedup` | 구간 배속 |
| `mute` | 구간 음소거 |

### EditReason

| 카테고리 | 값 | 설명 |
|----------|-----|------|
| 공통 | `silence` | SRT 갭 기반 무음 구간 |
| 강의 (subtitle-cut) | `duplicate` | 이전 테이크 반복 |
| | `incomplete` | 미완성 문장 |
| | `filler` | 필러/잡담 |
| | `fumble` | 말실수 |
| 팟캐스트 CUT | `boring` | 지루한 구간 |
| | `tangent` | 주제 이탈 |
| | `repetitive` | 반복 |
| | `long_pause` | 긴 침묵 |
| | `crosstalk` | 동시 발화 |
| | `irrelevant` | 무관한 내용 |
| | `dragging` | 늘어짐 |
| 팟캐스트 KEEP | `funny` | 유머 |
| | `witty` | 재치 |
| | `chemistry` | 케미 |
| | `reaction` | 리액션 |
| | `callback` | 콜백 유머 |
| | `climax` | 클라이맥스 |
| | `engaging` | 몰입 |
| | `emotional` | 감정 |

---

## 내보내기 형식

### FCPXML (기본)

Final Cut Pro 호환 XML. 편집 모드에 따라 구간을 cut 또는 disabled 처리.

| 파라미터 | 설명 |
|----------|------|
| `silence_mode` | `cut` (제거) / `disabled` (비활성화) — SRT 갭 기반 무음 |
| `content_mode` | `cut` (제거) / `disabled` (비활성화) — AI 분석 기반 |
| `merge_short_gaps_ms` | 짧은 간격 병합 (기본 500ms) |

`--final` 플래그: content_mode를 `cut`으로 설정. 없으면 `disabled`(리뷰용).

### 편집 보고서

Markdown 형식. reason별 개수, 총 시간, 상세 목록을 포함한다.

---

## 멀티소스 지원

### Phase 1: 오디오 싱크 + Connected Clips

카메라 여러 대 + 별도 마이크를 `--extra-source`로 지정하면:

1. **오디오 싱크**: `audio-offset-finder`(MFCC 교차상관)로 메인 대비 오프셋 자동 검출 (~10ms 정확도)
2. **FCPXML 출력**: 추가 소스를 connected clip(lane 기반)으로 메인 타임라인에 연결

```xml
<spine>
  <asset-clip ref="r2" duration="50/1s" start="0s" name="main.mp4">
    <asset-clip ref="r3" lane="-1" offset="0s" duration="50/1s" start="1500/1000s"/>
    <asset-clip ref="r4" lane="-2" offset="0s" duration="50/1s" start="800/1000s"/>
  </asset-clip>
</spine>
```

- 수동 오프셋: `--offset` 플래그로 ms 단위 지정 (자동 감지 대체)
- `audio-offset-finder`는 선택 의존성: `pip install 'avid[sync]'`
- Phase 2 (미래): mc-clip 멀티캠 앵글 전환

### API 스키마 (멀티소스)

`SubtitleCutRequest`, `PodcastCutRequest`에 추가된 필드:
```json
{
  "extra_sources": ["/path/to/cam2.mp4", "/path/to/mic.wav"],
  "extra_offsets": {"cam2.mp4": 1500, "mic.wav": 800}
}
```

---

## 기술 결정 사항

| 항목 | 결정 |
|------|------|
| AI 호출 방식 | `claude` CLI / `codex` CLI (subprocess) — API SDK 아님 |
| 인증 | CLI 도구가 자체 처리 |
| AI 실패 시 | 에러 반환 (규칙 기반 fallback 없음) |
| 품질 원칙 | 정확도 > 속도 |
| 무음 감지 | SRT 자막 갭 분석 (FFmpeg 미사용) |
| 음성 인식 | Chalna API (비동기 폴링) |
| 내보내기 | FCPXML (Final Cut Pro) |
| 스킬 실행 | subprocess.run (package import 아님) |
| 대규모 처리 | ThreadPoolExecutor 병렬 chunk (max_workers=5) |

---

## 외부 의존성

| 서비스 | 용도 | 필수 여부 |
|--------|------|----------|
| `claude` CLI | AI 분석 (기본 provider) | 둘 중 하나 |
| `codex` CLI | AI 분석 (대체 provider) | 둘 중 하나 |
| Chalna API | 음성 인식 | podcast-cut 자동 전사 시 |
| FFmpeg / FFprobe | 오디오 추출, 미디어 메타데이터 | 필수 |
| `audio-offset-finder` | 멀티소스 오디오 싱크 (MFCC) | `--extra-source` 사용 시 |

---

## 제약 사항

- `claude` CLI 또는 `codex` CLI가 환경에 설치되어 있어야 함
- FFmpeg / FFprobe 필수 (오디오 추출, 미디어 메타데이터)
- 한국어 우선 (다국어 확장 가능)
- AI 실패 시 자동 대체 없음
