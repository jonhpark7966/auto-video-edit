# Auto Video Edit - 개발 로드맵

## 개발 방침
실제 작동하는 기능을 우선 구현하고, 점진적으로 개선합니다.
각 Phase가 완료되면 다음 Phase로 넘어갑니다.

**핵심 원칙**:
- **정확도 > 속도**: 품질이 최우선
- **테스트 가능성**: 모든 컴포넌트는 FCPXML 기반 평가 프레임워크로 검증
- **확장 가능성**: 플러그인 가능한 아키텍처
- **사용자 중심**: 에러 발생 시 사용자에게 명확히 알림

---

## 현재 상태 (2026-02-07)

### ✅ 완료된 것
- **MediaService**: FFmpeg 래퍼 (미디어 정보 추출, 오디오 추출)
- **FCPXML Exporter**: Final Cut Pro XML 내보내기 (NTSC 프레임 레이트 지원, 프로젝트 병합, 강의/팟캐스트 EditReason 모두 지원)
- **데이터 모델**: Project, Track, EditDecision, Timeline (Pydantic) — EditReason 확장 완료 (강의 + 팟캐스트)
- **스킬 (skills/)**:
  - `subtitle-cut`: 강의/설명 영상용 자막 분석 (중복, 불완전, 필러, 말실수 감지)
  - `podcast-cut`: 팟캐스트/인터뷰용 재미 기준 분석 (entertainment_score 1-10)
  - `_common`: 스킬 간 공통 모듈 (SRT 파서, CLI 유틸, 비디오 정보, 공통 모델)
- **PodcastCutService**: 팟캐스트 전체 워크플로우 (chalna 전사 → 챕터 분석 → 엔터테인먼트 분석 → 무음 감지 → FCPXML)
- **CLI**: `avid-cli podcast-cut` 서브커맨드 (review/final 모드 지원)
- **리포트 생성기**: 동적 EditReason 지원 (강의/팟캐스트 모두)

### ⚠️ 문제가 있는 것
- **Gradio UI**: Placeholder 구현만 있음, 파이프라인 미연결 → **삭제 예정**
- **파이프라인 스테이지**: 인터페이스만 정의, 실제 구현 없음 (0개)
- **스킬 통합**: 독립 실행만 가능, 백엔드 파이프라인과 미통합
- **테스트**: 거의 없음
- **평가 프레임워크**: 미구현 (FCPXML 기반 비교 방식 예정)

### 🔍 검증 필요한 것
- **detect-silence 스킬**: 972줄의 복잡한 구현, 실제 품질 미검증
- **subtitle-cut 스킬**: Claude 의존성, 에러 핸들링 부족
- **FCPXML 출력**: 실제 FCP에서 테스트 필요

---

## 사용자 요구사항 (최종 확정)

### 핵심 기능
1. **FFmpeg + SRT 기반 편집**
   - FFmpeg: 무음 감지, 미디어 처리
   - SRT: 자막 기반 세그먼트 분석
   - 구현: 백엔드 서비스 (스킬 아님)

2. **결합 모드**
   - `or` 모드: FFmpeg OR SRT 중 하나라도 컷 대상이면 제거
   - `tight` 옵션: 컷 구간을 최소화 (보수적 접근)

3. **에러 핸들링**
   - 에러 발생 시 사용자에게 명확히 알림
   - 규칙 기반 폴백 없음 (AI 실패 시 사용자 판단)

4. **우선순위**
   - 정확도 > 속도
   - 품질이 최우선

5. **사용 사례**
   - 인터뷰 영상
   - 강의 영상
   - 팟캐스트

6. **언어 지원**
   - 1차: 한국어
   - 2차: 다국어 확장

7. **품질 중시**
   - 모든 컴포넌트는 FCPXML 기반 평가 프레임워크로 검증
   - 편집 전/후 FCPXML 비교로 자동 평가
   - 무음 감지, 의미단위 컷편집 각각 별도 평가
   - 스킬을 바꿔가며 반복 평가 → 품질 개선 루프

