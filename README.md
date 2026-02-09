# AVID — Auto Video Edit

영상의 불필요한 발화와 SRT 자막 갭(무음)을 자동 감지하여 Final Cut Pro용 편집 타임라인(FCPXML)을 생성하는 CLI 도구.

## 두 가지 편집 모드

| 모드 | 대상 | 목표 |
|------|------|------|
| **subtitle-cut** | 강의, 설명, 튜토리얼 | 정보 효율성 — 중복/필러/말실수 제거 |
| **podcast-cut** | 팟캐스트, 인터뷰 | 재미 유지 — 지루한 구간 제거, 하이라이트 보존 |

## Two-Pass 워크플로우

```
SRT ──→ [Pass 1: transcript-overview] ──storyline.json──→ [Pass 2: subtitle-cut / podcast-cut] ──→ FCPXML
```

Pass 1이 스토리 구조를 먼저 파악하여, Pass 2에서 setup-payoff 쌍이나 Q&A가 분리되는 것을 방지한다.

## 설치

```bash
cd apps/backend
pip install -e .
```

**사전 요구사항:**
- Python 3.11+
- FFmpeg / FFprobe
- `claude` CLI 또는 `codex` CLI (AI 분석용)
- Chalna API (음성 전사용, `transcribe` 명령 사용 시)

## CLI 워크플로우

### 팟캐스트 편집 (영상 → FCPXML)

영상 파일 하나에서 팟캐스트 편집본까지의 전체 흐름:

```bash
# 1) 음성 전사 — 영상에서 오디오를 추출하고 Chalna API로 SRT 생성
avid-cli transcribe podcast.mp4 -l ko

# 2) 스토리 분석 — SRT를 읽고 전체 흐름/챕터/의존성 파악 (storyline.json)
avid-cli transcript-overview podcast.srt --content-type podcast

# 3) 팟캐스트 컷 — 스토리 맥락을 참고하여 지루한/반복/탈선 구간 감지
avid-cli podcast-cut podcast.mp4 --srt podcast.srt --context podcast.storyline.json
```

출력물:
- `podcast.fcpxml` — Final Cut Pro 타임라인 (review 모드: 컷이 disabled 상태로 표시)
- `podcast.srt` — 편집 반영된 자막
- `podcast.report.md` — 편집 판단 근거 보고서
- `podcast.podcast.avid.json` — 프로젝트 메타데이터

### 강의 편집 (영상 → FCPXML)

```bash
# 1) 음성 전사
avid-cli transcribe lecture.mp4

# 2) 스토리 분석
avid-cli transcript-overview lecture.srt --content-type lecture

# 3) 자막 컷 — 중복 테이크/필러/말실수/미완성 문장 감지
avid-cli subtitle-cut lecture.mp4 --srt lecture.srt --context lecture.storyline.json
```

### 빠른 실행 (Pass 1 생략)

스토리 분석 없이 바로 편집할 수도 있다. 짧은 영상이거나 맥락 보존이 덜 중요할 때:

```bash
# SRT가 이미 있으면 바로 편집
avid-cli podcast-cut podcast.mp4 --srt podcast.srt
avid-cli subtitle-cut lecture.mp4 --srt lecture.srt

# podcast-cut은 SRT 없이도 가능 (내부에서 Chalna 전사)
avid-cli podcast-cut podcast.mp4
```

### review 모드 vs final 모드

기본은 **review 모드** — FCPXML에서 컷이 disabled 상태로 들어가서 Final Cut Pro에서 하나씩 확인할 수 있다.

```bash
# review 모드 (기본) — 컷을 disabled로 표시, FCP에서 검토
avid-cli podcast-cut podcast.mp4 --srt podcast.srt

# final 모드 — 모든 컷을 바로 적용
avid-cli podcast-cut podcast.mp4 --srt podcast.srt --final
```

## 명령어 레퍼런스

### `avid-cli transcribe`

영상/오디오 → SRT 자막 파일. 영상이면 ffmpeg으로 오디오 추출 후 Chalna API로 전사.

```
avid-cli transcribe <파일> [-l 언어] [--chalna-url URL] [-d 출력디렉토리]
```

