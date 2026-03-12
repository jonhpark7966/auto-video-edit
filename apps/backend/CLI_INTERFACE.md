# AVID CLI Interface

> 목적: 외부 시스템이 믿고 사용할 수 있는 `avid-cli` 표면을 고정한다.
> 원칙: 외부 통합은 `avid-cli` 만 사용하고 `avid.*` 내부 모듈은 직접 import 하지 않는다.

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

예시:

```bash
avid-cli doctor --provider claude --json
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
  }
}
```

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
avid-cli transcript-overview sample.srt -o /tmp/out/storyline.json --provider claude --json
```

### `avid-cli subtitle-cut`

최소 artifact:
- `artifacts.project_json`
- `artifacts.fcpxml`
- `artifacts.report`
- `artifacts.srt` if transcription exists

예시:

```bash
avid-cli subtitle-cut lecture.mp4 --srt lecture.srt --context lecture.storyline.json -d /tmp/out --json
```

### `avid-cli podcast-cut`

최소 artifact:
- `artifacts.project_json`
- `artifacts.fcpxml`
- `artifacts.report`
- `artifacts.srt`

예시:

```bash
avid-cli podcast-cut podcast.mp4 --srt podcast.srt --context podcast.storyline.json -d /tmp/out --json
```

### `avid-cli reexport`

용도:
- 기존 `.avid.json` 에 human evaluation override 적용
- 기존 `.avid.json` 에 extra source 를 다시 붙여 재-export
- 상위 시스템은 이 명령으로 direct import 없이 재-export 한다

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
