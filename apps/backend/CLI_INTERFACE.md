# AVID CLI Interface

> 목적: 외부 시스템이 믿고 사용할 수 있는 `avid-cli` 표면을 고정한다.
> 원칙: 외부 통합은 `avid-cli` 만 사용하고 `avid.*` 내부 모듈은 직접 import 하지 않는다.

테스트 관점 요약 문서는 [TEST_API_SPECS.md](TEST_API_SPECS.md) 에서 관리한다.
Provider model/effort 설정 표면은 [PROVIDER_RUNTIME_SPEC.md](PROVIDER_RUNTIME_SPEC.md) 에서 관리한다.
Multicam and FCPXML stability are tracked in the same test-spec document.

## 범위

이 문서는 아래에만 안정성을 약속한다.

- 서브커맨드 이름
- 주요 옵션 이름
- `--json` / `--manifest-out` 동작
- 필수 artifact key 이름
- 종료 코드와 stderr/stdout 규칙

이 문서는 아래는 안정성을 약속하지 않는다.

- `src/avid/services/*` 내부 함수 구조
- `src/avid/models/*` 내부 클래스 레이아웃
- 스킬 구현 디렉터리 구조
- CLI 내부 helper 함수 이름

## 공통 실행 규칙

- 성공 시 exit code `0`
- 실패 시 exit code `!= 0`
- 실패 상세는 stderr 로 본다
- 사람용 진행 로그는 기본 stdout 에 출력될 수 있다
- `--json` 사용 시 machine-readable JSON 은 stdout 으로 출력하고, 사람용 로그는 stderr 로 보낸다
- `--manifest-out <path>` 사용 시 같은 payload 를 JSON 파일로 저장한다

권장 실행 위치:

```bash
cd apps/backend
source .venv/bin/activate
avid-cli <command> ...
```

## 공통 JSON 형태

모든 `--json` 결과는 아래 필드를 기본으로 가진다.

```json
{
  "command": "subtitle-cut",
  "status": "ok",
  "avid_version": "4d60eb6",
  "package_version": "0.1.0",
  "git_revision": "4d60eb6"
}
```

명령에 따라 아래가 추가된다.

- `artifacts`: 파일 결과물 경로
- `stats`: 통계 또는 적용 개수
- `checks`: `doctor` 진단 결과

## 명령 표면

| 명령 | 목적 | 핵심 출력 |
|------|------|----------|
| `version` | 버전 식별 | `avid_version`, `package_version`, `git_revision` |
| `doctor` | 실행 환경 진단 | `checks` |
| `transcribe` | 소스에서 SRT 생성 | `artifacts.srt` |
| `transcript-overview` | SRT에서 storyline 생성 | `artifacts.storyline` |
| `subtitle-cut` | 강의/설명형 편집 | `artifacts.project_json`, `fcpxml`, `report`, `srt?` |
| `podcast-cut` | 팟캐스트/인터뷰 편집 | `artifacts.project_json`, `fcpxml`, `report`, `srt?` |
| `reexport` | 기존 project JSON 재-export | `artifacts.project_json`, `fcpxml`, `srt?` |

## Provider Runtime 표면

AI provider 를 쓰는 명령은 아래 공통 옵션을 가진다.

- `--provider <claude|codex>`
- `--provider-model <string>`
- `--provider-effort <string>`

적용 대상:

- `transcript-overview`
- `subtitle-cut`
- `podcast-cut`

`doctor` 는 예외적으로 `--provider` 를 repeatable 로 받고, 생략 시 `claude` 와 `codex` 를 둘 다 검사한다.
이때 `--provider-model`, `--provider-effort` 는 `--probe-providers` 와 단일 provider 지정 시만 허용한다.

설정 해석 순서:

1. CLI flag
2. provider-specific env
3. baked-in default

현재 권장 기본 프로필:

- `claude`: `claude-opus-4-6` + `medium`
- `codex`: `gpt-5.4` + `medium`

세부 규칙과 payload shape 는 [PROVIDER_RUNTIME_SPEC.md](PROVIDER_RUNTIME_SPEC.md) 를 source of truth 로 본다.

