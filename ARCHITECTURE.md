# AVID 아키텍처 설계

이 문서는 사용자 요구사항을 바탕으로 재설계된 AVID 아키텍처를 정의합니다.

---

## 핵심 요구사항 (2026-01-28)

### 1. 무음 감지 (FFmpeg + SRT)
- ✅ FFmpeg silencedetect 필수
- ✅ SRT 기반 갭 분석 필수
- ✅ 결합 모드: `or` + `tight` 옵션만 유지
- ✅ 스킬이 아닌 **코드로 구현** (백엔드 서비스)
- ✅ 실패 시 사용자에게 명확한 에러 메시지
- ❌ 규칙 기반 Fallback 불필요

### 2. 자막 기반 편집 결정 (Multi-AI, CLI 기반)
- ✅ `claude` CLI + `codex` CLI로 호출 (API SDK 아님)
- ✅ skillthon 서브모듈의 스킬을 로컬 CLI에 설치하여 직접 호출
- ✅ 두 AI의 의견을 합쳐서 결정
- ✅ 최종 결정자: Claude (기본값, 변경 가능)
- ✅ 향후 다른 CLI 도구 추가 예정 (확장 가능한 구조)
- ✅ 실패 시 사용자에게 알림

### 3. 음성 인식 (Whisper + 확장)
- ✅ Whisper로 자동 자막 생성
- ✅ Transcription Engine 교체 가능 (플러그인 구조)
- ✅ 향후 다른 엔진 추가 예정 (플러그인 구조)

### 4. 테스트 & 평가
- ✅ 각 로직마다 테스트 가능
- ✅ Evaluation 프레임워크 구축
- ✅ FCPXML 기반 평가: 편집 전/후 FCPXML을 비교하여 자동 평가
- ✅ 무음 감지, 의미단위 컷편집 각각 별도 평가
- ✅ 스킬을 바꿔가며 반복 평가 → 품질 개선 루프
- ✅ 문서화 (테스트 방법, 평가 기준)

### 5. 향후 확장
- ✅ 화면 기반 편집 (Scene Detection)
- ✅ 음성 기반 편집 (Speaker Diarization, Emotion Detection)
- ✅ 얼굴 인식 기반 편집

### 6. 품질 우선
- ✅ 정확도 > 속도
- ✅ 주요 사용 사례: 인터뷰, 강의, 팟캐스트
- ✅ 언어: 한국어 우선, 향후 다국어 지원

---

## 아키텍처 개요

### 레이어 구조

```
┌─────────────────────────────────────────────────────────┐
│                     UI Layer (Streamlit)                 │
│  - 파일 업로드, 옵션 설정, 진행률 표시, 결과 다운로드    │
└─────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────┐
│                  Pipeline Layer (Orchestration)          │
│  - PipelineExecutor: 스테이지 순차 실행                  │
│  - PipelineContext: 공유 상태 관리                       │
│  - 진행률 콜백, 에러 핸들링, 롤백                        │
└─────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────┐
│                   Stage Layer (Processing)               │
│  - TranscribeStage: 음성 → 텍스트                       │
│  - SilenceDetectionStage: 무음 감지                     │
│  - SubtitleAnalysisStage: 자막 분석 (Multi-AI)          │
│  - SceneDetectionStage: 화면 변화 감지 (향후)           │
│  - SpeakerDiarizationStage: 화자 분리 (향후)            │
└─────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────┐
│                  Service Layer (Business Logic)          │
│  - TranscriptionService: 음성 인식 (플러그인)            │
│  - AudioAnalyzer: 오디오 분석 (FFmpeg)                  │
│  - AIAnalysisService: AI 기반 분석 (플러그인)           │
│  - VideoAnalyzer: 비디오 분석 (향후)                    │
│  - MediaService: 미디어 처리 (FFmpeg)                   │
└─────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────┐
│                  Provider Layer (CLI Tools)              │
│  - Transcription Providers:                              │
│    - WhisperProvider (기본)                             │
│    - (향후 확장 가능한 플러그인 구조)                    │
│  - AI Analysis Providers (CLI 기반):                     │
│    - ClaudeProvider (claude CLI)                        │
│    - CodexProvider (codex CLI)                          │
│    - (향후 CLI 도구 추가 가능)                          │
└─────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────┐
│                  Evaluation Layer (FCPXML 기반)           │
│  - FCPXMLComparator: 편집 전/후 FCPXML 비교             │
│  - GroundTruthManager: 정답 FCPXML 관리                 │
│  - EvaluationRunner: 컴포넌트별 평가 실행               │
│  - ReportGenerator: 평가 리포트 생성                    │
└─────────────────────────────────────────────────────────┘
```

