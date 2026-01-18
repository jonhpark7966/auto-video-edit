# Auto Video Edit (AVID)

자동 영상 편집 파이프라인 - PoC

## 기능

- **무음 구간 자동 감지 및 제거**
- **음성 인식 (Whisper)**
- **중복 발화 감지**
- **Final Cut Pro / Premiere Pro XML 내보내기**

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
│           ├── services/  # 서비스 인터페이스
│           └── export/    # 타임라인 내보내기
├── docker/                # Docker 설정
└── README.md
```

## 파이프라인 단계 (구현 예정)

1. **Sync** - 영상/오디오 싱크 맞추기
2. **Transcribe** - Whisper 음성 인식
3. **Silence** - 무음 구간 감지/제거
4. **Duplicate** - 중복 발화 감지/제거

## 라이선스

CC BY-NC-SA 4.0 (비상업적 용도로만 사용 가능)
