# Backend Verification WIP

> 최종 갱신: 2026-03-14
> 범위: `auto-video-edit` backend 실제 워크플로우 검증

## 지금 보고 작업할 파일

- 이 파일: [WORK_IN_PROGRESS.md](/home/jonhpark/workspace/auto-video-edit/apps/backend/WORK_IN_PROGRESS.md)
- 검증 순서: [TESTING.md](/home/jonhpark/workspace/auto-video-edit/apps/backend/TESTING.md)
- 검증 스펙: [TEST_API_SPECS.md](/home/jonhpark/workspace/auto-video-edit/apps/backend/TEST_API_SPECS.md)
- fixture 안내: [TEST_DATA_GUIDE.md](/home/jonhpark/workspace/auto-video-edit/apps/backend/TEST_DATA_GUIDE.md)
- split command 배경: [REEXPORT_SPLIT_PLAN.md](/home/jonhpark/workspace/auto-video-edit/apps/backend/REEXPORT_SPLIT_PLAN.md)
- review 데이터 정렬 계획: [REVIEW_DATA_ALIGNMENT_PLAN.md](/home/jonhpark/workspace/auto-video-edit/apps/backend/REVIEW_DATA_ALIGNMENT_PLAN.md)

## 현재 상태

- [x] provider runtime 정리
- [x] `doctor` fast check / deep probe 분리
- [x] split command 분리
  - [x] `apply-evaluation`
  - [x] `export-project`
  - [x] `rebuild-multicam`
  - [x] `clear-extra-sources`
- [x] deprecated `reexport` 유지
- [x] `manual-fixtures` 경로 정리
- [x] main workflow 기준 human eval fixture 추가
- [x] legacy 자동화 테스트 제거
- [ ] review 데이터 모델 정렬 시작

## 현재 구현 작업

목표:

- `eogum` review 데이터가 `avid-cli` 에 그대로 들어갈 수 있게 만든다.
- `eogum` 이 아닌 다른 UI 도 `avid-cli` 의 review payload 를 그대로 쓸 수 있게 만든다.

원칙:

- review 기준 단위는 transcript segment index 다.
- `avid-cli` 가 review payload 를 직접 만든다.
- `eogum` 은 그 payload 를 저장/전달하는 소비자여야 한다.

커밋 단위 체크리스트:

- [x] Commit 1. avid 모델에 segment identity 추가
- [x] Commit 2. `avid-cli review-segments` 추가
- [x] Commit 3. `apply-evaluation` 를 index 기반 patch 로 교체
- [ ] Commit 4. `eogum` API 를 engine-native review payload 소비자로 변경
- [ ] Commit 5. `eogum` frontend / 문서 정리
- [ ] Commit 6. 새 영상 기준 수동 검증 문서 갱신

세부 파일 목록과 완료 기준은 [REVIEW_DATA_ALIGNMENT_PLAN.md](/home/jonhpark/workspace/auto-video-edit/apps/backend/REVIEW_DATA_ALIGNMENT_PLAN.md) 를 따른다.

## 지금부터 직접 확인할 순서

- [ ] preflight
  - [ ] `avid-cli doctor --json`
  - [ ] `avid-cli doctor --probe-providers --json`
- [ ] source -> srt
  - [ ] `avid-cli transcribe samples/test_multisource/main_live.mp4`
- [ ] srt -> storyline
  - [ ] `avid-cli transcript-overview`
- [ ] storyline -> initial edit decisions
  - [ ] `avid-cli podcast-cut` 또는 `avid-cli subtitle-cut`
- [ ] human override
  - [ ] `avid-cli apply-evaluation`
- [ ] multicam add
  - [ ] `avid-cli rebuild-multicam`
- [ ] final export
  - [ ] `avid-cli export-project`
- [ ] final review
  - [ ] FCPXML 을 Final Cut Pro 에서 열어 확인
- [ ] optional maintenance path
  - [ ] `avid-cli clear-extra-sources`
- [ ] compatibility only
  - [ ] deprecated `avid-cli reexport`

## 메모

- 검증 source of truth 는 이 저장소다.
- `eogum` 은 여기의 `avid-cli` 표면만 소비한다.
- `Python SDK` 방향은 채택하지 않았다.
- `reexport` 는 주 워크플로우가 아니라 마지막 compatibility 확인용이다.
- review 데이터 정렬 구현은 위 커밋 체크리스트 순서대로 진행한다.