| 옵션 | 기본값 | 설명 |
|------|--------|------|
| `-l, --language` | `ko` | 언어 코드 |
| `--chalna-url` | `$CHALNA_API_URL` 또는 `localhost:7861` | Chalna API 주소 |
| `-d, --output-dir` | 입력 파일과 같은 디렉토리 | 출력 디렉토리 |

### `avid-cli transcript-overview`

SRT → storyline.json. 전체 내러티브 구조를 분석하여 챕터, 의존성(setup-payoff), 핵심 순간을 추출.

```
avid-cli transcript-overview <srt> [-o 출력경로] [--content-type auto] [--provider codex]
```

| 옵션 | 기본값 | 설명 |
|------|--------|------|
| `-o, --output` | `{stem}.storyline.json` | 출력 JSON 경로 |
| `--content-type` | `auto` | `lecture` / `podcast` / `auto` |
| `--provider` | `codex` | AI 프로바이더 (`claude` 또는 `codex`) |

### `avid-cli subtitle-cut`

강의/튜토리얼 편집. 중복 테이크, 필러, 말실수, 미완성 문장을 감지.

```
avid-cli subtitle-cut <영상> --srt <srt> [--context storyline.json] [--provider codex] [-o 출력.fcpxml] [--final]
```

| 옵션 | 기본값 | 설명 |
|------|--------|------|
| `--srt` | (필수) | SRT 자막 파일 |
| `--context` | 없음 | storyline.json (Pass 1 결과) |
| `--provider` | `codex` | AI 프로바이더 |
| `-o, --output` | `{stem}_subtitle_cut.fcpxml` | 출력 FCPXML 경로 |
| `-d, --output-dir` | 영상과 같은 디렉토리 | 출력 디렉토리 |
| `--final` | review 모드 | 모든 편집 바로 적용 |

### `avid-cli podcast-cut`

팟캐스트/인터뷰 편집. 지루한/탈선/반복 구간을 감지하고, 재미있는 순간을 보존.

```
avid-cli podcast-cut <파일> [--srt <srt>] [--context storyline.json] [--provider codex] [-d 출력디렉토리] [--final]
```

| 옵션 | 기본값 | 설명 |
|------|--------|------|
| `--srt` | 없음 (Chalna로 자동 전사) | SRT 자막 파일 |
| `--context` | 없음 | storyline.json (Pass 1 결과) |
| `--provider` | `codex` | AI 프로바이더 |
| `-d, --output-dir` | 입력 파일과 같은 디렉토리 | 출력 디렉토리 |
| `--final` | review 모드 | 모든 편집 바로 적용 |

## 기술 스택

- **Backend**: Python 3.11+ / FastAPI
- **AI 분석**: `claude` CLI / `codex` CLI (subprocess)
- **음성 인식**: Chalna API
- **미디어 처리**: FFmpeg / FFprobe
- **내보내기**: FCPXML (Final Cut Pro)

## 프로젝트 구조

```
apps/backend/src/avid/
├── cli.py              # CLI 진입점 (4개 명령어)
├── services/           # 비즈니스 로직
├── models/             # Pydantic 데이터 모델
└── export/             # FCPXML, 보고서 내보내기

skills/
├── _common/            # 공통 모듈 (SRT 파서, CLI 유틸, 병렬 처리)
├── transcript-overview/ # Pass 1: 스토리 구조 분석
├── subtitle-cut/       # Pass 2: 강의 편집
└── podcast-cut/        # Pass 2: 팟캐스트 편집
```

## 외부 의존성

| 서비스 | 용도 | 필수 |
|--------|------|------|
| `claude` CLI 또는 `codex` CLI | AI 분석 | 둘 중 하나 |
| Chalna API | 음성 인식 | podcast-cut 자동 전사 시 |
| FFmpeg / FFprobe | 오디오 추출, 미디어 분석 | 필수 |

## 문서

- [SPEC.md](SPEC.md) — CLI API 스펙, 데이터 모델, 내보내기 형식
- [ARCHITECTURE.md](ARCHITECTURE.md) — 시스템 아키텍처, 서비스 계층, 데이터 흐름

## 라이선스

CC BY-NC-SA 4.0
