# AVID — Auto Video Edit

영상의 무음 구간과 불필요한 발화를 자동 감지하여 Final Cut Pro용 편집 타임라인(FCPXML)을 생성하는 CLI 도구.

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

## CLI 사용법

```bash
# 설치
cd apps/backend
pip install -e .

# Two-Pass 워크플로우
avid-cli transcript-overview lecture.srt -o lecture.storyline.json
avid-cli subtitle-cut lecture.mp4 --srt lecture.srt --context lecture.storyline.json

# 팟캐스트 (SRT 없으면 자동 전사)
avid-cli podcast-cut podcast.m4a --context podcast.storyline.json --final

# 단독 실행 (Pass 1 생략)
avid-cli subtitle-cut lecture.mp4 --srt lecture.srt
avid-cli podcast-cut podcast.m4a --srt podcast.srt

# 무음 감지
avid-cli silence video.mp4 --srt sub.srt

# 음성 인식
avid-cli transcribe video.mp4

# 편집 결과 평가
avid-cli eval predicted.fcpxml ground_truth.fcpxml
```

## 기술 스택

- **Backend**: Python 3.11+ / FastAPI
- **AI 분석**: `claude` CLI / `codex` CLI (subprocess)
- **음성 인식**: Chalna API
- **미디어 처리**: FFmpeg / FFprobe
- **내보내기**: FCPXML (Final Cut Pro)

## 프로젝트 구조

```
apps/backend/src/avid/
├── cli.py              # CLI 진입점 (6개 명령어)
├── services/           # 비즈니스 로직 (7개 서비스)
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
| FFmpeg | 미디어 분석 | 필수 |

## 문서

- [SPEC.md](SPEC.md) — CLI API 스펙, 데이터 모델, 내보내기 형식
- [ARCHITECTURE.md](ARCHITECTURE.md) — 시스템 아키텍처, 서비스 계층, 데이터 흐름

## 라이선스

CC BY-NC-SA 4.0