## 명령별 규칙

### `avid-cli version`

용도:
- 상위 시스템이 현재 `avid` 버전을 기록
- startup check 에서 엔진 식별

예시:

```bash
avid-cli version --json
```

### `avid-cli doctor`

용도:
- Python/ffmpeg/ffprobe/provider/Chalna 상태 확인
- live dependency 가 실제로 준비되었는지 진단
- 기본 실행은 provider binary 존재만 빠르게 확인
- 정밀 확인이 필요하면 `--probe-providers` 로 아주 작은 실제 호출까지 수행

예시:

```bash
avid-cli doctor --json
```

```bash
avid-cli doctor --provider claude --probe-providers --provider-model claude-opus-4-6 --provider-effort medium --json
```

최소 출력 예시:

```json
{
  "command": "doctor",
  "status": "ok",
  "checks": {
    "python": true,
    "ffmpeg": true,
    "ffprobe": true,
    "chalna": true,
    "provider": true
  },
  "provider_probe_requested": false,
  "provider_probes": {},
  "provider_configs": {
    "claude": {
      "provider": "claude",
      "model": "claude-opus-4-6",
      "effort": "medium"
    }
  },
  "hints": [
    "실제 Claude/Codex 호출까지 확인하려면 --probe-providers 를 사용하세요"
  ]
}
```

`doctor` 추가 규칙:
- 기본 `provider` check 는 `which claude` 같은 binary 존재 확인까지만 수행한다
- 실제 Claude/Codex 호출은 `--probe-providers` 일 때만 수행한다
- `doctor` 는 resolved `provider/model/effort` 를 payload 에 포함해야 한다
- multi-provider 기본 실행에서는 `provider_configs` 를 반환하고 `provider_probes` 는 비워 둘 수 있다
- single-provider probe 실행에서는 `provider_config`, `provider_probe` 도 함께 반환해야 한다
- `--provider-model`, `--provider-effort` 는 `--probe-providers` 와 함께 provider CLI 까지 전달해 option parsing 도 같이 확인한다
- 실패 시 어떤 probe 가 깨졌는지 `provider_probe` 또는 stderr 에 남긴다
- `chalna` 는 현재 deep health API 가 없으므로 당장은 endpoint/binary 존재 수준만 본다
- TODO: Chalna 가 실제 transcription health/test API 를 제공하면 `doctor` 는 실제 짧은 transcription probe 까지 수행해야 한다

### `avid-cli transcribe`

최소 artifact:
- `artifacts.srt`

예시:

```bash
avid-cli transcribe sample.mp4 -l ko -d /tmp/out --json
```

### `avid-cli transcript-overview`

최소 artifact:
- `artifacts.storyline`

예시:

```bash
avid-cli transcript-overview sample.srt -o /tmp/out/storyline.json --provider claude --provider-model claude-opus-4-6 --provider-effort medium --json
```

### `avid-cli subtitle-cut`

최소 artifact:
- `artifacts.project_json`
- `artifacts.fcpxml`
- `artifacts.report`
- `artifacts.srt` if transcription exists

예시:

```bash
avid-cli subtitle-cut lecture.mp4 --srt lecture.srt --context lecture.storyline.json -d /tmp/out --provider claude --provider-model claude-opus-4-6 --provider-effort medium --json
```

### `avid-cli podcast-cut`

최소 artifact:
- `artifacts.project_json`
- `artifacts.fcpxml`
- `artifacts.report`
- `artifacts.srt`

예시:

```bash
avid-cli podcast-cut podcast.mp4 --srt podcast.srt --context podcast.storyline.json -d /tmp/out --provider codex --provider-model gpt-5.4 --provider-effort medium --json
```

### `avid-cli apply-evaluation`

용도:
- 기존 `.avid.json` 에 human evaluation override 만 적용
- media 파일 없이 project JSON 만 갱신

상태:
- 현재 구현되어 있다
- `reexport` 분해의 1차 명령으로 본다
- 상위 통합은 evaluation-only 재처리에서 이 명령을 우선 사용하도록 수렴한다