---

## 핵심 컴포넌트 설계

### 1. 무음 감지 서비스 (AudioAnalyzer)

**위치**: `apps/backend/src/avid/services/audio_analyzer.py`

**책임**:
- FFmpeg silencedetect 실행
- SRT 기반 갭 분석
- 두 결과를 `or` + `tight` 모드로 결합

**인터페이스**:
```python
class AudioAnalyzer:
    async def detect_silence(
        self,
        audio_path: Path,
        srt_path: Path | None = None,
        min_silence_ms: int = 500,
        silence_threshold_db: float = -40.0,
        padding_ms: int = 100,
        tight_mode: bool = True,  # tight 옵션
    ) -> SilenceDetectionResult:
        """무음 구간 감지 (FFmpeg + SRT)
        
        Args:
            audio_path: 오디오 파일 경로
            srt_path: SRT 파일 경로 (선택)
            min_silence_ms: 최소 무음 길이
            silence_threshold_db: 무음 임계값
            padding_ms: 패딩 (음성 전후)
            tight_mode: True면 겹치는 부분만, False면 합집합
        
        Returns:
            SilenceDetectionResult with:
            - silence_regions: List[SilenceRegion]
            - statistics: 통계 정보
            - ffmpeg_regions: FFmpeg 결과 (디버깅용)
            - srt_gaps: SRT 갭 (디버깅용)
        
        Raises:
            FFmpegError: FFmpeg 실행 실패
            SRTParseError: SRT 파싱 실패
        """
```

**구현 세부사항**:
```python
class AudioAnalyzer:
    def __init__(self):
        self._ffmpeg_analyzer = FFmpegSilenceDetector()
        self._srt_parser = SRTGapAnalyzer()
        self._combiner = SilenceCombiner()
    
    async def detect_silence(self, ...) -> SilenceDetectionResult:
        # 1. FFmpeg silencedetect 실행
        try:
            ffmpeg_regions = await self._ffmpeg_analyzer.detect(
                audio_path, min_silence_ms, silence_threshold_db
            )
        except subprocess.CalledProcessError as e:
            raise FFmpegError(f"FFmpeg failed: {e.stderr}") from e
        
        # 2. SRT 갭 분석 (선택)
        srt_gaps = []
        if srt_path:
            try:
                srt_gaps = self._srt_parser.detect_gaps(
                    srt_path, padding_ms
                )
            except Exception as e:
                raise SRTParseError(f"SRT parsing failed: {e}") from e
        
        # 3. 결합 (or + tight)
        if tight_mode:
            # 겹치는 부분만 (교집합)
            combined = self._combiner.intersect(ffmpeg_regions, srt_gaps)
        else:
            # 합집합
            combined = self._combiner.union(ffmpeg_regions, srt_gaps)
        
        # 4. 결과 반환
        return SilenceDetectionResult(
            silence_regions=combined,
            statistics=self._calculate_stats(combined, audio_duration),
            ffmpeg_regions=ffmpeg_regions,  # 디버깅용
            srt_gaps=srt_gaps,  # 디버깅용
        )
```

**에러 처리**:
```python
class FFmpegError(Exception):
    """FFmpeg 실행 실패"""
    pass

class SRTParseError(Exception):
    """SRT 파싱 실패"""
    pass

# 사용 예시
try:
    result = await audio_analyzer.detect_silence(audio_path, srt_path)
except FFmpegError as e:
    # 사용자에게 명확한 에러 메시지
    st.error(f"FFmpeg 실행 실패: {e}")
    st.info("FFmpeg가 설치되어 있는지 확인해주세요.")
except SRTParseError as e:
    st.error(f"자막 파일 파싱 실패: {e}")
    st.info("SRT 파일 형식을 확인해주세요.")
```

---

### 2. AI 분석 서비스 (Multi-Provider, CLI 기반)

**핵심 원칙**: Claude와 Codex는 **CLI 도구**로 호출한다 (API SDK가 아님).
- `claude` CLI = Claude Code (환경에 설치된 CLI)
- `codex` CLI = Codex CLI (환경에 설치된 CLI)
- API 키 직접 관리 불필요 — CLI가 인증을 처리함
- skillthon 서브모듈의 스킬을 로컬 CLI에 설치하여 직접 호출

