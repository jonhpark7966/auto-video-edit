# AVID Test API Specs

> 목적: `auto-video-edit` 에서 무엇을 테스트해야 하는지, 어떤 입력/출력/실패 규칙을 검증해야 하는지, 그리고 어떤 준비물이 필요한지 한 문서에서 본다.
> 범위: `avid-cli` 표면과 현재 FastAPI route 표면.

## 1. Source Of Truth

- CLI 표면: [CLI_INTERFACE.md](CLI_INTERFACE.md)
- provider 설정 표면: [PROVIDER_RUNTIME_SPEC.md](PROVIDER_RUNTIME_SPEC.md)
- 테스트 계층/우선순위: [TESTING.md](TESTING.md)
- 테스트 데이터 분류/리뷰 순서: [TEST_DATA_GUIDE.md](TEST_DATA_GUIDE.md)
- 제품/도메인 스펙: [../../SPEC.md](../../SPEC.md)
- 런타임 구조: [../../ARCHITECTURE.md](../../ARCHITECTURE.md)

이 문서는 위 문서들을 테스트 관점으로 재정리한 문서다.

## 2. 테스트해야 하는 외부 표면

두 가지를 테스트한다.

1. `avid-cli` command interface
2. FastAPI HTTP routes

원칙:
- 상위 시스템 통합 전에는 CLI 표면이 먼저 green 이어야 한다.
- HTTP API 는 현재 보조 표면이므로 CLI 이후에 검증한다.
- 내부 Python 모듈 경로는 테스트하더라도 public contract 로 취급하지 않는다.

## 3. CLI 테스트 스펙

### 3.1 `avid-cli version`

목적:
- 엔진 버전 식별
- 상위 시스템 audit/version 기록

입력:
- 없음

검증할 성공 조건:
- exit code `0`
- `--json` 결과가 valid JSON
- 필수 필드 존재
  - `command == "version"`
  - `status == "ok"`
  - `avid_version`
  - `package_version`
  - `git_revision` or `null`

검증할 실패 조건:
- 없음에 가깝다. 가장 안정적인 진단 명령이어야 한다.

필요 준비물:
- git checkout 된 repo
- 설치된 `avid-cli`

의존성:
- Python
- `git` 실행 가능 환경

권장 테스트 계층:
- unit
- CLI integration

### 3.2 `avid-cli doctor`

목적:
- 런타임 준비 상태 확인

입력:
- 선택: `--provider` (repeatable, 생략 시 claude+codex)
- 선택: `--provider-model` (`--probe-providers` + 단일 provider 지정 시만 허용)
- 선택: `--provider-effort` (`--probe-providers` + 단일 provider 지정 시만 허용)
- 선택: `--chalna-url`

검증할 성공 조건:
- exit code `0` when required dependencies are present
- `--json` 결과에 `checks` 포함
- 최소 check key 존재
  - `python`
  - `ffmpeg`
  - `ffprobe`
  - `chalna`
  - `provider`
- multi-provider 기본 실행에서는 `provider_configs` 가 존재하고 `provider_probes` 는 비어 있거나 생략 가능
- single-provider 실행에서는 `provider_config` 가 존재
- `provider_config.provider` 가 요청 provider 와 일치
- `provider_config.model` 이 resolved model 과 일치
- `provider_config.effort` 가 resolved effort 와 일치
- `--probe-providers` 사용 시 `provider_probe` 또는 동등한 상세 필드가 존재
- `provider_probe.provider` 가 요청 provider 와 일치
- smoke 호출에 사용한 `model`, `reasoning_effort` 또는 동등 옵션 정보가 결과에 남는다
- provider smoke 가 실제 응답까지 도달했음을 확인할 수 있다

검증할 실패 조건:
- provider CLI 부재 시 non-zero exit
- `--probe-providers` 사용 시 provider binary 는 있으나 실제 API/auth/model 호출이 실패하면 non-zero exit
- `--provider-model` / `--provider-effort` 우선순위가 env/default 보다 낮게 해석되면 실패로 본다
- multi-provider 기본 실행에서 generic override를 허용하면 실패로 본다
- 요청한 `model` 또는 `reasoning_effort` 옵션이 무효이면 non-zero exit 또는 명시적 check failure
- Chalna 비가동 시 non-zero exit
- stderr 에 진단 payload 또는 실패 이유 존재

