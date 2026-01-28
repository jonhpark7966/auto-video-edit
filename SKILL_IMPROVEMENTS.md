# 스킬 개선 계획

이 문서는 기존 스킬(detect-silence, subtitle-cut)의 문제점과 개선 방안을 정리합니다.

---

## 1. detect-silence 스킬 분석

### 📊 현재 구현 상태

**파일**: `skillthon/detect-silence/skills/detect-silence/scripts/detect_silence.py`
**크기**: 972줄
**복잡도**: 높음

**주요 컴포넌트**:
```python
# 클래스 구조
- TimeRange: 시간 범위 모델
- TranscriptSegment: 자막 세그먼트 모델
- SilenceCombineMode: 결합 모드 enum (ffmpeg, srt, and, or, diff)
- SilenceDetectionConfig: 설정 모델
- SilenceRegion: 무음 구간 모델
- SilenceDetectionResult: 결과 모델

# 핵심 로직
- FFmpegAudioAnalyzer: FFmpeg silencedetect 실행 및 파싱
- SrtParser: SRT 파일 파싱 및 갭 분석
- SilenceCombiner: FFmpeg + SRT 결과 결합 (5가지 모드)
```

### 🔍 검증 필요 사항

#### 1.1. FFmpeg silencedetect 파싱 정확도
**우려 사항**:
- FFmpeg stderr 출력 파싱이 정규식 기반
- FFmpeg 버전별 출력 형식 차이 가능성
- 부동소수점 파싱 오류 가능성

**테스트 케이스**:
```bash
# 테스트 1: 기본 케이스
ffmpeg -i video.mp4 -af silencedetect=noise=-40dB:d=0.5 -f null -

# 테스트 2: 매우 짧은 무음 (< 100ms)
# 테스트 3: 매우 긴 무음 (> 10초)
# 테스트 4: 배경 음악이 있는 경우
# 테스트 5: 노이즈가 많은 경우
```

**검증 방법**:
1. 다양한 오디오 샘플 준비 (5-10개)
2. 수동으로 무음 구간 확인 (Audacity 등)
3. detect-silence 결과와 비교
4. 정확도 측정 (precision, recall)

#### 1.2. SRT 갭 분석 정확도
**우려 사항**:
- SRT 타이밍이 부정확한 경우 (Whisper 자동 생성 등)
- 자막이 겹치는 경우
- 자막이 없는 구간 (인트로, 아웃트로)

**테스트 케이스**:
```bash
# 테스트 1: 정확한 SRT (수동 작성)
# 테스트 2: Whisper 자동 생성 SRT
# 테스트 3: 타이밍이 부정확한 SRT (±500ms 오차)
# 테스트 4: 겹치는 자막
# 테스트 5: 긴 갭이 있는 SRT (> 5초)
```

#### 1.3. 결합 모드 비교
**5가지 모드**:
- `ffmpeg`: FFmpeg만 (기본값)
- `srt`: SRT 갭만
- `and`: 둘 다 동의 (보수적, 높은 신뢰도)
- `or`: 둘 중 하나 (공격적, 더 많이 잡음)
- `diff`: 불일치 구간 (수동 검토용)

**검증 질문**:
- 각 모드의 실제 사용 사례는?
- `and` 모드가 너무 보수적이지 않은가?
- `or` 모드가 너무 공격적이지 않은가?
- `diff` 모드의 실용성은?

**테스트 방법**:
1. 동일한 비디오에 5가지 모드 적용
2. 결과 비교 (무음 구간 수, 총 길이)
3. 실제 편집 결과 확인 (FCP에서)
4. 최적 모드 결정

#### 1.4. 성능 문제
**우려 사항**:
- FFmpeg를 여러 번 호출하는가?
- 큰 파일 처리 시 메모리 사용량은?
- 처리 속도는 실시간 대비 몇 배인가?

**측정 항목**:
```python
# 테스트 비디오: 10분, 30분, 1시간
- 처리 시간 (초)
- 메모리 사용량 (MB)
- FFmpeg 호출 횟수
- 중간 파일 생성 여부
```

### 🐛 예상 문제점

#### 문제 1: FFmpeg 버전 의존성
**증상**: FFmpeg 버전에 따라 silencedetect 출력 형식이 다를 수 있음

