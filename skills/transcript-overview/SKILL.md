# transcript-overview

전체 자막을 분석하여 스토리 구조(storyline)를 파악하는 Pass 1 스킬.

## 목적

프로 편집자의 "Paper Edit" 워크플로우를 자동화한다.
전체 내용을 먼저 파악한 뒤, 개별 컷 결정(Pass 2)에 필요한 컨텍스트를 생성한다.

## 분석 항목

1. **narrative_arc**: 콘텐츠 유형, 요약, 전체 흐름, 톤
2. **chapters**: 챕터 분할 (시작/끝 세그먼트, 제목, 요약, 역할, 중요도 1-10)
3. **key_moments**: 핵심 순간 (highlight, emotional_peak, callback, punchline, setup)
4. **dependencies**: 의존성 쌍 (setup-payoff, callback, Q&A, running joke)
5. **pacing_notes**: 느린 구간(지루하지만 필수), 고에너지 구간

## 사용법

```bash
cd skills/transcript-overview
python main.py <srt_file> [--output path] [--content-type {lecture,podcast,auto}]
```

### Options

- `--output, -o` — 출력 경로 (기본: `<srt_stem>.storyline.json`)
- `--content-type` — 콘텐츠 유형 힌트 (기본: auto)

## 출력

`storyline.json` — Pass 2 스킬(subtitle-cut, podcast-cut)의 `--context` 인자로 사용.

## 적응적 처리

세그먼트 수에 따라 자동으로 처리 전략을 선택:

| 세그먼트 수 | 전략 | 설명 |
|------------|------|------|
| ≤150 | Single call (full) | 전체 세그먼트를 한 번에 전송 |
| 151-400 | Single call (compressed) | 인덱스 + 첫 80자 + 타임스탬프 |
| 400+ | Two-step | Step A: 챕터 경계 → Step B: 챕터별 상세 분석 |

## Two-Pass 워크플로우

```
SRT ──→ [Pass 1: transcript-overview] ──storyline.json──→ [Pass 2: subtitle-cut 또는 podcast-cut] ──→ Project JSON
```

```bash
# Pass 1
python skills/transcript-overview/main.py test.srt -o test.storyline.json

# Pass 2 (with context)
python skills/subtitle-cut/main.py test.srt test.mp4 --context test.storyline.json
# or
python skills/podcast-cut/main.py test.srt test.mp4 --context test.storyline.json
```

## Chapter Roles

| Role | 설명 |
|------|------|
| intro | 인트로 / 오프닝 |
| context | 배경 설명 |
| main_topic | 핵심 주제 |
| deep_dive | 심층 분석 |
| tangent | 탈선 / 여담 |
| transition | 전환 |
| climax | 클라이맥스 |
| conclusion | 결론 / 정리 |
| qa | 질의응답 |
| outro | 아웃트로 / 마무리 |

## Dependency Strengths

| Strength | 설명 | 편집 시 |
|----------|------|--------|
| required | 반드시 함께 유지 | 한쪽을 자르면 안 됨 |
| strong | 강력 권장 | 가급적 함께 유지 |
| moderate | 권장 | 개별 판단 가능 |
