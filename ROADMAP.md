# Auto Video Edit - 개발 로드맵

## 개발 방침
워크플로우를 순차적으로 구현하고 검증하면서 진행합니다.
각 Phase가 완료되면 다음 Phase로 넘어갑니다.

---

## Phase 1: 기본 입출력 ✅ 완료
**목표**: 영상 + 오디오 파일을 받아서 FCP XML로 출력

### 작업 내용
- [x] MediaService 구현 (FFmpeg 래퍼)
  - [x] 미디어 정보 추출 (duration, fps, resolution)
  - [x] 오디오 추출
- [x] 기본 FCP XML 출력 테스트
  - [x] 영상 파일 단독 → FCP XML
  - [ ] 영상 + 오디오 파일 → FCP XML (싱크 없이, 두 클립 나란히) → Phase 2에서 처리

### 검증 방법
```bash
# CLI 또는 스크립트로 테스트
python -m avid.cli input_video.mp4 --output project.fcpxml
```
Final Cut Pro에서 열어서 영상이 정상적으로 나오는지 확인

---

## Phase 2: 싱크된 프로젝트
**목표**: 영상과 별도 녹음 오디오의 싱크를 맞춰서 FCP XML 출력

### 작업 내용
- [ ] SyncService 구현
  - [ ] 오디오 파형 분석 (cross-correlation 또는 fingerprint)
  - [ ] offset 계산
- [ ] 싱크된 FCP XML 출력
  - [ ] Primary clip (영상) + Connected clip (오디오) with offset

### 검증 방법
- 카메라 영상 + 별도 마이크 녹음 파일로 테스트
- FCP에서 열어서 싱크가 맞는지 확인

---

## Phase 3: 음성 인식 (Whisper)
**목표**: 오디오에서 텍스트 추출 (자막/편집점 기준)

### 작업 내용
- [ ] TranscriptionService 구현 (Whisper)
  - [ ] whisper 또는 faster-whisper 연동
  - [ ] 타임스탬프 포함 transcription 결과
- [ ] TranscribeStage 파이프라인 단계

### 검증 방법
- 테스트 영상으로 자막 생성 확인
- SRT 파일 출력 테스트

---

## Phase 4: 무음 구간 감지/제거
**목표**: 무음 구간을 자동으로 감지하고 타임라인에서 제거

### 작업 내용
- [ ] AudioAnalyzer 구현
  - [ ] 볼륨 기반 무음 감지
  - [ ] 임계값/최소 길이 설정
- [ ] SilenceStage 파이프라인 단계
- [ ] FCP XML에 편집점 반영

### 검증 방법
- 무음이 포함된 테스트 영상으로 확인
- FCP에서 무음 구간이 잘려있는지 확인

---

## Phase 5: 중복 말 감지/제거
**목표**: 반복되는 말(NG 테이크)을 감지하고 제거

### 작업 내용
- [ ] TextAnalyzer 구현
  - [ ] 문장 유사도 비교
  - [ ] 필러 워드 감지 (음, 어, 그...)
- [ ] DuplicateStage 파이프라인 단계

### 검증 방법
- 같은 말을 여러 번 반복한 테스트 영상
- 최적의 테이크만 남았는지 확인

---

## 현재 진행 상황

| Phase | 상태 | 비고 |
|-------|------|------|
| Phase 1 | ✅ 완료 | MediaService, CLI 구현 완료 |
| Phase 2 | 🔄 진행 중 | 싱크 기능 구현 |
| Phase 3 | ⏳ 대기 | |
| Phase 4 | ⏳ 대기 | |
| Phase 5 | ⏳ 대기 | |

---

## 기술 스택
- **Backend**: Python 3.11+ / FastAPI
- **UI**: Gradio (PoC)
- **미디어 처리**: FFmpeg (ffmpeg-python)
- **음성인식**: Whisper / faster-whisper
- **내보내기**: FCPXML, Premiere XML