**재현 방법**:
```bash
# FFmpeg 4.x vs 5.x vs 6.x
ffmpeg -version
ffmpeg -i test.mp4 -af silencedetect=noise=-40dB:d=0.5 -f null - 2>&1 | grep silence
```

**해결 방안**:
- Option 1: FFmpeg 최소 버전 명시 (예: 5.0+)
- Option 2: 여러 출력 형식 지원 (정규식 여러 개)
- Option 3: FFmpeg Python 바인딩 사용 (ffmpeg-python)

#### 문제 2: 에러 핸들링 부족
**증상**: FFmpeg 실패 시 크래시

**예상 시나리오**:
- FFmpeg가 설치되지 않음
- 파일 경로에 특수문자 (공백, 한글 등)
- 손상된 미디어 파일
- 권한 문제

**해결 방안**:
```python
try:
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg failed: {result.stderr}")
except FileNotFoundError:
    raise RuntimeError("FFmpeg not found. Please install FFmpeg.")
except subprocess.TimeoutExpired:
    raise RuntimeError("FFmpeg timeout (> 5 minutes)")
except Exception as e:
    raise RuntimeError(f"Unexpected error: {e}")
```

#### 문제 3: 복잡한 코드 구조
**증상**: 972줄의 단일 파일, 유지보수 어려움

**개선 방안**:
```
# 파일 분리
detect_silence/
├── models.py          # Pydantic 모델
├── ffmpeg_analyzer.py # FFmpeg 관련
├── srt_parser.py      # SRT 관련
├── combiner.py        # 결합 로직
├── cli.py             # CLI 진입점
└── __init__.py
```

#### 문제 4: 테스트 없음
**증상**: 단위 테스트, 통합 테스트 없음

**필요한 테스트**:
```python
# tests/test_ffmpeg_analyzer.py
def test_parse_silence_output():
    stderr = "[silencedetect @ 0x...] silence_start: 1.234\n..."
    analyzer = FFmpegAudioAnalyzer()
    ranges = analyzer._parse_silence_output(stderr)
    assert len(ranges) == 1
    assert ranges[0].start_ms == 1234

# tests/test_srt_parser.py
def test_parse_srt():
    srt_content = "1\n00:00:01,000 --> 00:00:03,000\nHello\n\n"
    parser = SrtParser()
    segments = parser.parse_srt(srt_content)
    assert len(segments) == 1
    assert segments[0].start_ms == 1000

# tests/test_combiner.py
def test_combine_and_mode():
    ffmpeg_ranges = [TimeRange(1000, 2000)]
    srt_gaps = [TimeRange(1500, 2500)]
    combiner = SilenceCombiner()
    result = combiner.combine(ffmpeg_ranges, srt_gaps, mode="and")
    # 겹치는 부분만: 1500-2000
    assert len(result) == 1
    assert result[0].start_ms == 1500
    assert result[0].end_ms == 2000
```

---

## 2. subtitle-cut 스킬 분석

### 📊 현재 구현 상태

**파일**: `skillthon/subtitle-cut-detector/skills/subtitle-cut/`
**구조**:
```
subtitle-cut/
├── main.py              # CLI 진입점, 프로젝트 JSON 생성
├── claude_analyzer.py   # Claude CLI 호출
├── srt_parser.py        # SRT 파싱
├── video_info.py        # ffprobe 비디오 정보
└── __init__.py
```

**핵심 로직**:
```python
# claude_analyzer.py
def analyze_with_claude(segments):
    # Claude CLI 호출 (subprocess)
    result = subprocess.run(["claude", "-p", prompt, ...])
    # JSON 파싱
    data = parse_claude_response(result.stdout)
    # cuts, keeps 분류
    return ClaudeAnalysisResult(cuts=cuts, keeps=keeps)
```

### 🔍 검증 필요 사항

#### 2.1. Claude 분석 정확도
**우려 사항**:
- Claude가 항상 정확한 판단을 하는가?
- 프롬프트가 충분히 명확한가?
- 엣지 케이스 처리는?

**테스트 케이스**:
```bash
# 테스트 1: 명확한 중복 (같은 인트로 3번)
# 테스트 2: 미묘한 중복 (비슷하지만 다른 내용)
# 테스트 3: 불완전한 문장 ("그래서...", "음...")
# 테스트 4: 필러 워드 ("어", "음", "그...")
# 테스트 5: 짧은 세그먼트 (< 2초)
# 테스트 6: 긴 세그먼트 (> 30초)
```

