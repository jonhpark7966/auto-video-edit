# AVID — 자동 영상 편집 스펙 문서

## 한 줄 요약

영상의 무음 구간과 불필요한 발화를 자동으로 감지하여 Final Cut Pro용 편집 결정을 생성하는 도구. 강의 영상(정보 효율)과 팟캐스트(재미 기준) 두 가지 편집 모드를 지원한다.

---

## 무엇을 하는가

1. **무음 구간 감지**: FFmpeg 오디오 분석 + SRT 자막 갭 분석을 결합하여 무음 구간을 찾는다.
2. **자막 기반 편집 결정 (2가지 모드)**:
   - **subtitle-cut** (강의/설명): AI가 중복 발화, 필러, 말실수, 미완성 문장을 감지하여 제거한다.
   - **podcast-cut** (팟캐스트/인터뷰): AI가 재미 기준으로 판단 — 지루한 구간을 제거하고 유머/케미/클라이맥스를 보존한다.
3. **타임라인 생성**: 감지 결과를 FCPXML로 내보내 Final Cut Pro에서 바로 열 수 있다.

자막이 없으면 Whisper 또는 chalna로 자동 생성한 뒤 분석한다.

---

## 대상 콘텐츠

- 인터뷰 영상
- 강의 영상
- 팟캐스트

언어는 한국어 우선, 이후 다국어 확장 예정.

---

## 핵심 동작 흐름

### subtitle-cut (강의/설명 영상)
```
영상 파일 입력
    ↓
[자막 없으면] Whisper로 자동 생성
    ↓
FFmpeg 무음 감지 + SRT 갭 분석 → 무음 구간 목록
    ↓
Claude CLI / Codex CLI → 자막 분석 (중복/필러/미완성 판단)
    ↓
편집 결정 생성 → FCPXML 내보내기
```

### podcast-cut (팟캐스트/인터뷰)
```
오디오/영상 파일 입력
    ↓
[자막 없으면] chalna로 SRT 생성
    ↓
챕터/토픽 구조 분석
    ↓
Claude CLI → 재미 기준 분석 (entertainment_score 1-10)
    ↓
SRT 갭에서 무음 구간 추출
    ↓
편집 결정 생성 → FCPXML 내보내기 (review / final 모드)
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

### 자막 분석 — subtitle-cut (AIAnalysisService)
- Claude CLI와 Codex CLI를 병렬 호출
- 각 AI가 자막 세그먼트를 분석하여 cut/keep 판단
- 결과를 집계 (기본: Claude 우선, voting 등 전략 선택 가능)
- 감지 대상: 중복 발화(duplicate), 불완전 문장(incomplete), 필러(filler), 말실수(fumble)

### 팟캐스트 분석 — podcast-cut (PodcastCutService)
- chalna로 SRT 생성 후 Claude CLI로 분석
- 챕터 구조 분석 → 청크별 엔터테인먼트 분석 → 무음 감지
- CUT 대상: 지루함(boring), 탈선(tangent), 반복(repetitive), 긴 침묵(long_pause), 동시 발화(crosstalk), 무관한 내용(irrelevant)
- KEEP 대상: 유머(funny), 재치(witty), 케미(chemistry), 리액션(reaction), 콜백 유머(callback), 클라이맥스(climax), 몰입(engaging), 감정(emotional)
- entertainment_score (1-10)로 각 세그먼트 평가

### 음성 인식 (TranscriptionService)
- Whisper 기반 자동 자막 생성
- 플러그인 구조 — 다른 엔진으로 교체 가능

### 내보내기 (FCPXMLExporter)
- 편집 결정을 FCPXML 형식으로 출력
- NTSC 프레임 레이트 지원
- 프로젝트 병합 기능

---

## 평가 방법

FCPXML 기반 자동 평가. 각 편집 행위의 결과를 정답과 비교한다.

**방식**:
1. 사람이 직접 편집한 정답 FCPXML을 준비 (무음 컷, 의미단위 컷 각각)
2. 스킬 실행 → 결과 FCPXML 생성
3. 정답 FCPXML vs 결과 FCPXML 자동 비교
4. 스킬을 바꿔가며 반복 → 품질 개선 루프

**평가 단위**: 무음 감지와 의미단위 컷편집을 각각 별도로 평가한다.

---

## 개발 단계

| 단계 | 내용 | 예상 기간 |
|------|------|----------|
| Phase 1 | Streamlit UI 구축 | 1일 |
| Phase 2 | 기존 스킬 검증 및 개선 | 1주 |
| Phase 3 | Whisper 자동 음성 인식 | 4일 |
| Phase 4 | 멀티 AI 자막 분석 | 5일 |
| Phase 5 | 파이프라인 통합 | 5.5일 |
| Phase 6 | FCPXML 기반 평가 프레임워크 | 5.5일 |
| Phase 7 | 미래 확장 (장면 감지, 화자 분리 등) | 선택 |

Phase 1~6까지 약 4주 소요 예상.

---

## 기존 자산

- **skills/subtitle-cut**: 강의/설명 영상용 자막 분석 스킬 (Claude/Codex CLI)
- **skills/podcast-cut**: 팟캐스트/인터뷰용 재미 기준 분석 스킬 (Claude CLI)
- **skills/_common**: 스킬 간 공통 모듈 (SRT 파서, CLI 유틸, 비디오 정보)
- **PodcastCutService**: 팟캐스트 전체 워크플로우 서비스 (chalna 전사 → 분석 → FCPXML)
- **FCPXML Exporter**: 구현 완료 (강의/팟캐스트 EditReason 모두 지원)
- **데이터 모델**: Project, Track, EditDecision 등 Pydantic 모델

---

## 제약 사항

- `claude` CLI와 `codex` CLI가 환경에 설치되어 있어야 함
- skillthon 스킬이 로컬 CLI에 설치되어 있어야 함
- FFmpeg 필수
- AI 실패 시 자동 대체 로직 없음 — 사용자가 직접 판단
- 비상업적 용도만 허용 (CC BY-NC-SA 4.0)
