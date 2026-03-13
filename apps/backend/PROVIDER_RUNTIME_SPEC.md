# AVID Provider Runtime Spec

> 목적: `avid-cli` 가 `claude` 와 `codex` 를 어떤 모델/effort 조합으로 호출할지 외부에서 제어할 수 있게 하고, 그 표면을 테스트 가능하게 고정한다.
> 원칙: provider 이름만 고정하지 말고, provider별 model/effort 를 CLI와 env 로 주입할 수 있어야 한다.

## 1. 현재 확인한 사실

2026-03-13 기준 로컬에서 아주 작은 smoke call 로 아래를 확인했다.

- `codex exec -m gpt-5.4 -c 'model_reasoning_effort="medium"' ...` 는 실제 응답을 반환했다.
- `claude -p --model claude-opus-4-6 --effort medium ...` 는 실제 응답을 반환했다.
- 현재 `eogum` 은 provider 이름만 넘기고, model/effort 는 `auto-video-edit` 내부 구현에 묻혀 있다.

현재 구현 상태:

- `claude`, `codex` 모두 model/effort 를 CLI 와 env 로 제어할 수 있다.
- 기본 프로필은 `claude-opus-4-6 + medium`, `gpt-5.4 + medium` 이다.
- `doctor` 기본 실행은 빠른 provider binary check 위주로 동작하고, 정밀 probe 는 `--probe-providers` 일 때만 수행한다.

## 2. 목표 상태

`avid-cli` 의 AI 관련 명령은 모두 동일한 provider runtime 표면을 가져야 한다.

적용 대상 명령:

- `doctor`
- `transcript-overview`
- `subtitle-cut`
- `podcast-cut`

이 네 명령은 provider runtime 개념을 공유해야 한다.

- `--provider <claude|codex>`
- `--provider-model <string>`
- `--provider-effort <string>`

이 표면은 model churn 에 대응하기 위해 string passthrough 로 설계한다.
로컬 코드에서 모델 이름을 enum 으로 묶지 않는다.

## 3. 권장 기본 프로필

초기 기본값은 아래처럼 둔다.

- `claude`: model `claude-opus-4-6`, effort `medium`
- `codex`: model `gpt-5.4`, effort `medium`

이 값들은 product default 일 뿐이고, external contract 로는 고정하지 않는다.
계속 바뀔 수 있으므로 env 나 CLI flag 로 쉽게 덮어써야 한다.

## 4. 설정 해석 순서

resolved provider config 는 아래 우선순위로 계산한다.

1. CLI flag
2. provider-specific environment variable
3. baked-in default

권장 env 이름:

- `AVID_CLAUDE_MODEL`
- `AVID_CLAUDE_EFFORT`
- `AVID_CODEX_MODEL`
- `AVID_CODEX_REASONING_EFFORT`

선택적으로 default provider 도 env 로 둘 수 있다.

- `AVID_DEFAULT_PROVIDER`

## 5. 실제 provider CLI 매핑

### Claude

`claude` provider 는 아래처럼 호출한다.

```bash
claude -p \
  --model <resolved_model> \
  --effort <resolved_effort> \
  --output-format text \
  "<prompt>"
```

규칙:

- `--model` 은 alias(`opus`) 또는 full model name(`claude-opus-4-6`) 모두 허용한다.
- `--effort` 는 현재 CLI help 기준 `low`, `medium`, `high`, `max` 를 우선 지원한다.
- model alias 와 full model name 둘 다 smoke test 가능해야 한다.

### Codex

`codex` provider 는 아래처럼 호출한다.

```bash
codex exec \
  -m <resolved_model> \
  -c 'model_reasoning_effort="<resolved_effort>"' \
  --sandbox read-only \
  --skip-git-repo-check \
  -
```

규칙:

- model 이름은 string passthrough 로 둔다.
- reasoning effort 도 string passthrough 로 둔다.
- trusted directory 검사에 걸리지 않도록 `--skip-git-repo-check` 를 항상 포함한다.
- 현재 추천 baseline 은 `gpt-5.4` + `medium` 이다.

## 6. CLI API Spec

### 6.1 공통 옵션 추가

아래 명령에 provider runtime 옵션을 추가한다.

- `avid-cli transcript-overview`
- `avid-cli subtitle-cut`
- `avid-cli podcast-cut`

공통 옵션:

```text
--provider <claude|codex>
--provider-model <string>
--provider-effort <string>
```

`avid-cli doctor` 는 아래 규칙을 따른다.

```text
--provider <claude|codex>   # repeatable, 생략 시 claude+codex 둘 다 대상
--probe-providers          # 실제 Claude/Codex 호출까지 수행
--provider-model <string>   # 단일 provider + --probe-providers 일 때만 허용
--provider-effort <string>  # 단일 provider + --probe-providers 일 때만 허용
```

예시:

```bash
avid-cli doctor --json
```

```bash
avid-cli doctor \
  --provider codex \
  --probe-providers \
  --provider-model gpt-5.4 \
  --provider-effort medium \
  --json
```

```bash
avid-cli transcript-overview source.srt \
  --provider claude \
  --provider-model claude-opus-4-6 \
  --provider-effort medium \
  --json
```