**검증 방법**:
1. 다양한 자막 샘플 준비 (10-20개)
2. 수동으로 중복/불완전 구간 표시
3. Claude 분석 결과와 비교
4. 정확도 측정 (precision, recall, F1)

#### 2.2. Claude CLI 의존성
**문제**: Claude CLI가 없으면 크래시

**시나리오**:
```bash
# Claude CLI 없을 때
$ python main.py video.srt video.mp4
FileNotFoundError: [Errno 2] No such file or directory: 'claude'

# Claude API 실패 시
$ python main.py video.srt video.mp4
RuntimeError: Claude CLI error: API rate limit exceeded
```

**해결 방안**:
- `claude` CLI가 설치되어 있는지 `shutil.which("claude")`로 확인
- 설치 안 되어 있으면 사용자에게 에러 메시지 표시 (fallback 없음)
- 에러 메시지 예: "claude CLI가 설치되어 있지 않습니다. Claude Code를 설치해주세요."

#### 2.3. 에러 핸들링 부족
**문제**: subprocess 실패 시 크래시

**예상 시나리오**:
- Claude CLI timeout (> 2분)
- Claude API rate limit
- 잘못된 JSON 응답
- 네트워크 오류

**해결 방안**:
```python
def call_claude(prompt: str) -> str:
    try:
        result = subprocess.run(
            ["claude", "-p", prompt, "--output-format", "text"],
            capture_output=True,
            text=True,
            timeout=120,  # 2분 타임아웃
        )
        if result.returncode != 0:
            raise RuntimeError(f"Claude CLI error: {result.stderr}")
        return result.stdout.strip()
    except FileNotFoundError:
        raise RuntimeError(
            "Claude CLI not found. Please install: pip install claude-code"
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("Claude CLI timeout (> 2 minutes)")
    except Exception as e:
        raise RuntimeError(f"Unexpected error: {e}")

def parse_claude_response(response: str) -> dict:
    try:
        start = response.find("{")
        end = response.rfind("}") + 1
        if start == -1 or end == 0:
            raise ValueError("No JSON found in response")
        json_str = response[start:end]
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON: {e}\nResponse: {response[:500]}")
```

#### 2.4. 프롬프트 개선
**현재 프롬프트**:
```python
ANALYSIS_PROMPT = '''당신은 영상 편집 전문가입니다. 아래 자막 세그먼트들을 분석해서 어떤 부분을 잘라야 하는지 판단해주세요.

## 자막 세그먼트들:
{segments}

## 판단 기준:
1. **중복 (duplicate)**: 같은 내용을 여러 번 말한 경우...
2. **불완전 (incomplete)**: 문장이 중간에 끊기거나...
3. **필러 (filler)**: 의미 없는 말, 망설임...
'''
```

**개선 방안**:
- Few-shot examples 추가
- 더 명확한 기준 제시
- 엣지 케이스 명시

**개선된 프롬프트**:
```python
ANALYSIS_PROMPT = '''당신은 영상 편집 전문가입니다. 아래 자막 세그먼트들을 분석해서 어떤 부분을 잘라야 하는지 판단해주세요.

## 자막 세그먼트들:
{segments}

## 판단 기준:
1. **중복 (duplicate)**: 같은 내용을 여러 번 말한 경우
   - 예시: "안녕하세요" (3번) → 가장 완성도 높은 것 1개만 유지
   - 주의: 비슷해 보여도 내용이 다르면 중복 아님

2. **불완전 (incomplete)**: 문장이 중간에 끊긴 경우
   - 예시: "그래서 제가...", "음... 이제..."
   - 조사로 끝남: "하는", "이제", "그래서"

3. **필러 (filler)**: 의미 없는 말, 망설임
   - 예시: "어...", "음...", "그..."
   - 너무 짧은 세그먼트 (< 2초, < 10자)

## Few-shot Examples:

### Example 1: 중복 인트로
Input:
[1] (0s-5s): "안녕하세요. 오늘은..."
[2] (6s-8s): "안녕하세요."
[3] (10s-18s): "안녕하세요. 오늘은 D2SF에 대해 말씀드리겠습니다."

Output:
- [1] cut (duplicate, segment 3이 더 완성도 높음)
- [2] cut (duplicate, segment 3이 더 완성도 높음)
- [3] keep (best_take)

### Example 2: 불완전한 문장
Input:
[1] (0s-2s): "그래서 제가..."
[2] (3s-10s): "그래서 제가 오늘 말씀드릴 내용은..."

Output:
- [1] cut (incomplete)
- [2] keep (complete)

## 출력 형식 (JSON):
```json
{
  "analysis": [
    {
      "segment_index": 1,
      "action": "cut",
      "reason": "duplicate",
      "note": "segment 3의 인트로가 더 완성도 높음"
    },
    ...
  ]
}
```

JSON만 출력하세요.'''
```