### 자동 음성 인식 (Whisper)
- 자막이 없을 때 자동 생성
- Whisper (기본)
- 플러그인 가능한 엔진 구조 (향후 다른 엔진 추가 가능)

### 멀티 AI 분석 (CLI 기반)
- **`claude` CLI + `codex` CLI**: 환경에 설치된 CLI 도구로 호출 (API SDK 아님)
- **skillthon 서브모듈**: 로컬 CLI에 설치하여 직접 호출하는 스킬
- **결과 집계**: 두 AI의 분석 결과를 종합
- **기본 의사결정자**: Claude
- **확장 가능**: 추가 CLI 도구 프로바이더 지원

### 미래 확장 기능
- **화면 기반 편집**: 장면 변화 감지, 얼굴 인식 등 (구체적 기술 미정)
- **음성 기반 편집**: 화자 분리, 감정 분석 등 (구체적 기술 미정)

---

## 아키텍처 결정

### 설계 원칙
1. **프로토콜 기반 서비스 인터페이스**
   - 기존 패턴 유지
   - 느슨한 결합, 높은 테스트 가능성

2. **파이프라인 스테이지 시스템**
   - 기존 패턴 유지
   - 각 스테이지는 독립적으로 테스트 가능

3. **멀티 프로바이더 패턴**
   - Factory 패턴으로 프로바이더 선택
   - LiteLLM 패턴 참고 (멀티 LLM 라우팅)

4. **평가 프레임워크**
   - FCPXML 기반 비교: 편집 전/후 FCPXML을 비교하여 자동 평가
   - 정답 FCPXML (사람이 편집한 결과)과 결과 FCPXML 대조
   - 무음 감지, 의미단위 컷편집 각각 별도 평가
   - 스킬을 교체하며 반복 평가 → 품질 개선 루프

5. **플러그인 가능한 트랜스크립션 엔진**
   - TranscriptionProvider 인터페이스
    - Whisper (기본), 플러그인 가능한 엔진 인터페이스

### 기술 스택

#### 현재 사용 중
- **Backend**: Python 3.11+ / FastAPI
- **UI**: Streamlit (Gradio에서 전환)
- **미디어 처리**: FFmpeg
- **데이터 검증**: Pydantic
- **AI 분석**: `claude` CLI (Claude Code), `codex` CLI

#### 추가 예정
- **음성인식**: Whisper (Phase 3)
- **화면/음성 기반 편집**: 확장 인터페이스만 정의 (Phase 7, 구체적 기술 미정)
- **테스트**: pytest, pytest-asyncio
- **로깅**: Python logging
- **평가**: FCPXML 비교 기반 자동 평가

---

## Phase 1: UI 재설계 (Streamlit) 🔄 진행 예정

**목표**: 간단하고 작동하는 UI 구축

### 작업 내용
- [ ] Gradio UI 삭제 (`apps/backend/src/avid/ui/app.py`)
- [ ] Streamlit UI 구현
  - [ ] 파일 업로드 (비디오, 오디오, SRT)
  - [ ] 무음 감지 옵션 (임계값, 최소 길이, 패딩)
  - [ ] 자막 분석 옵션 (Claude 사용 여부)
  - [ ] 실행 버튼 + 진행률 표시
  - [ ] 결과 다운로드 (FCPXML)
- [ ] CLI 통합
  - [ ] detect-silence 스킬 호출
  - [ ] subtitle-cut 스킬 호출
  - [ ] 프로젝트 병합
  - [ ] FCPXML 내보내기

### 검증 방법
```bash
# Streamlit 실행
streamlit run apps/backend/src/avid/ui/streamlit_app.py

# 테스트 시나리오:
# 1. 비디오 파일 업로드
# 2. 무음 감지 실행
# 3. FCPXML 다운로드
# 4. Final Cut Pro에서 열기
```