**위치**: `apps/backend/src/avid/services/ai_analysis/`

**구조**:
```
ai_analysis/
├── __init__.py
├── base.py              # IAIProvider 인터페이스
├── providers/
│   ├── __init__.py
│   ├── claude.py        # ClaudeProvider (claude CLI)
│   └── codex.py         # CodexProvider (codex CLI)
├── aggregator.py        # 여러 AI 결과 합치기
└── service.py           # AIAnalysisService (메인)
```

**CLI 호출 패턴** (skillthon 스킬을 설치한 후 호출):
```python
# Claude Code CLI 호출 (설치된 subtitle-cut 스킬 활용)
result = subprocess.run(
    ["claude", "-p", prompt, "--output-format", "text"],
    capture_output=True, text=True, timeout=120,
)

# Codex CLI 호출
result = subprocess.run(
    ["codex", "--quiet", "--approval-mode", "full-auto", "-p", prompt],
    capture_output=True, text=True, timeout=120,
)
```

**인터페이스**:
```python
class IAIProvider(Protocol):
    async def analyze_subtitles(
        self,
        segments: list[SubtitleSegment],
        options: dict[str, Any],
    ) -> AIAnalysisResult: ...
    
    @property
    def name(self) -> str: ...
    
    @property
    def is_available(self) -> bool:
        """CLI 바이너리가 설치되어 있는지 확인"""
        ...
```

**구현 예시**:
```python
# providers/claude.py — Claude Code CLI 사용
import shutil
import subprocess

class ClaudeProvider:
    def __init__(self):
        self._available = shutil.which("claude") is not None
    
    async def analyze_subtitles(self, segments, options) -> AIAnalysisResult:
        if not self._available:
            raise AIProviderError("claude CLI not found")
        
        prompt = self._build_prompt(segments, options)
        
        result = await asyncio.to_thread(
            subprocess.run,
            ["claude", "-p", prompt, "--output-format", "text"],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            raise AIProviderError(f"claude CLI failed: {result.stderr}")
        
        return self._parse_response(result.stdout)
    
    @property
    def is_available(self) -> bool:
        return self._available

# providers/codex.py — Codex CLI 사용
class CodexProvider:
    def __init__(self):
        self._available = shutil.which("codex") is not None
    
    async def analyze_subtitles(self, segments, options) -> AIAnalysisResult:
        if not self._available:
            raise AIProviderError("codex CLI not found")
        
        prompt = self._build_prompt(segments, options)
        
        result = await asyncio.to_thread(
            subprocess.run,
            ["codex", "--quiet", "--approval-mode", "full-auto", "-p", prompt],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            raise AIProviderError(f"codex CLI failed: {result.stderr}")
        
        return self._parse_response(result.stdout)
    
    @property
    def is_available(self) -> bool:
        return self._available
```

**결과 합치기 (Aggregator)**:
```python
class AIResultAggregator:
    def aggregate(
        self,
        results: dict[str, AIAnalysisResult],
        decision_maker: str = "claude",
    ) -> AIAnalysisResult:
        """전략: decision_maker가 동의하거나 과반수가 동의하면 cut"""
        ...
```

**메인 서비스**:
```python
class AIAnalysisService:
    def __init__(self):
        # CLI 바이너리 존재 여부로 자동 검색
        self.providers = self._auto_discover()
    
    def _auto_discover(self):
        candidates = [ClaudeProvider(), CodexProvider()]
        return {p.name: p for p in candidates if p.is_available}
    
    async def analyze(self, segments, provider_names=None, decision_maker="claude"):
        # 선택된 프로바이더 병렬 실행 → 결과 집계
        ...
```

---

### 3. 음성 인식 서비스 (Multi-Provider)

**위치**: `apps/backend/src/avid/services/transcription/`

**구조**:
```
transcription/
├── __init__.py
├── base.py              # ITranscriptionProvider 인터페이스
├── providers/
│   ├── __init__.py
│   └── whisper.py       # WhisperProvider (기본)
└── service.py           # TranscriptionService (메인)
```