필요 준비물:
- live profile 에서는 실제 provider CLI
- provider auth 가 설정된 shell environment
- canonical smoke prompt fixture: `tests/fixtures/text/provider_smoke_prompt.txt`
- provider smoke 에 쓸 최소 model 이름과 reasoning option 조합
- live profile 에서는 실제 Chalna server

의존성:
- Python
- `ffmpeg`
- `ffprobe`
- `claude` or `codex`
- provider API auth
- Chalna

권장 테스트 계층:
- unit: payload shape / check aggregation / probe result formatting
- live smoke: 실제 dependency 상태
- TODO: Chalna 가 deep health/test API 를 제공하면 doctor live test 는 실제 transcription probe 까지 확장

### 3.2a Provider runtime resolution

목적:
- provider 이름만이 아니라 model/effort 조합도 stable 하게 전달
- model churn 시 코드 수정 없이 env/CLI 로 교체 가능하게 유지

입력:
- `--provider`
- `--provider-model`
- `--provider-effort`
- provider-specific env

검증할 성공 조건:
- CLI flag > env > default 우선순위가 유지된다
- `provider_config.source` 에 각 값의 해석 출처가 남는다
- `transcript-overview`, `subtitle-cut`, `podcast-cut`, `doctor` 가 같은 resolution 규칙을 공유한다

검증할 실패 조건:
- provider별 env 를 잘못 섞어 읽으면 실패
- model/effort 가 payload 에 누락되면 실패

필요 준비물:
- env override fixture
- subprocess argv capture fixture

권장 테스트 계층:
- unit
- CLI integration

### 3.3 `avid-cli transcribe`

목적:
- 영상/오디오 -> SRT 변환

입력:
- `input`
- 선택: `-l/--language`
- 선택: `--chalna-url`
- 선택: `-d/--output-dir`
- 선택: `--json`
- 선택: `--manifest-out`

검증할 성공 조건:
- exit code `0`
- `artifacts.srt` 존재
- 출력 SRT 파일이 실제로 생성됨
- `stats.segments` 가 1 이상
- `stats.language` 가 요청과 일치
- `--manifest-out` 결과와 stdout JSON 이 동일 payload

검증할 실패 조건:
- 입력 파일 없음 -> non-zero exit + stderr
- Chalna 비가동 -> non-zero exit + stderr

필요 준비물:
- very small sample media file
- live Chalna server
- writable temp/output directory

의존성:
- Python
- Chalna
- `ffmpeg` if video input is used

권장 테스트 계층:
- integration: service monkeypatch 또는 audio fixture 최소화
- live smoke: 실제 Chalna 호출

### 3.4 `avid-cli transcript-overview`

목적:
- SRT -> storyline.json 생성

입력:
- `input` SRT
- 선택: `-o/--output`
- 선택: `--content-type`
- 선택: `--provider`
- 선택: `--provider-model`
- 선택: `--provider-effort`
- 선택: `--json`
- 선택: `--manifest-out`

검증할 성공 조건:
- exit code `0`
- `artifacts.storyline` 존재
- storyline JSON 파일 실제 생성
- `stats.chapters`, `stats.dependencies`, `stats.key_moments` 존재

검증할 실패 조건:
- SRT 파일 없음 -> non-zero exit
- provider CLI 부재 또는 provider 실패 -> non-zero exit

필요 준비물:
- small sample SRT
- live provider or provider stub

의존성:
- Python
- `claude` or `codex`

권장 테스트 계층:
- integration: provider call monkeypatch 가능
- live smoke: 실제 provider 호출

### 3.5 `avid-cli subtitle-cut`

목적:
- 강의/설명형 컷 편집 결과 생성

입력:
- `input` video
- `--srt`
- 선택: `--context`
- 선택: `--provider`
- 선택: `--provider-model`
- 선택: `--provider-effort`
- 선택: `-o/--output`
- 선택: `-d/--output-dir`
- 선택: `--final`
- 선택: `--extra-source`
- 선택: `--offset`
- 선택: `--json`
- 선택: `--manifest-out`

검증할 성공 조건:
- exit code `0`
- 필수 artifact key 존재
  - `project_json`
  - `fcpxml`
  - `report`
  - `srt` if transcription exists
- 각 artifact 파일이 실제로 생성됨
- `stats.edit_decisions` 존재
- review/default 와 final 모드에서 출력이 달라짐

검증할 실패 조건:
- video 없음 -> non-zero exit
- srt 없음 -> non-zero exit
- context 지정했는데 파일 없음 -> non-zero exit
- extra source 지정했는데 파일 없음 -> non-zero exit