### 예상 작업 시간
- Gradio 삭제: 5분
- Streamlit UI 기본 구조: 2-3시간
- CLI 통합: 3-4시간
- 테스트 및 디버깅: 2-3시간
- **총 예상**: 1일

---

## Phase 2: 스킬 검증 및 개선 🔍 계획 중

**목표**: 기존 스킬의 품질 검증 및 문제 해결

### 2.1. detect-silence 스킬 검증

**현재 구현 분석**:
- 972줄의 복잡한 구현
- FFmpegAudioAnalyzer, SrtParser, SilenceCombiner 클래스
- 5가지 결합 모드 (ffmpeg, srt, and, or, diff)
- 자동 템포 기반 임계값 조정

**검증 항목**:
- [ ] 실제 비디오로 무음 감지 정확도 테스트
- [ ] FFmpeg silencedetect 출력 파싱 정확도
- [ ] SRT 갭 분석 정확도
- [ ] 결합 모드별 결과 비교
- [ ] 엣지 케이스 테스트:
  - [ ] 매우 짧은 무음 (< 100ms)
  - [ ] 매우 긴 무음 (> 10초)
  - [ ] 배경 음악이 있는 경우
  - [ ] 노이즈가 많은 경우
  - [ ] SRT 타이밍이 부정확한 경우

### 2.2. subtitle-cut 스킬 검증

**현재 구현 분석**:
- Claude CLI 기반 의미론적 분석
- 중복, 불완전, 필러 감지
- subprocess로 Claude 호출

**검증 항목**:
- [ ] Claude 분석 정확도 테스트
- [ ] 다양한 자막 패턴 테스트:
  - [ ] 짧은 세그먼트 (< 2초)
  - [ ] 긴 세그먼트 (> 30초)
  - [ ] 중복 인트로 (3-4번 반복)
  - [ ] 불완전한 문장
  - [ ] 필러 워드 ("음", "어", "그...")
- [ ] 에러 핸들링 테스트:
  - [ ] Claude CLI 없을 때
  - [ ] Claude API 실패 시
  - [ ] 잘못된 SRT 형식
  - [ ] 타임스탬프 오류

### 2.3. 스킬 개선 작업

**우선순위 1: 에러 핸들링**
- [ ] 모든 subprocess 호출에 try-catch
- [ ] 파일 존재 여부 확인
- [ ] FFmpeg 실패 시 명확한 에러 메시지
- [ ] Claude CLI 실패 시 사용자에게 알림 (폴백 없음)

**우선순위 2: 로깅**
- [ ] Python logging 설정
- [ ] 각 단계별 로그 출력
- [ ] 디버그 모드 추가

**우선순위 3: 성능 최적화**
- [ ] FFmpeg 호출 최소화
- [ ] 중간 결과 캐싱
- [ ] 병렬 처리 (가능한 경우)

**우선순위 4: 테스트 작성**
- [ ] 단위 테스트 (각 클래스/함수)
- [ ] 통합 테스트 (전체 워크플로우)
- [ ] 샘플 데이터 준비

### 예상 작업 시간
- 스킬 검증: 1-2일
- 문제 분석 및 문서화: 0.5일
- 개선 작업: 2-3일
- 테스트 작성: 1-2일
- **총 예상**: 1주

---

## Phase 3: Whisper 자동 음성 인식

**목표**: 자막이 없을 때 자동 생성 (플러그인 가능한 엔진)

### 3.1. TranscriptionProvider 인터페이스

```python
from typing import Protocol
from pathlib import Path

class TranscriptionProvider(Protocol):
    """음성 인식 프로바이더 인터페이스"""
    
    def transcribe(
        self,
        audio_path: Path,
        language: str = "ko",
        **kwargs
    ) -> list[SubtitleSegment]:
        """오디오 파일을 텍스트로 변환"""
        ...
```

### 3.2. 지원 엔진

