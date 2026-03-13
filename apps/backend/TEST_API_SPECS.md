# AVID Manual Verification Specs

> 목적: 실제 작업 순서대로 무엇을 확인해야 하는지 정리한다.
> 범위: `avid-cli` 표면과 현재 FastAPI route 표면.

## 1. Source Of Truth

- [CLI_INTERFACE.md](CLI_INTERFACE.md)
- [PROVIDER_RUNTIME_SPEC.md](PROVIDER_RUNTIME_SPEC.md)
- [TESTING.md](TESTING.md)
- [TEST_DATA_GUIDE.md](TEST_DATA_GUIDE.md)
- [../../SPEC.md](../../SPEC.md)
- [../../ARCHITECTURE.md](../../ARCHITECTURE.md)

## 2. 주 워크플로우

주 검증 순서는 아래다.

1. preflight `doctor`
2. `transcribe`
3. `transcript-overview`
4. `subtitle-cut` 또는 `podcast-cut`
5. `review-segments`
6. `apply-evaluation`
7. `rebuild-multicam`
8. `export-project`
9. Final Cut Pro 에서 FCPXML 확인

`reexport` 는 주 워크플로우가 아니라 compatibility 확인용이다.

## 3. 공통 확인 항목

모든 CLI 명령에서 공통으로 보는 것:

- exit code
- stderr 가 실패 원인을 충분히 말해주는지
- `--json` payload shape
- `--manifest-out` 사용 시 파일과 stdout 이 일치하는지
- 실제 artifact 파일이 생성됐는지

## 4. 단계별 수동 검증 포인트

### 4.1 Preflight: `doctor`

목적:
- source 처리 전에 runtime 이 살아 있는지 본다.

성공 기준:

- 기본 `doctor --json` 은 빠르게 끝난다
- `doctor --probe-providers --json` 은 실제 Claude/Codex 호출을 수행한다
- resolved `provider/model/effort` 가 payload 에 남는다

### 4.2 Source -> SRT: `transcribe`

목적:
- 원본 소스에서 자막이 생성되는지 본다.

성공 기준:

- `artifacts.srt` 생성
- 생성된 SRT 가 사람이 읽을 수 있는 형태
- main workflow sample 기준으로 `main_live.srt` 와 같은 종류의 출력

### 4.3 SRT -> Storyline: `transcript-overview`

목적:
- SRT 를 기반으로 story analysis 가 만들어지는지 본다.

성공 기준:

- `artifacts.storyline` 생성
- chapter / dependency / key moment 존재
- provider/model/effort 설정이 실제 실행에 반영됨

### 4.4 Storyline -> Initial Edit Decisions: `subtitle-cut` / `podcast-cut`

목적:
- source + srt + storyline 를 기반으로 initial edit decision 이 만들어지는지 본다.

성공 기준:

- `artifacts.project_json` 생성
- `artifacts.fcpxml`, `artifacts.report`, `artifacts.srt` 도 생성될 수 있음
- 여기서 주로 볼 것은 **initial project JSON / edit decisions**

주의:

- 이 단계의 FCPXML 은 편의 출력일 수 있다
- 사람이 평가하고 multicam 을 붙인 뒤 최종 export 를 다시 보는 것이 주 workflow 다

### 4.5 Review Payload: `review-segments`

목적:
- 엔진이 직접 review payload 를 내보내는지 본다.

성공 기준:

- `schema_version=review-segments/v1`
- `segments[]` 가 transcription segment 기준으로 채워짐
- 새 project JSON 에서는 `join_strategy=source_segment_index`
- old project JSON 에서는 필요 시 `join_strategy=legacy_overlap`
- `ai.origin_kind`, `ai.source_segment_index` 가 포함됨

### 4.6 Human Eval Override: `apply-evaluation`

목적:
- 사람이 판단한 keep/cut 이 initial decision 을 덮어쓰는지 본다.

성공 기준:

- `artifacts.project_json` 생성
- `stats.applied_evaluation_segments` 존재
- `stats.join_strategy=source_segment_index`
- 결과 JSON 에 override 반영

legacy 기준:

- old project 에서는 `stats.join_strategy=legacy_overlap`
- stderr 에 deprecated warning 이 남아야 함

### 4.7 Multicam Add: `rebuild-multicam`

목적:
- 사람 평가가 반영된 project JSON 에 extra source 를 붙인다.

성공 기준:

- secondary source 와 track 이 추가됨
- `stats.extra_sources`, `stats.stripped_extra_sources` 존재

실패 기준:

- `--extra-source` 만 있고 `--source` 없음
- offset 개수와 extra source 개수 불일치

### 4.8 Final Export: `export-project`

목적:
- human eval + multicam 이 반영된 최종 project JSON 에서 delivery artifact 를 만든다.

성공 기준:

- `artifacts.fcpxml` 생성
- transcription 이 있으면 `artifacts.srt` 생성
- `report` 는 생성하지 않는다
- **이 단계의 FCPXML 이 최종 검토 대상**

### 4.9 Optional Maintenance: `clear-extra-sources`

목적:
- multicam 을 붙였다가 explicit 하게 제거하는 maintenance path

성공 기준:

- extra source 가 제거된 project JSON 생성
- `stats.stripped_extra_sources` 존재

### 4.10 Compatibility Only: deprecated `reexport`

목적:
- legacy wrapper 가 아직 동작하는지만 본다.

성공 기준:

- stderr 에 deprecated warning
- split 명령 조합과 같은 계열의 artifact 생성

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

주 workflow 데이터:

- `samples/test_multisource/main_live.mp4`
- `samples/test_multisource/cam_sony.mp4`
- `samples/test_multisource/main_live.srt`
- `samples/test_multisource/main_live.storyline.json`
- `samples/test_multisource/main_live.podcast.avid.json`
- runtime 에서 생성한 `04_review/main_live.review.json`
- 사람이 `human` 필드를 채운 `04_review/main_live.eval.json`

보조 reference 데이터:

- `apps/backend/manual-fixtures/historical/20260207_192336/`
- `samples/sample_10min.m4a`
- `samples/C1718_compressed.mp4`

## 7. 권장 검증 단계

1. preflight `doctor`
2. `transcribe`
3. `transcript-overview`
4. initial `subtitle-cut` / `podcast-cut`
5. `review-segments`
6. `apply-evaluation`
7. `rebuild-multicam`
8. `export-project`
9. Final Cut Pro review
10. optional `clear-extra-sources`
11. compatibility-only `reexport`
