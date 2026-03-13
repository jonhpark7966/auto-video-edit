# Backend Verification WIP

> 최종 갱신: 2026-03-13
> 범위: `auto-video-edit` backend 수동 검증

## 지금 보고 작업할 파일

- 이 파일: [WORK_IN_PROGRESS.md](/home/jonhpark/workspace/auto-video-edit/apps/backend/WORK_IN_PROGRESS.md)
- CLI 표면: [CLI_INTERFACE.md](/home/jonhpark/workspace/auto-video-edit/apps/backend/CLI_INTERFACE.md)
- 검증 스펙: [TEST_API_SPECS.md](/home/jonhpark/workspace/auto-video-edit/apps/backend/TEST_API_SPECS.md)
- 검증 순서: [TESTING.md](/home/jonhpark/workspace/auto-video-edit/apps/backend/TESTING.md)
- fixture 안내: [TEST_DATA_GUIDE.md](/home/jonhpark/workspace/auto-video-edit/apps/backend/TEST_DATA_GUIDE.md)

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
- [x] legacy 자동화 테스트 제거

## 지금부터 직접 확인할 순서

- [ ] `avid-cli doctor --json`
- [ ] `avid-cli doctor --probe-providers --json`
- [ ] `avid-cli apply-evaluation`
- [ ] `avid-cli export-project`
- [ ] `avid-cli rebuild-multicam`
- [ ] `avid-cli clear-extra-sources`
- [ ] deprecated `avid-cli reexport`
- [ ] `avid-cli transcribe`
- [ ] `avid-cli transcript-overview`
- [ ] `avid-cli subtitle-cut`
- [ ] `avid-cli podcast-cut`
- [ ] FCPXML 을 Final Cut Pro 에서 열어 확인

## 메모

- 검증 source of truth 는 이 저장소다.
- `eogum` 은 여기의 `avid-cli` 표면만 소비한다.
- `Python SDK` 방향은 채택하지 않았다.