**Whisper (기본)**
- OpenAI Whisper
- 로컬 실행
- 높은 정확도

**향후 확장**
- 플러그인 가능한 TranscriptionProvider 인터페이스
- 사용자가 원하는 엔진 추가 가능

### 3.3. 작업 내용

- [ ] TranscriptionProvider 인터페이스 정의
- [ ] WhisperProvider 구현
- [ ] TranscriptionFactory (프로바이더 선택)
- [ ] TranscribeStage 파이프라인 단계
- [ ] SRT 파일 생성
- [ ] 자동 워크플로우: Transcribe → SubtitleCut

### 3.4. 검증 방법

```bash
# 자막 없는 영상으로 테스트
avid-cli video.mp4 \
  --transcribe \
  --engine faster-whisper \
  --language ko \
  --subtitle-cut \
  -o output.fcpxml

# 결과 확인:
# 1. 생성된 SRT 품질
# 2. 자동 컷 결과
# 3. FCPXML 정상 작동
```

### 3.5. 평가 프레임워크

- [ ] Whisper 생성 자막 → 편집 결과 FCPXML로 평가
- [ ] 정답 FCPXML과 비교하여 자막 품질이 최종 편집에 미치는 영향 측정
- [ ] 엔진별 성능 비교 (FCPXML 결과 기준)

### 예상 작업 시간
- 인터페이스 설계: 0.5일
- Whisper 구현: 1일
- TranscribeStage: 0.5일
- FCPXML 기반 평가: 1일
- 통합 테스트: 0.5일
- **총 예상**: 4일

---

## Phase 4: 멀티 AI 자막 분석 (CLI 기반)

**목표**: `claude` CLI + `codex` CLI로 자막 분석, 결과 집계

### 4.1. SubtitleAnalysisProvider 인터페이스

```python
from typing import Protocol

class SubtitleAnalysisProvider(Protocol):
    """자막 분석 프로바이더 인터페이스 (CLI 기반)"""
    
    def analyze(
        self,
        srt_path: Path,
        analysis_type: str = "all"
    ) -> list[CutSegment]:
        """CLI 도구를 통해 자막 분석"""
        ...
```

### 4.2. 지원 AI (CLI 도구)

**Claude (기본 의사결정자)**
- `claude` CLI (Claude Code) — subprocess로 호출
- 높은 정확도, 의미론적 분석
- skillthon/subtitle-cut-detector 스킬을 로컬 CLI에 설치하여 호출

**Codex**
- `codex` CLI — subprocess로 호출
- 보조 분석, 결과 검증

**확장 가능**
- 환경에 설치된 다른 CLI 도구 추가 가능

### 4.3. 작업 내용

- [ ] SubtitleAnalysisProvider 인터페이스 정의
- [ ] ClaudeProvider 구현 (기존 스킬 래핑)
- [ ] CodexProvider 구현
- [ ] MultiAIAggregator (결과 집계)
  - [ ] 두 AI의 분석 결과 비교
  - [ ] 일치하는 세그먼트 우선
  - [ ] 불일치 시 Claude 결과 사용
- [ ] SubtitleCutStage 업데이트 (멀티 AI 지원)

### 4.4. 결과 집계 전략

**전략 1: Voting (기본)**
- 두 AI가 모두 컷 대상으로 판단한 세그먼트만 제거
- 보수적 접근 (정확도 우선)

**전략 2: Union**
- 둘 중 하나라도 컷 대상으로 판단하면 제거
- 공격적 접근 (재현율 우선)

**전략 3: Claude Priority**
- Claude 결과를 기본으로 사용
- Codex는 검증 용도

### 4.5. 검증 방법

```bash
# 멀티 AI 분석
avid-cli video.mp4 \
  --srt subtitles.srt \
  --subtitle-cut \
  --ai claude,codex \
  --aggregation voting \
  -o output.fcpxml

# 결과 확인:
# 1. 두 AI의 분석 결과 비교
# 2. 집계 전략별 결과 차이
# 3. 최종 컷 품질
```