필요 준비물:
- sample video
- sample SRT
- optional sample storyline JSON
- optional extra source media files

의존성:
- Python
- `ffmpeg` / `ffprobe`
- provider CLI
- `audio-offset-finder` if extra source auto sync is tested

권장 테스트 계층:
- integration
- live smoke

### 3.6 `avid-cli podcast-cut`

목적:
- 팟캐스트/인터뷰형 컷 편집 결과 생성

입력:
- `input` audio or video
- 선택: `--srt`
- 선택: `--context`
- 선택: `--provider`
- 선택: `--provider-model`
- 선택: `--provider-effort`
- 선택: `-d/--output-dir`
- 선택: `--final`
- 선택: `--extra-source`
- 선택: `--offset`
- 선택: `--json`
- 선택: `--manifest-out`

검증할 성공 조건:
- exit code `0`
- 필수 artifact key 존재
  - `project_json`
  - `fcpxml`
  - `report`
  - `srt`
- artifact 파일 실제 생성
- `stats.edit_decisions` 존재
- `--srt` 없이 실행 시 raw transcription 경로 또는 output artifact 동작 확인

검증할 실패 조건:
- input 없음 -> non-zero exit
- `--srt` 지정했는데 파일 없음 -> non-zero exit
- context 지정했는데 파일 없음 -> non-zero exit

필요 준비물:
- sample audio or video
- optional sample SRT
- optional storyline JSON
- optional extra source media files

의존성:
- Python
- provider CLI
- Chalna if `--srt` 없이 테스트
- `ffmpeg` / `ffprobe`
- `audio-offset-finder` if extra source auto sync is tested

권장 테스트 계층:
- integration
- live smoke

### 3.6a `avid-cli apply-evaluation`

목적:
- 기존 `.avid.json` 에 human override 만 적용
- media 없이 project JSON patch 경계를 고정

상태:
- 현재 구현되어 있다
- `reexport` 분해의 첫 단계다
- 상위 통합은 evaluation-only 재처리에서 이 명령을 우선 사용해야 한다

입력:
- `--project-json`
- `--evaluation`
- `--output-project-json`
- 선택: `--json`
- 선택: `--manifest-out`

검증할 성공 조건:
- exit code `0`
- 필수 artifact key 존재
  - `project_json`
- stats key 존재
  - `applied_evaluation_segments`
  - `applied_changes`
- output project JSON 에 manual override 결과가 반영됨
- `{ "segments": [...] }` 와 list payload 둘 다 허용됨

검증할 실패 조건:
- project JSON 없음 -> non-zero exit
- evaluation JSON 없음 -> non-zero exit
- evaluation JSON 형식 오류 -> non-zero exit

필요 준비물:
- sample `.avid.json`
- sample `evaluation.json`

의존성:
- Python

권장 테스트 계층:
- unit
- CLI integration

### 3.6b `avid-cli export-project`

목적:
- 준비된 `.avid.json` 을 FCPXML / adjusted SRT 로 export
- project JSON mutation 없이 export 경계 고정

상태:
- 현재 구현되어 있다
- `reexport` 분해의 두 번째 단계다

입력:
- `--project-json`
- `--output-dir`
- 선택: `-o/--output`
- 선택: `--silence-mode`
- 선택: `--content-mode`
- 선택: `--json`
- 선택: `--manifest-out`

검증할 성공 조건:
- exit code `0`
- 필수 artifact key 존재
  - `fcpxml`
  - `srt` if transcription exists
- output FCPXML 이 parse 가능함
- output override 를 주면 그 경로를 따른다
- report artifact 는 생성하지 않는다

검증할 실패 조건:
- project JSON 없음 -> non-zero exit

필요 준비물:
- transcription 이 있는 sample `.avid.json`

의존성:
- Python

권장 테스트 계층:
- unit
- CLI integration

### 3.6c `avid-cli rebuild-multicam`

목적:
- 기존 `.avid.json` 의 extra source 를 재구성
- export 없이 multicam patch 경계를 고정

상태:
- 현재 구현되어 있다
- `reexport` 분해의 세 번째 단계다

입력:
- `--project-json`
- `--source`
- `--extra-source` repeatable
- 선택: `--offset` repeatable
- `--output-project-json`
- 선택: `--json`
- 선택: `--manifest-out`

검증할 성공 조건:
- exit code `0`
- 필수 artifact key 존재
  - `project_json`
- stats key 존재
  - `extra_sources`
  - `stripped_extra_sources`
