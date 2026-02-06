# Auto Video Edit (AVID)

자동 영상 편집 파이프라인 - PoC

## 기능

- **무음 구간 자동 감지 및 제거**
- **음성 인식 (Whisper)**
- **자막 기반 자동 편집 (2가지 모드)**
  - **subtitle-cut**: 강의/설명 영상 — 중복 발화, 필러, 말실수 감지
  - **podcast-cut**: 팟캐스트/인터뷰 — 재미 기준 편집 (지루한 구간 제거, 하이라이트 보존)
- **Final Cut Pro XML (FCPXML) 내보내기**

## 기술 스택

- **Backend**: Python 3.11+ / FastAPI
- **UI**: Gradio (PoC)
- **배포**: Docker Compose

## 시작하기

### 로컬 개발

```bash
cd apps/backend
pip install -e ".[dev]"
python -m avid.main
```

- Gradio UI: http://localhost:8000
- Health Check: http://localhost:8000/health

### Docker Compose

```bash
cd docker
docker-compose up --build
```

## 프로젝트 구조

```
auto-video-edit/
├── apps/
│   └── backend/           # FastAPI + Gradio 백엔드
│       └── src/avid/      # 메인 패키지
│           ├── api/       # REST API
│           ├── ui/        # Gradio UI
│           ├── models/    # Pydantic 데이터 모델
│           ├── pipeline/  # 워크플로우 파이프라인
│           ├── services/  # 서비스 (subtitle_cut, podcast_cut 등)
│           └── export/    # FCPXML/리포트 내보내기
├── skills/
│   ├── _common/           # 스킬 간 공통 모듈 (SRT 파서, CLI 유틸 등)
│   ├── subtitle-cut/      # 강의/설명 영상 편집 스킬
│   └── podcast-cut/       # 팟캐스트/인터뷰 편집 스킬
├── docker/                # Docker 설정
└── README.md
```

## CLI 사용법

```bash
# 무음 감지
avid-cli silence <video> [--srt sub.srt] [-o output.fcpxml]

# 강의/설명 영상 편집 (중복, 필러, 말실수 제거)
avid-cli subtitle-cut <video> --srt sub.srt [-o output.fcpxml]

# 팟캐스트/인터뷰 편집 (재미 기준 — 지루한 구간 제거)
avid-cli podcast-cut <audio> [--srt sub.srt] [-d output_dir] [--final]

# 음성 인식
avid-cli transcribe <video> [-l ko] [-m base] [-o output.srt]

# 편집 결과 평가
avid-cli eval <predicted.fcpxml> <ground-truth.fcpxml>
```

## 라이선스

CC BY-NC-SA 4.0 (비상업적 용도로만 사용 가능)