### 4.6. 평가 프레임워크

- [ ] AI별 FCPXML 결과 비교
- [ ] 집계 전략별 FCPXML 결과 비교
- [ ] 정답 FCPXML과 대조하여 자동 평가
- [ ] 스킬 변경 → 재평가 반복

### 예상 작업 시간
- 인터페이스 설계: 0.5일
- ClaudeProvider 구현: 0.5일
- CodexProvider 구현: 1일
- MultiAIAggregator: 1일
- SubtitleCutStage 업데이트: 0.5일
- FCPXML 기반 평가: 1일
- 통합 테스트: 0.5일
- **총 예상**: 5일

---

## Phase 5: 파이프라인 통합 및 백엔드 서비스화

**목표**: 스킬을 백엔드 파이프라인에 통합, FFmpeg + SRT 백엔드 서비스로 구현

### 5.1. 백엔드 서비스 구현

**SilenceDetectionService**
- FFmpeg silencedetect 래핑
- SRT 갭 분석
- `or` + `tight` 결합 모드
- 백엔드 서비스 (스킬 아님)

**SubtitleAnalysisService**
- 멀티 AI 분석 (Claude + Codex)
- 결과 집계
- 백엔드 서비스 (스킬 아님)

### 5.2. 파이프라인 스테이지

- [ ] SilenceStage 구현
  - [ ] SilenceDetectionService 호출
  - [ ] EditDecision 생성
  - [ ] 진행률 콜백
- [ ] SubtitleCutStage 구현
  - [ ] SubtitleAnalysisService 호출
  - [ ] EditDecision 생성
- [ ] TranscribeStage 구현 (Phase 3에서)
  - [ ] TranscriptionService 호출
  - [ ] SRT 파일 생성
- [ ] PipelineExecutor 연결
  - [ ] 스테이지 순차 실행
  - [ ] 에러 핸들링 (사용자 알림)
  - [ ] 롤백 지원
- [ ] 프로젝트 병합
  - [ ] 여러 스테이지 결과 통합
  - [ ] 겹치는 컷 처리

### 5.3. 검증 방법

```bash
# CLI로 전체 파이프라인 실행
avid-cli video.mp4 \
  --srt subtitles.srt \
  --detect-silence \
  --subtitle-cut \
  --ai claude,codex \
  -o output.fcpxml

# 자막 없는 경우
avid-cli video.mp4 \
  --transcribe \
  --engine faster-whisper \
  --detect-silence \
  --subtitle-cut \
  -o output.fcpxml

# 결과 확인:
# 1. 무음 구간이 제거되었는지
# 2. 중복/불완전 세그먼트가 제거되었는지
# 3. FCPXML이 FCP에서 정상 작동하는지
```

### 예상 작업 시간
- SilenceDetectionService: 1일
- SubtitleAnalysisService: 1일
- SilenceStage: 0.5일
- SubtitleCutStage: 0.5일
- PipelineExecutor 연결: 1일
- 프로젝트 병합: 0.5일
- 테스트 및 디버깅: 1일
- **총 예상**: 5.5일

---

## Phase 6: 평가 프레임워크 (FCPXML 기반)

**목표**: FCPXML 편집 전/후 비교로 모든 컴포넌트를 자동 평가

### 6.1. 평가 방식

**핵심**: 각 편집 행위(무음 컷, 의미단위 컷)의 결과는 FCPXML로 표현됨. 사람이 편집한 정답 FCPXML과 자동 생성 FCPXML을 비교하여 품질을 측정.

**평가 루프**:
```
스킬 변경 → 편집 실행 → 결과 FCPXML 생성 → 정답 FCPXML과 비교 → 메트릭 산출 → 반복
```

**평가 단위**:
- 무음 감지 평가: `ground_truth_silence.fcpxml` vs 결과
- 의미단위 컷편집 평가: `ground_truth_subtitle.fcpxml` vs 결과

