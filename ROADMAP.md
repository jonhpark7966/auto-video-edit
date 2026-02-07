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
- [ ] podcast-cut 실제 영상 테스트 (≤80 단일 / >80 병렬)
- [ ] Two-Pass 워크플로우 end-to-end 테스트
- [ ] FCPXML 출력을 Final Cut Pro에서 검증

### 문서

- [ ] podcast-cut/SKILL.md 작성

### 내보내기

- [ ] Premiere Pro XML 내보내기 연결 (`export/premiere.py` 구현 완료, CLI 미노출)