### 6.2 JSON payload 추가

AI 관련 명령의 `--json` 결과에는 resolved provider config 를 넣는다.
단일 provider 명령에서는 `provider_config`, `doctor`의 multi-provider 실행에서는 `provider_configs` 를 넣는다.

```json
{
  "command": "doctor",
  "status": "ok",
  "provider_config": {
    "provider": "claude",
    "model": "claude-opus-4-6",
    "effort": "medium",
    "source": {
      "provider": "cli",
      "model": "env",
      "effort": "default"
    }
  }
}
```

최소 규칙:

- `provider_config.provider`
- `provider_config.model`
- `provider_config.effort`
- `provider_config.source`

### 6.3 doctor probe payload

`doctor --json` 은 기본적으로 binary-only 결과를 반환한다. `--probe-providers` 를 주면 provider smoke 결과를 추가로 포함한다. multi-provider 정밀실행에서는 `provider_probes` map을 반환한다.

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
  "provider_config": {
    "provider": "codex",
    "model": "gpt-5.4",
    "effort": "medium",
    "source": {
      "provider": "cli",
      "model": "cli",
      "effort": "cli"
    }
  },
  "provider_probe": {
    "status": "ok",
    "prompt": "Respond with exactly OK",
    "response": "OK",
    "argv_summary": ["codex", "exec", "-m", "gpt-5.4"]
  }
}
```

규칙:

- 기본 `doctor` 는 binary 존재만 빠르게 확인한다.
- `--probe-providers` 를 주면 아주 짧은 smoke prompt 를 실제 호출한다.
- 응답 본문 전체를 저장할 필요는 없지만, 최소 성공 여부와 요약은 남긴다.
- `chalna` 는 현재 deep health API 가 없으므로 당장은 health endpoint 수준까지만 본다.
- TODO: Chalna 가 test transcription API 를 제공하면 provider probe 와 별개로 transcription probe 를 추가한다.

## 7. 테스트 계획

### P0: provider config 해석 테스트

- CLI flag > env > default 우선순위가 맞는지
- `claude` 선택 시 Claude env 를 읽고 Codex env 는 무시하는지
- `codex` 선택 시 Codex env 를 읽고 Claude env 는 무시하는지
- `provider_config.source` 가 올바르게 기록되는지

### P1: argv mapping 테스트

- Claude가 `--model` 과 `--effort` 를 포함해 호출되는지
- Codex가 `-m` 과 `-c model_reasoning_effort=...` 를 포함해 호출되는지
- invalid effort/model 입력 시 subprocess failure 가 그대로 surface 되는지

### P2: doctor integration test

- `doctor --json` 이 기본적으로 `claude`, `codex` 둘 다 binary-only check 하는지
- `doctor --probe-providers --json` 이 실제 `claude`, `codex` 둘 다 probe 하는지
- `doctor --provider claude --probe-providers --provider-model claude-opus-4-6 --provider-effort medium --json`
- `doctor --provider codex --probe-providers --provider-model gpt-5.4 --provider-effort medium --json`
- multi-provider 기본 실행은 `provider_configs` 를 포함하고 `provider_probes` 는 비어 있는지
- single-provider probe 실행은 `provider_config` 와 `provider_probe` 를 포함하는지
- actual response 가 `OK` 인지

### P3: command propagation test

아래 명령들이 resolved provider config 를 실제 skill layer 까지 전달하는지 확인한다.

- `transcript-overview`
- `subtitle-cut`
- `podcast-cut`

수동 검증에서는 single-provider deep probe 를 직접 돌려, 전달된 `provider/model/effort` 조합이 실제 응답까지 도달하는지 본다.

### P4: optional compatibility matrix

기본 smoke 와 별도 opt-in 으로 아래를 돌린다.

- Claude alias model: `opus`
- Claude full model: `claude-opus-4-6`
- Codex baseline model: `gpt-5.4`
- Codex effort override: `low`, `medium`

matrix 는 env 로 확장 가능하게 둔다.

- `AVID_TEST_CLAUDE_MODELS`
- `AVID_TEST_CLAUDE_EFFORTS`
- `AVID_TEST_CODEX_MODELS`
- `AVID_TEST_CODEX_EFFORTS`

## 8. 추천 검토 순서

1. 이 문서에서 resolution order 와 payload shape 확인
2. [CLI_INTERFACE.md](CLI_INTERFACE.md) 에 공통 옵션이 반영됐는지 확인
3. [TEST_API_SPECS.md](TEST_API_SPECS.md) 의 `doctor` 와 provider 관련 테스트가 충분한지 확인
4. [TESTING.md](TESTING.md) 의 P0/P1/P2 우선순위가 맞는지 확인

## 9. eogum 연동 메모

`eogum` 은 지금 `--provider claude` 만 하드코딩해 넘기고 있다.
`auto-video-edit` 쪽 spec 이 정리되면 `eogum` 도 아래를 따라야 한다.

- provider 이름 하드코딩 제거
- model/effort 도 avid-cli 표면으로 넘길 수 있게 변경
- audit/version 기록에 provider/model/effort 를 함께 남기기