### 6.2. Ground Truth 데이터셋

- [ ] 사람이 직접 편집한 정답 FCPXML 준비
- [ ] 다양한 사용 사례 (인터뷰, 강의, 팟캐스트)
- [ ] 다양한 언어 (한국어, 영어)
- [ ] 엣지 케이스 포함
- [ ] 무음 컷 / 의미단위 컷 각각 별도 정답

### 6.3. 작업 내용

- [ ] FCPXMLComparator 구현 (편집 전/후 FCPXML 비교)
  - [ ] FCPXML에서 편집 구간 추출
  - [ ] 시간축 기준 구간 매칭
  - [ ] 일치/불일치 산출
- [ ] EvaluationRunner 구현
  - [ ] 무음 감지 평가
  - [ ] 의미단위 컷편집 평가
- [ ] Ground Truth FCPXML 준비
- [ ] 자동 평가 스크립트 (스킬 교체 후 재평가)
- [ ] 평가 리포트 생성

### 6.4. 검증 방법

```bash
# 무음 감지 평가
avid-eval \
  --test-case test_data/cases/interview_01/ \
  --component silence \
  --output report.json

# 의미단위 컷편집 평가
avid-eval \
  --test-case test_data/cases/interview_01/ \
  --component subtitle-cut \
  --output report.json

# 리포트:
# {
#   "component": "silence",
#   "matched_cuts": 12,
#   "missed_cuts": 1,
#   "extra_cuts": 2,
#   "timeline_overlap_ratio": 0.87
# }
```

### 예상 작업 시간
- FCPXMLComparator: 2일
- Ground Truth FCPXML 준비: 2일
- 자동 평가 스크립트: 1일
- 평가 리포트: 0.5일
- **총 예상**: 5.5일

---

## Phase 7: 미래 확장 기능 (선택)

**목표**: 고급 분석 기능 추가

### 7.1. 장면 감지

- [ ] SceneDetectionService 인터페이스 정의
- [ ] 장면 전환 감지 구현 (기술 선정 시 결정)
- [ ] SceneStage 파이프라인 단계

**예상 작업 시간**: 2일

### 7.2. 화자 분리

- [ ] SpeakerDiarizationService 인터페이스 정의
- [ ] 화자별 세그먼트 분리 구현 (기술 선정 시 결정)
- [ ] SpeakerStage 파이프라인 단계

**예상 작업 시간**: 3일

### 7.3. 감정 분석

- [ ] EmotionDetectionService 인터페이스 정의
- [ ] 감정 분석 구현 (기술 선정 시 결정)
- [ ] EmotionStage 파이프라인 단계

**예상 작업 시간**: 3일

### 7.4. 싱크 기능 (선택)

**목표**: 영상과 별도 녹음 오디오의 싱크 맞추기

- [ ] SyncService 구현
  - [ ] 오디오 파형 분석 (cross-correlation)
  - [ ] offset 계산
- [ ] SyncStage 파이프라인 단계
- [ ] FCPXML에 offset 반영

**검증 방법**:
- 카메라 영상 + 별도 마이크 녹음 파일로 테스트
- FCP에서 싱크 확인

**예상 작업 시간**: 4일

---

## 진행 상황 요약

| Phase | 목표 | 상태 | 완성도 | 예상 시간 |
|-------|------|------|--------|----------|
| **Phase 1** | Streamlit UI | 🔄 진행 예정 | 0% | 1일 |
| **Phase 2** | 스킬 검증 및 개선 | 🔍 계획 중 | 0% | 1주 |
| **Phase 3** | Whisper 자동 음성 인식 | ⏳ 대기 | 0% | 4일 |
| **Phase 4** | 멀티 AI 자막 분석 | ⏳ 대기 | 0% | 5일 |
| **Phase 5** | 파이프라인 통합 | ⏳ 대기 | 0% | 5.5일 |
| **Phase 6** | 평가 프레임워크 | ⏳ 대기 | 0% | 5.5일 |
| **Phase 7** | 미래 확장 기능 | ⏳ 선택 | 0% | 12일 |

