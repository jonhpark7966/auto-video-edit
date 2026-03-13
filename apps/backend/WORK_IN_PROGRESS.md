# Backend Test WIP

> 최종 갱신: 2026-03-13
> 범위: `auto-video-edit` backend 테스트 구축

## 현재 상태

- [x] `doctor` / provider runtime 정리
- [x] `doctor` fast check / deep probe 분리
- [x] provider 기본 프로필 정리
  - Claude: `claude-opus-4-6` + `medium`
  - Codex: `gpt-5.4` + `medium`
- [x] provider runtime 문서화
- [x] provider runtime unit test 추가
- [x] 테스트 fixture 기준 경로 정리

## 지금 보고 작업할 파일

- 이 파일: [WORK_IN_PROGRESS.md](/home/jonhpark/workspace/auto-video-edit/apps/backend/WORK_IN_PROGRESS.md)
- CLI 표면: [CLI_INTERFACE.md](/home/jonhpark/workspace/auto-video-edit/apps/backend/CLI_INTERFACE.md)
- 테스트 스펙: [TEST_API_SPECS.md](/home/jonhpark/workspace/auto-video-edit/apps/backend/TEST_API_SPECS.md)
- 테스트 순서: [TESTING.md](/home/jonhpark/workspace/auto-video-edit/apps/backend/TESTING.md)
- 테스트 데이터 안내: [TEST_DATA_GUIDE.md](/home/jonhpark/workspace/auto-video-edit/apps/backend/TEST_DATA_GUIDE.md)

## 현재 테스트 순서

- [x] `doctor` / provider runtime
- [ ] `reexport` 분해 명세 확정
- [x] `apply-evaluation` contract
- [x] `export-project` contract
- [x] `rebuild-multicam` contract
- [x] `clear-extra-sources` contract
- [ ] deprecated `reexport` parity contract
- [ ] `transcribe` live smoke
- [ ] legacy unit test 정리

## 이번 작업: `reexport` 분해 계획

- [ ] 분해 문서 검토
  - [REEXPORT_SPLIT_PLAN.md](REEXPORT_SPLIT_PLAN.md)
- [ ] 새 명령 경계 확정
  - `apply-evaluation`
  - `rebuild-multicam`
  - `clear-extra-sources`
  - `export-project`
- [ ] deprecated wrapper 정책 확정
  - `reexport` 는 유지하되 deprecated warning 추가
  - 내부적으로 새 명령 조합으로 재구성
- [ ] 테스트 우선순위 확정
  - `apply-evaluation` unit
  - `export-project` integration
  - `rebuild-multicam` integration
  - `clear-extra-sources` integration
  - `reexport` parity
- [x] `export-project` 는 report 를 만들지 않음
- [x] `eogum` 중간 project JSON 은 기존 `settings.avid_temp_dir` 아래 단계별 파일로 유지
- [x] manual offset 은 public API/CLI 표면으로 노출
- [ ] `eogum` 마이그레이션 TODO 반영 확인

## 분해 후 순서

- [x] `apply-evaluation`
  - evaluation override 적용만 담당
  - media 파일 없이 project JSON 만 갱신
- [x] `export-project`
  - project JSON 으로 FCPXML / SRT 산출물 생성
  - `content-mode`, `silence-mode` 만 담당
- [x] `rebuild-multicam`
  - extra source strip / add / offset 담당
  - evaluation 적용과 분리
- [x] `clear-extra-sources`
  - extra source 제거만 담당
  - strip-only 용도의 명시적 명령
- [ ] deprecated `reexport`
  - compatibility wrapper 로만 유지
- [ ] live smoke
  - `transcribe`
  - `audio sync`

## 메모

- 테스트 source of truth 는 이 저장소다.
- `eogum`은 여기의 `avid-cli` 표면만 소비한다.
- 다음 실제 작업은 deprecated `reexport` parity 정리다.