- output project JSON 의 source_files / tracks 가 새 extra source 기준으로 갱신됨
- manual offset 이 track offset 에 반영됨

검증할 실패 조건:
- project JSON 없음 -> non-zero exit
- source 없음 -> non-zero exit
- `--extra-source` 없음 -> non-zero exit
- extra source 파일 없음 -> non-zero exit

필요 준비물:
- sample `.avid.json`
- main source media
- extra source media

의존성:
- Python
- `ffprobe` if real media metadata 경로를 검증할 때

권장 테스트 계층:
- unit
- CLI integration
- live smoke for real media path

### 3.7 `avid-cli reexport`

목적:
- 기존 `.avid.json` 에 human override 적용
- 기존 `.avid.json` 에 extra source 재구성
- 상위 시스템 direct import 제거의 핵심 명령

상태:
- 현재 구현은 compatibility wrapper 로 유지
- `apply-evaluation`, `export-project`, `rebuild-multicam` 는 이미 분리되었고, 신규 테스트의 다음 목표는 `clear-extra-sources` 의 계약을 고정하는 것이다
- `reexport` 테스트는 최종적으로 parity / backward-compatibility 확인 용도로 남긴다
- 자세한 분해 계획은 [REEXPORT_SPLIT_PLAN.md](REEXPORT_SPLIT_PLAN.md) 를 본다

입력:
- `--project-json`
- `--output-dir`
- 선택: `--source`
- 선택: `--evaluation`
- 선택: `--extra-source`
- 선택: `--offset`
- 선택: `-o/--output`
- 선택: `--silence-mode`
- 선택: `--content-mode`
- 선택: `--json`
- 선택: `--manifest-out`

검증할 성공 조건:
- exit code `0`
- 필수 artifact key 존재
  - `project_json`
  - `fcpxml`
  - `srt` if transcription exists
- stats key 존재
  - `applied_evaluation_segments`
  - `applied_changes`
  - `extra_sources`
  - `stripped_extra_sources`
- evaluation 적용 후 output project JSON 에 manual override 가 반영됨
- 기존 extra source 가 있는 입력에서도 strip 후 재구성됨

검증할 실패 조건:
- project JSON 없음 -> non-zero exit
- evaluation 파일 없음 -> non-zero exit
- `--extra-source` 를 줬는데 `--source` 없음 -> non-zero exit
- extra source 파일 없음 -> non-zero exit

필요 준비물:
- sample `.avid.json`
- sample `evaluation.json`
- optional main source media
- optional extra source media pair

의존성:
- Python
- `ffmpeg` / `ffprobe` for export path using media metadata
- `audio-offset-finder` if extra source auto sync is tested

권장 테스트 계층:
- unit
- CLI integration
- live smoke for extra source path only

### 3.8 멀티캠 / extra source 추가 시나리오

목적:
- 메인 소스 외 추가 카메라/마이크를 project 에 붙이는 흐름 검증
- `--extra-source` / `--offset` / auto sync 경계 검증

대상 명령:
- `subtitle-cut`
- `podcast-cut`
- `reexport`

검증할 성공 조건:
- extra source 가 있는 입력에서 exit code `0`
- output `project_json` 의 `source_files` 수가 증가한다
- output `project_json` 의 extra track 들에 offset 이 설정된다
- `stats.extra_sources` 또는 equivalent summary 가 기대값과 맞는다
- auto sync 사용 시 메인/추가 소스가 모두 project 에 반영된다
- manual offset 사용 시 지정한 offset 값이 최종 project 에 반영된다

검증할 실패 조건:
- 존재하지 않는 extra source -> non-zero exit
- `reexport` 에서 `--extra-source` 만 주고 `--source` 가 없으면 non-zero exit
- sync dependency 가 없는데 auto sync path 를 타면 명시적으로 실패한다

필요 준비물:
- 메인 소스 1개
- 오디오가 일부 겹치는 extra source 1~2개
- manual offset 확인용 fixture case

의존성:
- `audio-offset-finder` for auto sync
- `ffmpeg` / `ffprobe`

권장 테스트 계층:
- integration
- live smoke

### 3.9 FCPXML export 시나리오

목적:
- 최종 산출물인 FCPXML 이 항상 생성되고, review/final/multicam 조합에서 깨지지 않는지 검증

대상 경로:
- `subtitle-cut` export
- `podcast-cut` export
- `reexport` export
- `FCPXMLExporter`