**총 예상 시간 (Phase 1-6)**: 약 4주
**총 예상 시간 (Phase 1-7)**: 약 6주

---

## 다음 작업 (우선순위)

### 즉시 실행
1. ✅ Gradio UI 삭제
2. ✅ ROADMAP.md 업데이트 (이 문서)
3. 🔄 Streamlit UI 기본 구조 작성

### 이번 주
1. Streamlit UI 완성
2. CLI에 스킬 통합
3. 실제 비디오로 테스트

### 다음 주
1. 스킬 검증 (detect-silence, subtitle-cut)
2. 발견된 문제 문서화
3. 개선 작업 시작

### 이번 달
1. Whisper 자동 음성 인식 구현
2. 멀티 AI 자막 분석 구현
3. 파이프라인 통합
4. 평가 프레임워크 구축

---

## 알려진 문제 및 개선 사항

### detect-silence 스킬
- [ ] 실제 품질 미검증 (972줄의 복잡한 구현)
- [ ] 엣지 케이스 테스트 필요
- [ ] 성능 최적화 필요 (FFmpeg 호출 최소화)
- [ ] `or` + `tight` 모드로 단순화 필요

### subtitle-cut 스킬
- [ ] Claude CLI 의존성 (없으면 크래시)
- [ ] 에러 핸들링 부족 (사용자 알림 필요)
- [ ] subprocess 실패 시 크래시
- [ ] 멀티 AI 지원 필요 (Claude + Codex)

### 백엔드
- [ ] 파이프라인 스테이지 미구현 (0개)
- [ ] 테스트 코드 없음
- [ ] 로깅 설정 없음
- [ ] 에러 핸들링 부족
- [ ] 평가 프레임워크 없음

### FCPXML 내보내기
- [ ] 실제 FCP에서 테스트 필요
- [ ] Connected audio clips 미구현 (TODO 주석)
- [ ] Premiere XML 내보내기 미구현 (stub만)

---

## 참고 자료

### 스킬 문서
- `skillthon/detect-silence/skills/detect-silence/SKILL.md`
- `skillthon/subtitle-cut-detector/skills/subtitle-cut/SKILL.md`

### 샘플 프로젝트
- `sample_projects/C1718_silence.avid.json` (무음 감지 샘플)
- `sample_projects/C1718_subtitle.avid.json` (자막 분석 샘플)
- `sample_projects/*.fcpxml` (FCPXML 내보내기 샘플)

### 테스트 미디어
- `srcs/C1718_compressed.mp4` (비디오)
- `srcs/C1718_compressed.srt` (자막)

### 연구 자료
- **LiteLLM**: https://github.com/BerriAI/litellm

---

## 성공 기준

### Phase 1-2 완료 시
- [ ] Streamlit UI가 작동함
- [ ] 실제 비디오로 무음 감지 + 자막 분석 가능
- [ ] FCPXML이 FCP에서 정상 작동
- [ ] 에러 발생 시 사용자에게 명확히 알림

### Phase 3-4 완료 시
- [ ] 자막 없는 영상도 자동 처리 가능
- [ ] 멀티 AI 분석 결과 집계
- [ ] 정확도가 단일 AI보다 향상

### Phase 5-6 완료 시
- [ ] 전체 파이프라인이 백엔드 서비스로 통합
- [ ] 모든 컴포넌트가 평가 프레임워크로 검증
- [ ] IoU > 0.8, F1 > 0.85 달성

### Phase 7 완료 시
- [ ] 장면 감지, 화자 분리, 감정 분석 가능
- [ ] 확장 가능한 아키텍처 검증
- [ ] 프로덕션 레디

---

## 라이선스

CC BY-NC-SA 4.0 (비상업적 용도로만 사용 가능)
