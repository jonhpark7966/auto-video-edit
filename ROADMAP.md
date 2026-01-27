# Auto Video Edit - 개발 로드맵

## 개발 방침
실제 작동하는 기능을 우선 구현하고, 점진적으로 개선합니다.
각 Phase가 완료되면 다음 Phase로 넘어갑니다.

---

## 현재 상태 (2026-01-28)

### ✅ 완료된 것
- **MediaService**: FFmpeg 래퍼 (미디어 정보 추출, 오디오 추출)
- **FCPXML Exporter**: Final Cut Pro XML 내보내기 (NTSC 프레임 레이트 지원, 프로젝트 병합)
- **데이터 모델**: Project, Track, EditDecision, Timeline (Pydantic)
- **Skillthon 스킬**:
  - `subtitle-cut-detector`: Claude 기반 자막 분석 (중복, 불완전, 필러 감지)
  - `detect-silence`: FFmpeg 기반 무음 감지 (SRT 결합 지원, 5가지 모드)

### ⚠️ 문제가 있는 것
- **Gradio UI**: Placeholder 구현만 있음, 파이프라인 미연결 → **삭제 예정**
- **파이프라인 스테이지**: 인터페이스만 정의, 실제 구현 없음 (0개)
- **스킬 통합**: 독립 실행만 가능, 백엔드 파이프라인과 미통합
- **테스트**: 거의 없음

### 🔍 검증 필요한 것
- **detect-silence 스킬**: 972줄의 복잡한 구현, 실제 품질 미검증
- **subtitle-cut 스킬**: Claude 의존성, 에러 핸들링 부족
- **FCPXML 출력**: 실제 FCP에서 테스트 필요

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

**발견된 문제 기록**:
```markdown
# 문제 1: [제목]
- 증상: [설명]
- 재현 방법: [단계]
- 예상 원인: [분석]
- 해결 방안: [제안]

# 문제 2: ...
```

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

**발견된 문제 기록**:
```markdown
# 문제 1: Claude CLI 의존성
- 증상: Claude CLI가 없으면 크래시
- 해결 방안: 
  - Option 1: Claude API 직접 호출
  - Option 2: Fallback to 규칙 기반 분석

# 문제 2: 에러 핸들링 부족
- 증상: subprocess 실패 시 크래시
- 해결 방안: try-catch 추가, 사용자 친화적 에러 메시지
```

### 2.3. 스킬 개선 작업

**우선순위 1: 에러 핸들링**
- [ ] 모든 subprocess 호출에 try-catch
- [ ] 파일 존재 여부 확인
- [ ] FFmpeg 실패 시 명확한 에러 메시지
- [ ] Claude CLI 실패 시 Fallback

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

## Phase 3: 파이프라인 통합

**목표**: 스킬을 백엔드 파이프라인에 통합

### 작업 내용
- [ ] SilenceStage 구현
  - [ ] detect-silence 스킬 래핑
  - [ ] EditDecision 생성
  - [ ] 진행률 콜백
- [ ] SubtitleCutStage 구현
  - [ ] subtitle-cut 스킬 래핑
  - [ ] EditDecision 생성
- [ ] PipelineExecutor 연결
  - [ ] 스테이지 순차 실행
  - [ ] 에러 핸들링
  - [ ] 롤백 지원
- [ ] 프로젝트 병합
  - [ ] 여러 스테이지 결과 통합
  - [ ] 겹치는 컷 처리

### 검증 방법
```bash
# CLI로 전체 파이프라인 실행
avid-cli video.mp4 \
  --srt subtitles.srt \
  --detect-silence \
  --subtitle-cut \
  -o output.fcpxml

# 결과 확인:
# 1. 무음 구간이 제거되었는지
# 2. 중복/불완전 세그먼트가 제거되었는지
# 3. FCPXML이 FCP에서 정상 작동하는지
```

### 예상 작업 시간
- SilenceStage: 0.5일
- SubtitleCutStage: 0.5일
- PipelineExecutor 연결: 1일
- 테스트 및 디버깅: 1일
- **총 예상**: 3일

---

## Phase 4: Whisper 음성 인식 (선택)

**목표**: 자막이 없을 때 자동 생성

### 작업 내용
- [ ] TranscriptionService 구현
  - [ ] Whisper 또는 faster-whisper 연동
  - [ ] 타임스탬프 포함 transcription
  - [ ] SRT 파일 생성
- [ ] TranscribeStage 파이프라인 단계
- [ ] 자동 워크플로우
  - [ ] Transcribe → SubtitleCut

### 검증 방법
- 자막 없는 영상으로 테스트
- 생성된 SRT 품질 확인
- 자동 컷 결과 확인

### 예상 작업 시간
- TranscriptionService: 1일
- TranscribeStage: 0.5일
- 통합 테스트: 0.5일
- **총 예상**: 2일

---

## Phase 5: 싱크 기능 (선택)

**목표**: 영상과 별도 녹음 오디오의 싱크 맞추기

### 작업 내용
- [ ] SyncService 구현
  - [ ] 오디오 파형 분석 (cross-correlation)
  - [ ] offset 계산
- [ ] SyncStage 파이프라인 단계
- [ ] FCPXML에 offset 반영

### 검증 방법
- 카메라 영상 + 별도 마이크 녹음 파일로 테스트
- FCP에서 싱크 확인

### 예상 작업 시간
- SyncService: 2-3일
- SyncStage: 0.5일
- 테스트: 1일
- **총 예상**: 4일

---

## 기술 스택

### 현재 사용 중
- **Backend**: Python 3.11+ / FastAPI
- **UI**: Streamlit (Gradio에서 전환)
- **미디어 처리**: FFmpeg
- **데이터 검증**: Pydantic
- **AI 분석**: Claude (Claude CLI)
- **내보내기**: FCPXML, Premiere XML

### 계획 중
- **음성인식**: Whisper / faster-whisper (Phase 4)
- **오디오 분석**: librosa / scipy (Phase 5)
- **테스트**: pytest, pytest-asyncio
- **로깅**: Python logging

---

## 진행 상황 요약

| Phase | 목표 | 상태 | 완성도 | 예상 시간 |
|-------|------|------|--------|----------|
| **Phase 1** | Streamlit UI | 🔄 진행 예정 | 0% | 1일 |
| **Phase 2** | 스킬 검증 및 개선 | 🔍 계획 중 | 0% | 1주 |
| **Phase 3** | 파이프라인 통합 | ⏳ 대기 | 0% | 3일 |
| **Phase 4** | Whisper 음성 인식 | ⏳ 선택 | 0% | 2일 |
| **Phase 5** | 싱크 기능 | ⏳ 선택 | 0% | 4일 |

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

---

## 알려진 문제 및 개선 사항

### detect-silence 스킬
- [ ] 실제 품질 미검증 (972줄의 복잡한 구현)
- [ ] 엣지 케이스 테스트 필요
- [ ] 성능 최적화 필요 (FFmpeg 호출 최소화)

### subtitle-cut 스킬
- [ ] Claude CLI 의존성 (없으면 크래시)
- [ ] 에러 핸들링 부족
- [ ] subprocess 실패 시 크래시
- [ ] Fallback 메커니즘 없음

### 백엔드
- [ ] 파이프라인 스테이지 미구현 (0개)
- [ ] 테스트 코드 없음
- [ ] 로깅 설정 없음
- [ ] 에러 핸들링 부족

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