**인터페이스**:
```python
# base.py
class ITranscriptionProvider(Protocol):
    """음성 인식 제공자 인터페이스"""
    
    async def transcribe(
        self,
        audio_path: Path,
        language: str | None = None,
        options: dict[str, Any] | None = None,
    ) -> TranscriptionResult:
        """오디오를 텍스트로 변환
        
        Args:
            audio_path: 오디오 파일 경로
            language: 언어 코드 (ko, en, ja 등)
            options: 제공자별 옵션
        
        Returns:
            TranscriptionResult with:
            - text: 전체 텍스트
            - segments: List[TranscriptSegment]
            - language: 감지된 언어
            - confidence: 신뢰도
        
        Raises:
            TranscriptionError: 음성 인식 실패
        """
        ...
    
    @property
    def name(self) -> str:
        """제공자 이름"""
        ...
    
    @property
    def supported_languages(self) -> list[str]:
        """지원 언어 목록"""
        ...
```

**구현 예시**:
```python
# providers/whisper.py
import whisper

class WhisperProvider:
    def __init__(self, model_name: str = "base"):
        self.model_name = model_name
        self.model = None  # Lazy loading
    
    async def transcribe(
        self, audio_path, language=None, options=None
    ) -> TranscriptionResult:
        # 1. 모델 로드 (lazy)
        if self.model is None:
            self.model = whisper.load_model(self.model_name)
        
        # 2. 음성 인식
        try:
            result = self.model.transcribe(
                str(audio_path),
                language=language,
                **options or {}
            )
        except Exception as e:
            raise TranscriptionError(f"Whisper failed: {e}") from e
        
        # 3. 결과 변환
        segments = [
            TranscriptSegment(
                start_ms=int(seg["start"] * 1000),
                end_ms=int(seg["end"] * 1000),
                text=seg["text"].strip(),
                confidence=seg.get("confidence", 1.0),
            )
            for seg in result["segments"]
        ]
        
        return TranscriptionResult(
            text=result["text"],
            segments=segments,
            language=result["language"],
            confidence=self._calculate_avg_confidence(segments),
        )
    
    @property
    def name(self) -> str:
        return f"whisper-{self.model_name}"
    
    @property
    def supported_languages(self) -> list[str]:
        return ["ko", "en", "ja", "zh", "es", "fr", "de", ...]  # Whisper 지원 언어

```

**메인 서비스**:
```python
# service.py
class TranscriptionService:
    def __init__(self, default_provider: str = "whisper-base"):
        self.providers = {}
        self.default_provider = default_provider
        self._register_providers()
    
    def _register_providers(self):
        """사용 가능한 제공자 등록"""
        try:
            self.providers["whisper-base"] = WhisperProvider("base")
            self.providers["whisper-small"] = WhisperProvider("small")
            self.providers["whisper-medium"] = WhisperProvider("medium")
        except ImportError:
            logger.warning("Whisper not available")
        
        # 향후 추가 엔진은 플러그인으로 등록
    
    async def transcribe(
        self,
        audio_path: Path,
        provider_name: str | None = None,
        language: str | None = None,
        options: dict[str, Any] | None = None,
    ) -> TranscriptionResult:
        """음성 인식
        
        Args:
            audio_path: 오디오 파일
            provider_name: 제공자 이름 (None이면 기본값)
            language: 언어 코드
            options: 제공자별 옵션
        
        Returns:
            TranscriptionResult
        
        Raises:
            TranscriptionError: 음성 인식 실패
        """
        provider_name = provider_name or self.default_provider
        provider = self.providers.get(provider_name)
        
        if not provider:
            available = list(self.providers.keys())
            raise TranscriptionError(
                f"Provider '{provider_name}' not found. "
                f"Available: {available}"
            )
        
        try:
            return await provider.transcribe(audio_path, language, options)
        except Exception as e:
            raise TranscriptionError(
                f"Transcription failed with {provider_name}: {e}"
            ) from e
```

---

### 4. 평가 프레임워크 (FCPXML 기반 Evaluation)

**핵심 원칙**: 편집 결과는 FCPXML로 표현되므로, 평가도 FCPXML 비교로 수행한다.

**평가 단위**:
- 무음 감지 → FCPXML (무음 컷 결과)
- 의미단위 컷편집 → FCPXML (자막 기반 컷 결과)
- 각각 별도로 평가

**평가 흐름**:
```
1. 원본 영상 + 정답 FCPXML (사람이 편집한 결과) 준비
2. 스킬 실행 → 결과 FCPXML 생성
3. 정답 FCPXML vs 결과 FCPXML 자동 비교
4. 메트릭 산출
5. 스킬 변경 → 2번부터 반복 (품질 개선 루프)
```

