# AVID — 로드맵

## 완료

- CLI 4개 명령어: transcribe, transcript-overview, subtitle-cut, podcast-cut
- Two-Pass 편집 워크플로우 (transcript-overview → subtitle-cut / podcast-cut)
- 병렬 chunk 처리 (ThreadPoolExecutor, max_workers=5)
- FCPXML 내보내기 (review / final 모드)
- Markdown 편집 보고서
- Chalna API 비동기 음성 인식
- 데이터 모델 (Project, EditDecision, EditReason — 강의+팟캐스트 통합)
- 프로젝트 문서 정리 (SPEC, ARCHITECTURE, README)

## TODO

### 테스트

- [ ] subtitle-cut 실제 영상 테스트 (≤150 단일 호출 / >150 병렬 chunk)
- [x] podcast-cut 실제 영상 테스트 (≤80 단일 / >80 병렬)
- [x] Two-Pass 워크플로우 end-to-end 테스트
- [ ] FCPXML 출력을 Final Cut Pro에서 검증

### podcast-cut 품질 개선

> 평가 리포트: `tests/e2e/data/20260207_192336/EVAL_REPORT.md`
> 현재 수치 — Duration Precision 21.6%, Recall 50.2%, F1 30.2%

#### Precision 개선 (과잉 편집 줄이기)

- [ ] filler 판단 임계값 상향 — 짧은 호응("네","어","맞아요")을 과도하게 제거함 (113.7s 중 적중 15.7%). 대화 자연스러움 유지를 위해 단독 호응만 자르고, 앞뒤 맥락이 있는 호응은 유지
- [ ] manual/boring score 기준 재조정 — manual 202.2s(적중 15.8%), boring 48.3s(적중 29.5%). 현재 score 4/10도 자르는데, 임계값을 높여서 보수적으로 변경
- [ ] repetitive 판단 개선 — 75.5s(적중 15.3%). 대화에서 자연스러운 반복과 진짜 군더더기 반복 구분 필요

#### Recall 개선 (놓치는 구간 줄이기)

- [ ] SRT segment 내부 부분 컷 지원 — 현재 segment 단위로만 판단. "오토노머스, 오토노머스하게 드라이, 오토노머스하게" 같은 segment 내 반복/말더듬을 단어 레벨로 잡아야 함
- [ ] SRT 미전사 구간 처리 — 전사되지 않은 구간(의미없는 소리, 시행착오)을 silence와 구분하여 잡는 방법 필요
- [ ] 맥락/사실 판단 강화 — "정보가 부정확할 수 있다", "블로그 안내=저중요도" 같은 외부 지식 기반 판단. storyline context 활용도를 높이거나, 프롬프트에 "라이브 방송 특성" 힌트 추가
- [ ] 대화 흐름 끼어들기 감지 — 진행 흐름을 끊는 질문/확인("이거 맞아?", "뭐였지?") 중 빠져도 자연스러운 것을 감지

### 문서

- [ ] podcast-cut/SKILL.md 작성

### 내보내기

- [ ] Premiere Pro XML 내보내기 연결 (`export/premiere.py` 구현 완료, CLI 미노출)