### 🐛 예상 문제점

#### 문제 1: Claude CLI 처리 비용
**증상**: Claude CLI 호출 시 내부적으로 API 비용이 발생할 수 있음

**해결 방안**:
- 캐싱 (같은 자막은 재분석 안함)
- 배치 처리 (여러 영상 한 번에)

#### 문제 2: 느린 처리 속도
**증상**: Claude CLI 호출이 느림 (5-10초)

**측정**:
```python
import time

start = time.time()
result = analyze_with_claude(segments)
elapsed = time.time() - start
print(f"Claude analysis took {elapsed:.2f}s")
```

**해결 방안**:
- 비동기 처리 (async/await)
- 진행률 표시 (사용자 경험 개선)
- 백그라운드 작업 (UI 블로킹 방지)

#### 문제 3: 테스트 어려움
**증상**: Claude CLI 호출이 필요해서 단위 테스트 어려움

**해결 방안**:
```python
# Mock Claude 응답
def test_analyze_with_claude(mocker):
    mock_response = '''
    {
      "analysis": [
        {"segment_index": 1, "action": "cut", "reason": "duplicate"}
      ]
    }
    '''
    mocker.patch('subprocess.run', return_value=Mock(stdout=mock_response, returncode=0))
    
    segments = [SubtitleSegment(start_ms=0, end_ms=1000, text="test")]
    result = analyze_with_claude(segments)
    
    assert len(result.cuts) == 1
    assert result.cuts[0]["reason"] == "duplicate"
```

---

## 3. 통합 개선 계획

### 3.1. 우선순위 1: 에러 핸들링 (1-2일)

**목표**: 모든 실패 시나리오에 대한 graceful handling

**작업 내용**:
- [ ] detect-silence: FFmpeg 실패 처리
- [ ] detect-silence: 파일 경로 검증
- [ ] subtitle-cut: Claude CLI 실패 처리
- [ ] subtitle-cut: CLI 실패 시 사용자에게 에러 메시지 표시 (fallback 없음)
- [ ] 모든 subprocess 호출에 timeout
- [ ] 사용자 친화적 에러 메시지

### 3.2. 우선순위 2: 테스트 작성 (2-3일)

**목표**: 80% 이상 코드 커버리지

**작업 내용**:
- [ ] detect-silence 단위 테스트
  - [ ] FFmpeg 출력 파싱
  - [ ] SRT 파싱
  - [ ] 결합 로직 (5가지 모드)
- [ ] subtitle-cut 단위 테스트
  - [ ] SRT 파싱
   - [ ] Claude CLI 응답 파싱
- [ ] 통합 테스트
  - [ ] 전체 워크플로우
  - [ ] 샘플 비디오로 end-to-end

### 3.3. 우선순위 3: 성능 최적화 (1-2일)

**목표**: 처리 속도 2배 향상

**작업 내용**:
- [ ] FFmpeg 호출 최소화
- [ ] 중간 결과 캐싱
- [ ] 병렬 처리 (가능한 경우)
- [ ] 비동기 처리 (async/await)

### 3.4. 우선순위 4: 코드 리팩토링 (1-2일)

**목표**: 유지보수성 향상

**작업 내용**:
- [ ] detect-silence 파일 분리 (972줄 → 5개 파일)
- [ ] 공통 코드 추출 (TimeRange, SRT 파싱 등)
- [ ] 타입 힌트 추가
- [ ] Docstring 추가

---

## 4. 검증 계획