**위치**: `apps/backend/src/avid/evaluation/`

**구조**:
```
evaluation/
├── __init__.py
├── fcpxml_comparator.py  # FCPXML 편집 전/후 비교
├── ground_truth.py       # 정답 FCPXML 관리
├── runner.py             # 컴포넌트별 평가 실행
└── report.py             # 리포트 생성
```

**정답 데이터 형식**:
```
test_data/
├── cases/
│   ├── interview_01/
│   │   ├── source.mp4                    # 원본 영상
│   │   ├── source.srt                    # 원본 자막
│   │   ├── ground_truth_silence.fcpxml   # 사람이 편집한 무음 컷 결과
│   │   ├── ground_truth_subtitle.fcpxml  # 사람이 편집한 의미단위 컷 결과
│   │   └── metadata.json                 # 영상 메타 (장르, 언어 등)
│   ├── lecture_01/
│   │   └── ...
│   └── podcast_01/
│       └── ...
```

**FCPXML 비교 방식**:
```python
# fcpxml_comparator.py
class FCPXMLComparator:
    def compare(
        self,
        predicted_fcpxml: Path,
        ground_truth_fcpxml: Path,
    ) -> ComparisonResult:
        """두 FCPXML의 편집 결정을 비교
        
        1. 양쪽 FCPXML에서 편집 구간(컷/유지) 추출
        2. 시간축 기준으로 구간 매칭
        3. 일치/불일치 구간 산출
        
        Returns:
            ComparisonResult with:
            - matched_cuts: 정답과 일치하는 컷 구간
            - missed_cuts: 정답에는 있지만 빠뜨린 컷 구간
            - extra_cuts: 정답에 없는데 추가된 컷 구간
            - timeline_overlap_ratio: 전체 타임라인 일치 비율
        """
```

**평가 실행**:
```python
# runner.py
class EvaluationRunner:
    async def evaluate_silence_detection(
        self,
        test_case_dir: Path,
    ) -> EvaluationReport:
        """무음 감지 평가
        
        1. 스킬 실행 → 결과 FCPXML 생성
        2. ground_truth_silence.fcpxml와 비교
        3. 메트릭 산출
        """

    async def evaluate_subtitle_cut(
        self,
        test_case_dir: Path,
    ) -> EvaluationReport:
        """의미단위 컷편집 평가
        
        1. 스킬 실행 → 결과 FCPXML 생성
        2. ground_truth_subtitle.fcpxml와 비교
        3. 메트릭 산출
        """

    async def run_all(
        self,
        test_cases: list[Path],
    ) -> list[EvaluationReport]:
        """모든 테스트 케이스에 대해 평가 실행 → 종합 리포트"""
```

---

### 5. 향후 확장 (화면/음성 기반 편집)

**Scene Detection (화면 변화 감지)**:
```python
# services/video_analyzer.py
class VideoAnalyzer:
    async def detect_scenes(
        self,
        video_path: Path,
        threshold: float = 0.3,
    ) -> list[SceneChange]:
        """화면 변화 감지
        
        Args:
            video_path: 비디오 파일
            threshold: 변화 임계값 (0-1)
        
        Returns:
            List[SceneChange] with timestamp_ms
        
        구체적 라이브러리는 향후 결정
        """
        ...
```

**Speaker Diarization (화자 분리)**:
```python
# services/speaker_analyzer.py
class SpeakerAnalyzer:
    async def diarize(
        self,
        audio_path: Path,
    ) -> list[SpeakerSegment]:
        """화자 분리
        
        Args:
            audio_path: 오디오 파일
        
        Returns:
            List[SpeakerSegment] with:
            - start_ms, end_ms
            - speaker_id (0, 1, 2, ...)
            - confidence
        
        구체적 라이브러리는 향후 결정
        """
        ...
```

**Emotion Detection (감정 인식)**:
```python
# services/emotion_analyzer.py
class EmotionAnalyzer:
    async def detect_emotions(
        self,
        audio_path: Path,
    ) -> list[EmotionSegment]:
        """감정 인식
        
        Args:
            audio_path: 오디오 파일
        
        Returns:
            List[EmotionSegment] with:
            - start_ms, end_ms
            - emotion (happy, sad, angry, neutral)
            - confidence
        
        구체적 라이브러리는 향후 결정
        """
        ...
```

---

## 테스트 전략