최소 artifact:
- `artifacts.project_json`

최소 stats:
- `stats.applied_evaluation_segments`
- `stats.applied_changes`

예시:

```bash
avid-cli apply-evaluation \
  --project-json /tmp/in/project.avid.json \
  --evaluation /tmp/in/evaluation.json \
  --output-project-json /tmp/out/project.avid.json \
  --json
```

보조 규칙:
- 평가 JSON 은 list 자체이거나 `{ "segments": [...] }` 형태를 허용한다
- `human.action == keep` 은 겹치는 기존 cut decision 을 제거하는 방식으로 해석한다
- `human.action == cut` 은 manual cut decision 추가로 해석한다

### `avid-cli export-project`

용도:
- 준비된 `.avid.json` 을 FCPXML / adjusted SRT 로 export
- project JSON 자체는 수정하지 않는다

상태:
- 현재 구현되어 있다
- `reexport` 분해의 2차 명령으로 본다
- 상위 통합은 단계별 project JSON 을 만든 뒤 이 명령으로 산출물만 생성하도록 수렴한다

최소 artifact:
- `artifacts.fcpxml`
- `artifacts.srt` if transcription exists

예시:

```bash
avid-cli export-project \
  --project-json /tmp/in/project.avid.json \
  --output-dir /tmp/out \
  --content-mode cut \
  --json
```

보조 규칙:
- `--output` 이 없으면 primary source 이름 기준으로 `<base>_subtitle_cut.fcpxml` 을 생성한다
- `report` 는 생성하지 않는다
- `silence-mode`, `content-mode` 만 export 방식에 영향 준다

### `avid-cli reexport`

용도:
- 기존 `.avid.json` 에 human evaluation override 적용
- 기존 `.avid.json` 에 extra source 를 다시 붙여 재-export
- 상위 시스템은 이 명령으로 direct import 없이 재-export 한다

상태:
- 현재 구현은 유지한다
- 하지만 이 명령은 여러 책임을 한 번에 수행하므로 deprecated wrapper 로 전환할 예정이다
- `apply-evaluation`, `export-project` 는 이미 구현되었고, 나머지 `rebuild-multicam` + `clear-extra-sources` 로 계속 분리한다
- 분해 계획은 [REEXPORT_SPLIT_PLAN.md](REEXPORT_SPLIT_PLAN.md) 를 본다

최소 artifact:
- `artifacts.project_json`
- `artifacts.fcpxml`
- `artifacts.srt` if transcription exists

예시:

```bash
avid-cli reexport \
  --project-json /tmp/in/project.avid.json \
  --output-dir /tmp/out \
  --evaluation /tmp/in/evaluation.json \
  --source /tmp/in/main.mp4 \
  --extra-source /tmp/in/cam2.mp4 \
  --json
```

`reexport` 보조 규칙:
- `--extra-source` 를 쓰면 `--source` 가 필요하다
- 평가 JSON 은 list 자체이거나 `{ "segments": [...] }` 형태를 허용한다
- 기존 extra source 가 이미 프로젝트에 있으면 먼저 벗겨내고 다시 구성한다
- 새 통합은 가능하면 `reexport` 대신 분리된 명령으로 수렴해야 한다

## Artifact key 규칙

외부 통합에서 아래 key 이름은 고정으로 본다.

- `srt`
- `storyline`
- `project_json`
- `fcpxml`
- `report`
- `srt_raw`

추가 key 를 넣는 것은 허용하지만, 기존 key 를 제거/개명하면 breaking change 로 본다.

## Breaking change 규칙

아래 변경은 breaking change 로 취급한다.

- 명령 이름 변경
- 옵션 이름 삭제/변경
- 필수 artifact key 변경
- `--json` 결과 shape 에서 핵심 필드 삭제
- 실패 시 exit 규칙 변경

이런 변경을 할 때는 반드시 같이 해야 한다.

1. 이 문서 수정
2. CLI 테스트 수정
3. 루트 README / SPEC 업데이트
4. 상위 통합 저장소 검토