### 4.1. 테스트 데이터 준비

**필요한 샘플**:
```
test_data/
├── videos/
│   ├── short_silence.mp4      # 짧은 무음 (< 500ms)
│   ├── long_silence.mp4       # 긴 무음 (> 10s)
│   ├── background_music.mp4   # 배경 음악
│   ├── noisy.mp4              # 노이즈 많음
│   ├── duplicate_intro.mp4    # 중복 인트로
│   └── incomplete.mp4         # 불완전한 문장
├── subtitles/
│   ├── accurate.srt           # 정확한 타이밍
│   ├── whisper_auto.srt       # Whisper 자동 생성
│   ├── inaccurate.srt         # 부정확한 타이밍
│   └── overlapping.srt        # 겹치는 자막
└── ground_truth/
    ├── short_silence.json     # 수동 표시한 무음 구간
    ├── duplicate_intro.json   # 수동 표시한 중복 구간
    └── ...
```

### 4.2. 정확도 측정

**메트릭**:
```python
# Precision: 감지한 것 중 실제 맞는 비율
precision = true_positives / (true_positives + false_positives)

# Recall: 실제 있는 것 중 감지한 비율
recall = true_positives / (true_positives + false_negatives)

# F1 Score: Precision과 Recall의 조화 평균
f1 = 2 * (precision * recall) / (precision + recall)
```

**목표**:
- detect-silence: F1 > 0.85
- subtitle-cut: F1 > 0.80

### 4.3. 성능 측정

**메트릭**:
```python
# 처리 속도 (실시간 대비)
speed_ratio = processing_time / video_duration

# 메모리 사용량
memory_mb = peak_memory_usage / 1024 / 1024

# FFmpeg 호출 횟수
ffmpeg_calls = count_subprocess_calls("ffmpeg")
```

**목표**:
- 처리 속도: < 0.5x (10분 영상을 5분 안에)
- 메모리 사용량: < 500MB
- FFmpeg 호출: < 3회 per video

---

## 5. 다음 단계

### 즉시 실행 (이번 주)
1. ✅ ROADMAP.md 업데이트
2. ✅ SKILL_IMPROVEMENTS.md 작성 (이 문서)
3. 🔄 테스트 데이터 준비
4. 🔄 detect-silence 검증 시작

### 다음 주
1. detect-silence 개선 작업
2. subtitle-cut 개선 작업
3. 테스트 작성
4. 성능 측정

### 2주 후
1. 파이프라인 통합
2. Streamlit UI 완성
3. End-to-end 테스트

---

## 6. 논의 필요 사항

### 질문 1: detect-silence 결합 모드
- 5가지 모드가 모두 필요한가?
- 기본값은 `ffmpeg`가 맞는가?
- `and` vs `or` 중 어느 것이 더 실용적인가?

### 질문 2: subtitle-cut 에러 처리
- ✅ 확정: Claude CLI 실패 시 사용자에게 에러 메시지 표시
- ✅ 확정: 규칙 기반 fallback 없음 (AI 실패 시 사용자 판단)

### 질문 3: 성능 vs 정확도
- 처리 속도를 위해 정확도를 희생할 수 있는가?
- 예: FFmpeg 한 번만 호출 (빠름) vs 여러 번 호출 (정확함)

### 질문 4: 테스트 데이터
- 어떤 종류의 비디오를 테스트해야 하는가?
- 인터뷰? 강의? 브이로그? 게임 플레이?
- 언어는? (한국어, 영어, 일본어?)

---

## 7. 참고 자료

### 관련 문서
- `ROADMAP.md`: 전체 개발 로드맵
- `skillthon/detect-silence/skills/detect-silence/SKILL.md`: detect-silence 스킬 문서
- `skillthon/subtitle-cut-detector/skills/subtitle-cut/SKILL.md`: subtitle-cut 스킬 문서

### 외부 참고
- [FFmpeg silencedetect 문서](https://ffmpeg.org/ffmpeg-filters.html#silencedetect)
- [Auto-Editor](https://github.com/WyattBlue/auto-editor): 유사 프로젝트
- [Unsilence](https://github.com/lagmoellertim/unsilence): FFmpeg 기반 무음 제거
- [Jumpcutter](https://github.com/carykh/jumpcutter): 원조 무음 제거 도구