### 단위 테스트
```python
# tests/services/test_audio_analyzer.py
def test_ffmpeg_silence_detection():
    analyzer = AudioAnalyzer()
    result = await analyzer.detect_silence(
        audio_path="test_data/audio/silence_test.wav",
        min_silence_ms=500,
        silence_threshold_db=-40.0,
    )
    assert len(result.silence_regions) > 0

# tests/services/test_ai_analysis.py
@pytest.mark.asyncio
async def test_claude_provider(mocker):
    # claude CLI 응답을 mock
    mock_response = '{"cuts": [{"index": 1, "reason": "duplicate"}]}'
    mocker.patch('subprocess.run', return_value=Mock(
        stdout=mock_response, returncode=0
    ))
    
    provider = ClaudeProvider()
    segments = [
        SubtitleSegment(start_ms=0, end_ms=1000, text="안녕하세요"),
        SubtitleSegment(start_ms=1000, end_ms=2000, text="안녕하세요"),
    ]
    result = await provider.analyze_subtitles(segments, {})
    assert len(result.cuts) == 1
```

### 통합 테스트
```python
# tests/integration/test_full_pipeline.py
@pytest.mark.asyncio
async def test_full_pipeline():
    # 1. 음성 인식
    transcription_service = TranscriptionService()
    transcription = await transcription_service.transcribe(
        audio_path="test_data/audio/interview.wav",
        language="ko",
    )
    
    # 2. 무음 감지
    audio_analyzer = AudioAnalyzer()
    silence_result = await audio_analyzer.detect_silence(
        audio_path="test_data/audio/interview.wav",
        srt_path=None,  # 자막 없음
    )
    
    # 3. AI 분석
    ai_service = AIAnalysisService()  # CLI 자동 검색
    ai_result = await ai_service.analyze(
        segments=transcription.segments,
    )
    
    # 4. 프로젝트 생성
    project = Project(name="Test")
    # ... (생략)
    
    # 5. FCPXML 내보내기
    exporter = FCPXMLExporter()
    await exporter.export(project, "output.fcpxml")
    
    # 6. 검증
    assert Path("output.fcpxml").exists()
```

### 평가 테스트
```python
# tests/evaluation/test_fcpxml_comparator.py
def test_silence_evaluation():
    comparator = FCPXMLComparator()
    
    result = comparator.compare(
        predicted_fcpxml="output/silence_result.fcpxml",
        ground_truth_fcpxml="test_data/cases/interview_01/ground_truth_silence.fcpxml",
    )
    
    # 컷 구간 일치율 확인
    assert result.timeline_overlap_ratio > 0.8
    assert len(result.missed_cuts) == 0  # 빠뜨린 컷 없음
    assert len(result.extra_cuts) <= 2   # 불필요한 컷 최소화
```

---

## 문서화

### 사용자 문서
- `docs/USER_GUIDE.md`: 사용자 가이드
- `docs/API.md`: API 문서
- `docs/EVALUATION.md`: FCPXML 기반 평가 방법

### 개발자 문서
- `docs/ARCHITECTURE.md`: 이 문서
- `docs/PLUGIN_DEVELOPMENT.md`: 플러그인 개발 가이드
- `docs/TESTING.md`: 테스트 가이드

---

## 다음 단계

### Phase 1: 핵심 서비스 구현 (1주)
1. AudioAnalyzer 구현 (FFmpeg + SRT)
2. AIAnalysisService 구현 (Claude + Codex)
3. TranscriptionService 구현 (Whisper)
4. 단위 테스트 작성

### Phase 2: 파이프라인 통합 (3일)
1. SilenceDetectionStage 구현
2. SubtitleAnalysisStage 구현
3. TranscribeStage 구현
4. 통합 테스트 작성

### Phase 3: 평가 프레임워크 (3일)
1. FCPXMLComparator 구현 (편집 전/후 FCPXML 비교)
2. GroundTruth FCPXML 관리
3. EvaluationRunner 구현 (컴포넌트별 평가)
4. 테스트 데이터 준비 (정답 FCPXML 포함)

### Phase 4: UI 구현 (2일)
1. Streamlit UI 기본 구조
2. 파일 업로드 및 옵션 설정
3. 진행률 표시
4. 결과 다운로드

### Phase 5: 문서화 및 배포 (2일)
1. 사용자 가이드 작성
2. API 문서 작성
3. FCPXML 기반 평가 방법 문서 작성
4. Docker 이미지 빌드
