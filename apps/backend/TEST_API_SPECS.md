# AVID Manual Verification Specs

> 목적: 사람이 직접 어떤 표면을 어떤 순서와 기준으로 확인해야 하는지 정리한다.
> 범위: `avid-cli` 표면과 현재 FastAPI route 표면.

## 1. Source Of Truth

- [CLI_INTERFACE.md](CLI_INTERFACE.md)
- [PROVIDER_RUNTIME_SPEC.md](PROVIDER_RUNTIME_SPEC.md)
- [TESTING.md](TESTING.md)
- [TEST_DATA_GUIDE.md](TEST_DATA_GUIDE.md)
- [../../SPEC.md](../../SPEC.md)
- [../../ARCHITECTURE.md](../../ARCHITECTURE.md)

## 2. 검증 대상

먼저 보는 것은 `avid-cli` 이고, HTTP API 는 그 다음이다.

1. `avid-cli version`
2. `avid-cli doctor`
3. `avid-cli apply-evaluation`
4. `avid-cli export-project`
5. `avid-cli rebuild-multicam`
6. `avid-cli clear-extra-sources`
7. deprecated `avid-cli reexport`
8. `avid-cli transcribe`
9. `avid-cli transcript-overview`
10. `avid-cli subtitle-cut`
11. `avid-cli podcast-cut`
12. FastAPI HTTP routes

## 3. 공통 확인 항목

모든 CLI 명령에서 공통으로 보는 것:

- exit code
- stderr 가 실패 원인을 충분히 말해주는지
- `--json` payload shape
- `--manifest-out` 사용 시 파일과 stdout 이 일치하는지
- 실제 artifact 파일이 생성됐는지

## 4. 명령별 수동 검증 포인트

### 4.1 `version`

입력:
- 없음

성공 기준:
- exit code `0`
- `command == "version"`
- `status == "ok"`
- `avid_version`, `package_version` 존재

### 4.2 `doctor`

입력:
- 선택: `--provider`
- 선택: `--probe-providers`
- 선택: `--provider-model`
- 선택: `--provider-effort`
- 선택: `--chalna-url`

성공 기준:
- 기본 `doctor --json` 은 빠르게 끝난다
- 기본 doctor 는 binary/runtime 중심으로만 본다
- `doctor --probe-providers --json` 은 실제 Claude/Codex 호출을 수행한다
- resolved `provider/model/effort` 가 payload 에 남는다

실패 기준:
- provider CLI 없음
- provider auth/model/effort 오류
- Chalna 비가동

### 4.3 `apply-evaluation`

입력:
- `--project-json`
- `--evaluation`
- `--output-project-json`

성공 기준:
- `artifacts.project_json` 생성
- `stats.applied_evaluation_segments` 존재
- 결과 JSON 의 cut decision 이 바뀐다

### 4.4 `export-project`

입력:
- `--project-json`
- `--output-dir`
- 선택: `--output`
- 선택: `--content-mode`
- 선택: `--silence-mode`

성공 기준:
- `artifacts.fcpxml` 생성
- transcription 이 있으면 `artifacts.srt` 생성
- `report` 는 생성하지 않는다

### 4.5 `rebuild-multicam`

입력:
- `--project-json`
- `--source`
- `--extra-source` repeated
- `--offset` repeated
- `--output-project-json`

성공 기준:
- 기존 extra source strip 후 새 source 가 붙는다
- manual offset 이 결과 JSON 에 반영된다
- `stats.extra_sources`, `stats.stripped_extra_sources` 존재

실패 기준:
- `--extra-source` 만 있고 `--source` 없음
- offset 개수와 extra source 개수 불일치

### 4.6 `clear-extra-sources`

입력:
- `--project-json`
- `--output-project-json`

성공 기준:
- extra source 가 제거된 project JSON 생성
- `stats.stripped_extra_sources` 존재

### 4.7 Deprecated `reexport`

입력:
- legacy 표면 유지

성공 기준:
- stderr 에 deprecated warning
- split 명령 조합과 같은 계열의 artifact 생성

### 4.8 `transcribe`

성공 기준:
- `artifacts.srt` 생성
- 작은 media 로도 끝까지 돈다

필수 준비물:
- Chalna
- small media source

### 4.9 `transcript-overview`

성공 기준:
- `artifacts.storyline` 생성
- provider/model/effort 설정이 실제 실행에 반영된다

### 4.10 `subtitle-cut`, `podcast-cut`

성공 기준:
- `project_json`, `fcpxml`, `report`, `srt` artifact 존재
- provider failure 시 stderr 에 원인이 보인다

## 5. HTTP 수동 검증 포인트

우선 라우트:

- `GET /health`
- `POST /api/v1/jobs/transcribe`
- `POST /api/v1/jobs/transcript-overview`
- `POST /api/v1/jobs/subtitle-cut`
- `POST /api/v1/jobs/podcast-cut`
- `GET /api/v1/jobs`
- `GET /api/v1/jobs/{job_id}`
- `GET /api/v1/jobs/{job_id}/files/{name}`

확인할 것:

- status code
- validation error
- job 상태 전이
- artifact 다운로드 가능 여부

## 6. 준비물

기본:

- Python 3.11+
- `ffmpeg`
- `ffprobe`
- `git`

선택:

- `claude`
- `codex`
- Chalna
- `audio-offset-finder`

데이터:

- `apps/backend/manual-fixtures/text/`
- `apps/backend/manual-fixtures/historical/20260207_192336/`
- `samples/test_multisource/`
- `samples/sample_10min.m4a`
- `samples/C1718_compressed.mp4`

## 7. 권장 검증 단계

1. fast doctor
2. deep doctor
3. `apply-evaluation`
4. `export-project`
5. `rebuild-multicam`
6. `clear-extra-sources`
7. deprecated `reexport`
8. `transcribe`
9. `transcript-overview`
10. `subtitle-cut` / `podcast-cut`
11. HTTP API 수동 검증
