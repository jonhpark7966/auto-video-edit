# AVID — 자동 영상 편집 스펙 문서

## 한 줄 요약

영상의 무음 구간과 불필요한 발화(중복, 필러, 미완성 문장)를 자동으로 감지하여 Final Cut Pro용 편집 결정을 생성하는 도구.

---

## 무엇을 하는가

1. **무음 구간 감지**: FFmpeg 오디오 분석 + SRT 자막 갭 분석을 결합하여 무음 구간을 찾는다.
2. **자막 기반 편집 결정**: AI(Claude, Codex)가 자막을 읽고 잘라야 할 부분을 판단한다.
3. **타임라인 생성**: 감지 결과를 FCPXML로 내보내 Final Cut Pro에서 바로 열 수 있다.

자막이 없으면 Whisper로 자동 생성한 뒤 분석한다.

---

## 대상 콘텐츠

- 인터뷰 영상
- 강의 영상
- 팟캐스트

언어는 한국어 우선, 이후 다국어 확장 예정.

---

## 핵심 동작 흐름

```
영상 파일 입력
    ↓
[자막 없으면] Whisper로 자동 생성
    ↓
FFmpeg 무음 감지 + SRT 갭 분석 → 무음 구간 목록
    ↓
Claude CLI + Codex CLI → 자막 분석 (중복/필러/미완성 판단)
    ↓
두 결과를 합쳐 편집 결정 생성
    ↓
FCPXML 내보내기 → Final Cut Pro에서 편집
```

---

## 기술 결정 사항

| 항목 | 결정 |
|------|------|
| AI 호출 방식 | `claude` CLI, `codex` CLI (subprocess) — API SDK 아님 |
| 인증 | CLI 도구가 자체 처리 (API 키 직접 관리 안 함) |
| 무음 결합 모드 | `or` + `tight`만 사용 |
| AI 실패 시 | 사용자에게 에러 알림 (규칙 기반 fallback 없음) |
| 품질 원칙 | 정확도 > 속도 |
| 음성 인식 | Whisper 기본, 플러그인 구조로 엔진 교체 가능 |
| AI 의사결정자 | Claude 기본 (변경 가능) |
| 내보내기 형식 | FCPXML (Final Cut Pro) |

---

## 주요 컴포넌트

### 무음 감지 (AudioAnalyzer)
- FFmpeg `silencedetect` 필터로 오디오 무음 구간 추출
- SRT 파일에서 자막 사이 갭(빈 구간) 추출
- 두 결과를 `or` 모드로 결합 (둘 중 하나라도 무음이면 컷 대상)
- `tight` 옵션으로 겹치는 부분만 취할 수도 있음

### 자막 분석 (AIAnalysisService)
- Claude CLI와 Codex CLI를 병렬 호출
- 각 AI가 자막 세그먼트를 분석하여 cut/keep 판단
- 결과를 집계 (기본: Claude 우선, voting 등 전략 선택 가능)
- 감지 대상: 중복 발화, 불완전 문장, 필러("음...", "어...")

### 음성 인식 (TranscriptionService)
- Whisper 기반 자동 자막 생성
- 플러그인 구조 — 다른 엔진으로 교체 가능

### 내보내기 (FCPXMLExporter)
- 편집 결정을 FCPXML 형식으로 출력
- NTSC 프레임 레이트 지원
- 프로젝트 병합 기능

---

## 평가 방법

모든 컴포넌트는 정량적으로 평가한다.

| 메트릭 | 설명 | 목표 |
|--------|------|------|
| IoU | 예측 구간과 정답 구간의 겹침 비율 | > 0.8 |
| Precision | 컷 판단 중 실제 맞는 비율 | > 0.85 |
| Recall | 실제 컷 대상 중 감지한 비율 | > 0.85 |
| F1 | Precision과 Recall의 조화 평균 | > 0.85 |

수동 레이블링된 ground truth 데이터셋으로 검증.

---

## 개발 단계

| 단계 | 내용 | 예상 기간 |
|------|------|----------|
| Phase 1 | Streamlit UI 구축 | 1일 |
| Phase 2 | 기존 스킬 검증 및 개선 | 1주 |
| Phase 3 | Whisper 자동 음성 인식 | 4일 |
| Phase 4 | 멀티 AI 자막 분석 | 5일 |
| Phase 5 | 파이프라인 통합 | 5.5일 |
| Phase 6 | 평가 프레임워크 | 5.5일 |
| Phase 7 | 미래 확장 (장면 감지, 화자 분리 등) | 선택 |

Phase 1~6까지 약 4주 소요 예상.

---

## 기존 자산

- **skillthon/detect-silence**: FFmpeg 무음 감지 스킬 (972줄, 참조 구현)
- **skillthon/subtitle-cut-detector**: Claude CLI 자막 분석 스킬 (참조 구현)
- **FCPXML Exporter**: 이미 구현됨
- **데이터 모델**: Project, Track, EditDecision 등 Pydantic 모델

---

## 제약 사항

- `claude` CLI와 `codex` CLI가 환경에 설치되어 있어야 함
- FFmpeg 필수
- AI 실패 시 자동 대체 로직 없음 — 사용자가 직접 판단
- 비상업적 용도만 허용 (CC BY-NC-SA 4.0)