검증할 성공 조건:
- `artifacts.fcpxml` 존재
- FCPXML 파일이 실제로 생성됨
- XML 파싱이 가능함
- 최소 구조 포함
  - `<fcpxml>` root
  - `<resources>`
  - `<library>` or export body main structure
  - main clip / spine timeline
- review 모드에서는 disabled/kept semantics 가 반영됨
- final 모드에서는 cut semantics 가 반영됨
- transcription 이 있으면 adjusted SRT 가 FCPXML cut 결과와 일관됨
- multicam case 에서는 connected clip / extra track 구조가 포함됨
- zero-frame clip 같은 비정상 clip 이 export 되지 않는다

검증할 실패 조건:
- invalid project 입력에서 export 실패 시 non-zero exit 또는 예외
- missing media metadata 로 export 불가하면 명시적인 실패

필요 준비물:
- minimal project JSON fixture
- transcription 이 포함된 project fixture
- multicam project fixture
- review/final 비교 fixture

의존성:
- Python XML parser
- `ffmpeg` / `ffprobe` if export path depends on media metadata fixture generation

권장 테스트 계층:
- unit: exporter pure behavior
- integration: CLI artifact generation
- live smoke: Final Cut Pro import 전 수동 spot-check

## 4. HTTP API 테스트 스펙

현재 FastAPI 표면은 보조 인터페이스다. CLI 테스트 이후에 검증한다.

### 4.1 `GET /health`

목적:
- 서버 가동 확인

검증할 성공 조건:
- status code `200`
- response JSON: `status`, `version`
- `status == "healthy"`

필요 준비물:
- FastAPI app import 가능 환경

의존성:
- Python
- FastAPI test client

권장 테스트 계층:
- API integration

### 4.2 `GET /api/v1/media/info`

입력:
- query `path`

검증할 성공 조건:
- status code `200`
- response JSON fields
  - `duration_ms`
  - optional `width`, `height`, `fps`, `sample_rate`

검증할 실패 조건:
- 파일 없음 -> `422`

필요 준비물:
- sample media file

의존성:
- `ffprobe`

권장 테스트 계층:
- API integration

### 4.3 `POST /api/v1/jobs/transcribe`

검증할 성공 조건:
- status code `202`
- response JSON: `job_id`, `status`, `type`
- manager 에 transcribe job 생성

검증할 실패 조건:
- input file 없음 -> `422`

필요 준비물:
- sample media file
- test job manager fixture

의존성:
- FastAPI test client

권장 테스트 계층:
- API integration with fake job manager

### 4.4 `POST /api/v1/jobs/transcript-overview`

검증할 성공 조건:
- status code `202`
- response JSON: `job_id`, `status`, `type`

검증할 실패 조건:
- SRT file 없음 -> `422`

필요 준비물:
- sample SRT
- fake job manager

권장 테스트 계층:
- API integration

### 4.5 `POST /api/v1/jobs/subtitle-cut`

검증할 성공 조건:
- status code `202`
- video/srt/context validation 통과 시 job 생성
- `extra_sources` / `extra_offsets` payload 도 함께 전달 가능

검증할 실패 조건:
- video 없음 -> `422`
- srt 없음 -> `422`
- context_path 없음 -> `422`

필요 준비물:
- sample video
- sample SRT
- optional storyline JSON
- fake job manager

권장 테스트 계층:
- API integration

### 4.6 `POST /api/v1/jobs/podcast-cut`

검증할 성공 조건:
- status code `202`
- audio_path validation 통과 시 job 생성
- `extra_sources` / `extra_offsets` payload 도 함께 전달 가능

검증할 실패 조건:
- audio 없음 -> `422`
- srt 지정 후 없음 -> `422`
- context 지정 후 없음 -> `422`

필요 준비물:
- sample audio or video
- optional SRT
- optional storyline JSON
- fake job manager

권장 테스트 계층:
- API integration

### 4.7 `GET /api/v1/jobs`

검증할 성공 조건:
- status code `200`
- list response
- 각 item 이 `job_id/type/status/created_at` 포함

필요 준비물:
- fake job manager with seeded jobs

권장 테스트 계층:
- API integration

### 4.8 `GET /api/v1/jobs/{job_id}`

검증할 성공 조건:
- status code `200`
- response JSON includes
  - `job_id`
  - `type`
  - `status`
  - `progress`
  - `message`
  - `result?`
  - `error?`
  - `created_at`
  - `completed_at?`

검증할 실패 조건:
- job 없음 -> `404`

필요 준비물:
- fake job manager with seeded completed/running/failed jobs

권장 테스트 계층:
- API integration

### 4.9 `GET /api/v1/jobs/{job_id}/files/{name}`

검증할 성공 조건:
- status code `200`
- requested file download 응답

검증할 실패 조건:
- job 없음 -> `404`
- job result 없음 -> `404`
- output_files 에 name 없음 -> `404`
- mapped file path 가 실제로 없음 -> `404`

필요 준비물:
- fake completed job with temp output_files mapping
- temp output file

권장 테스트 계층:
- API integration

## 5. 준비물 정리

### 5.1 텍스트 fixture

반드시 필요한 최소 fixture:

- `fixtures/srt/sample_short.srt`
- `fixtures/json/storyline_minimal.json`
- `fixtures/json/project_minimal.avid.json`
- `fixtures/json/evaluation_minimal.json`

권장 내용:
- `sample_short.srt`: 3~8 segment
- `storyline_minimal.json`: chapters/dependencies/key_moments 최소 1개씩
- `project_minimal.avid.json`: transcription + edit_decisions + source_files + tracks 포함
- `evaluation_minimal.json`: keep/cut override 2~3개

### 5.2 미디어 fixture

권장 분리:
- `fixtures/media/live/` 에만 실제 미디어 파일 보관
- unit/integration 에서는 가급적 텍스트 fixture + monkeypatch 사용

live test 에 필요한 후보:
- `fixtures/media/live/sample_main.mp4`
- `fixtures/media/live/sample_alt.mp4`
- `fixtures/media/live/sample_audio.wav`
- `fixtures/media/live/sample_main_plus_cam2_pair/` or equivalent multicam pair fixture

속성 권장:
- 10~30초 길이
- 너무 크지 않을 것
- extra source sync 용으로 일부 오디오 구간이 겹칠 것

### 5.3 fake/stub 준비물

integration test 에 필요한 보조물:
- fake job manager
- monkeypatched provider call
- monkeypatched Chalna service
- temp output directory fixture

## 6. Dependency 정리

### 6.1 기본 Python 의존성

- Python 3.11+
- `pytest`
- `pytest-asyncio`
- `pytest-cov`

설치:

```bash
cd apps/backend
pip install -e '.[dev]'
```

### 6.2 미디어 처리 의존성

- `ffmpeg`
- `ffprobe`

필요한 테스트:
- `doctor`
- `media/info`
- 실제 export/smoke

### 6.3 AI/provider 의존성

- `claude` or `codex`

필요한 테스트:
- live `transcript-overview`
- live `subtitle-cut`
- live `podcast-cut`
- `doctor`

### 6.4 STT 의존성

- Chalna server

필요한 테스트:
- live `transcribe`
- `podcast-cut` without `--srt`
- `doctor`

### 6.5 멀티소스 의존성

- `audio-offset-finder`
- 설치: `pip install 'avid[sync]'`

필요한 테스트:
- `reexport` with `--extra-source`
- `subtitle-cut` / `podcast-cut` with `--extra-source`
- sync smoke

## 7. 테스트 실행 프로파일

### Fast profile

목적:
- PR 전 빠른 회귀 확인

포함:
- unit
- API integration with fake manager
- CLI integration with monkeypatch

불포함:
- live provider
- live Chalna
- real sync

### Contract profile

목적:
- 외부 통합 표면 고정 확인

포함:
- 모든 CLI `--json` / `--manifest-out`
- artifact key
- exit code / stderr 규칙
- HTTP route schema/status code

### Live smoke profile

목적:
- 실제 설치 환경 검증

포함:
- `doctor`
- `transcribe`
- one of `transcript-overview` / `subtitle-cut` / `podcast-cut`
- one sync case

## 8. 추가로 먼저 챙겨야 하는 특수 시나리오

- multicam add path: `extra_source` + auto sync + manual offset
- FCPXML export path: review/final/multicam 조합별 구조 검증
- adjusted SRT 와 cut 결과의 시간 일관성 검증

## 9. 내가 보기엔 먼저 만들어야 할 테스트

가장 먼저 필요한 것은 이것들이다.

1. `version --json` contract
2. `doctor --json` contract
3. `--manifest-out` contract
4. `reexport` validation and output contract
5. `GET /health`
6. `POST /api/v1/jobs/*` validation matrix
7. `GET /api/v1/jobs/{job_id}/files/{name}` 404 matrix
8. multicam extra source contract
9. FCPXML export structure contract

이 7개가 먼저 green 이어야 상위 시스템 연결을 자신 있게 진행할 수 있다.
