# AVID Backend Testing Strategy

> 목표: `avid-cli` 표면을 먼저 고정하고, 그 다음 서비스/내보내기/live dependency 테스트를 쌓는다.
> 원칙: `eogum` 연결 전에 `auto-video-edit` 자체 테스트가 먼저 돌아야 한다.

## 관련 문서

- [CLI_INTERFACE.md](CLI_INTERFACE.md)
- [TEST_API_SPECS.md](TEST_API_SPECS.md)
- [TEST_DATA_GUIDE.md](TEST_DATA_GUIDE.md)
- [PROVIDER_RUNTIME_SPEC.md](PROVIDER_RUNTIME_SPEC.md)

## 왜 CLI부터 테스트하나

지금 상위 시스템이 의존하는 것은 `avid` 내부 Python 객체가 아니라 `avid-cli` 표면이다.
따라서 가장 먼저 검증해야 하는 것은 아래다.

- 명령이 존재하는가
- 옵션 이름이 고정돼 있는가
- `--json` / `--manifest-out` 결과 shape 가 안정적인가
- 결과물 artifact key 가 일정한가
- 실패 시 exit/stderr 규칙이 예측 가능한가

## 테스트 계층

### 1. Unit

범위:
- pure helper 함수
- provider config resolution
- provider argv mapping
- evaluation override 적용
- extra source stripping
- JSON payload 생성 규칙
- manifest 파일 기록 규칙

특징:
- ffmpeg 불필요
- Chalna 불필요
- provider CLI 불필요
- 빠르게 돌아야 함

### 2. CLI Integration

범위:
- 실제 `avid-cli` subprocess 실행
- 샘플 fixture 입력으로 artifact key / 파일 생성 확인
- `--json` stdout 과 `--manifest-out` 파일의 일치 확인

특징:
- 가능한 한 외부 네트워크 없이
- 필요한 부분은 monkeypatch / fixture file 사용
- 상위 시스템이 실제로 보는 표면을 검증

### 3. Live Smoke

범위:
- `doctor` 로 실제 환경 진단
- live Chalna 로 `transcribe`
- live provider 로 `transcript-overview` / `subtitle-cut` / `podcast-cut`
- provider smoke 는 가능한 한 짧은 prompt 와 저비용 설정으로 실행한다
- `audio-offset-finder` 가 설치된 상태의 sync smoke

특징:
- 느리고 flaky 할 수 있음
- 기본 test run 에서 분리
- opt-in marker 로만 실행

## 권장 테스트 디렉터리 구조

```text
apps/backend/tests/
  unit/
    cli/
      test_version.py
      test_doctor.py
      test_provider_resolution.py
      test_provider_argv.py
      test_manifest_output.py
      test_apply_evaluation.py
      test_export_project.py
      test_rebuild_multicam.py
      test_clear_extra_sources.py
      test_reexport_logic.py
      test_multicam_contract.py
    export/
      test_fcpxml_modes.py
      test_fcpxml_multicam.py
      test_adjusted_srt_consistency.py
    services/
      test_audio_sync_offsets.py
  integration/
    cli/
      test_cli_contract.py
      test_cli_reexport_contract.py
  live/
    test_doctor_live.py
    test_provider_profiles_live.py
    test_transcribe_live.py
    test_sync_live.py
```

## 우선순위별 테스트 목록

## `reexport` 분해 메모

- 현재 `reexport` 는 compatibility wrapper 로 유지한다.
- `apply-evaluation`, `export-project`, `rebuild-multicam`, `clear-extra-sources` 는 구현 완료, 다음 목표는 deprecated `reexport` parity 와 상위 통합 교체다.
- 새 테스트는 가능하면 분리된 명령을 우선 대상으로 하고, `reexport` 는 parity / deprecation coverage 로 남긴다.
- 자세한 계획은 [REEXPORT_SPLIT_PLAN.md](REEXPORT_SPLIT_PLAN.md) 를 본다.

### P0: 상위 통합 전에 반드시 있어야 하는 것

- `version --json` 이 유효한 JSON 을 반환하고 핵심 필드를 포함한다
- `doctor --json` 이 `checks.python/ffmpeg/ffprobe/chalna/provider` 를 반환한다
- 기본 `doctor --json` 은 provider binary 존재만 검사하고 `provider_probes` 는 비워 둔다
- `doctor --probe-providers --json` 의 provider check 가 실제 작은 `claude`/`codex` 호출을 수행한다
- `doctor --json` 결과에 resolved `provider/model/effort` 가 single-provider에서는 `provider_config`, multi-provider에서는 `provider_configs` 로 남는다
- 기본 doctor 출력에는 정밀체크 안내 hint 가 포함된다
- `doctor --json` 결과에 provider smoke 에 사용한 `model` 과 `reasoning_effort` 또는 동등 옵션 정보가 남는다
- AI 명령들이 CLI flag > env > default 우선순위로 같은 provider config 를 해석한다
- `--manifest-out` 이 stdout JSON 과 같은 payload 를 기록한다
- `apply-evaluation --json` 이 `project_json` artifact 와 `applied_evaluation_segments/applied_changes` stats 를 반환한다
- `export-project --json` 이 `fcpxml/srt?` artifact 를 반환한다
- `rebuild-multicam --json` 이 `project_json` artifact 와 `extra_sources/stripped_extra_sources` stats 를 반환한다
- `clear-extra-sources --json` 이 `project_json` artifact 와 `stripped_extra_sources` stats 를 반환한다
- `transcribe --json` 이 `artifacts.srt` 를 반환한다
- `transcript-overview --json` 이 `artifacts.storyline` 을 반환한다
- `subtitle-cut --json` 이 `project_json/fcpxml/report/srt` key 를 반환한다
- `podcast-cut --json` 이 `project_json/fcpxml/report/srt` key 를 반환한다
- `reexport --json` 이 `project_json/fcpxml/srt?` key 를 반환한다
- `reexport` 에서 `--extra-source` 사용 시 `--source` 가 없으면 실패한다
- 잘못된 입력 파일 경로에서 exit code 가 non-zero 이고 stderr 로 실패 이유를 남긴다

### P1: 구현 회귀를 막기 위한 것

- Claude argv 가 `--model` / `--effort` 를 포함해 생성된다
- Codex argv 가 `-m` / `-c model_reasoning_effort=...` 를 포함해 생성된다
- provider-specific env 가 올바르게 해석된다
- evaluation override 가 기존 overlapping decision 을 제거하고 human cut 을 다시 추가한다
- `reexport` 가 기존 extra source 를 제거한 뒤 새 extra source 를 다시 붙인다
- multicam case 에서 auto sync 와 manual offset 둘 다 기대대로 반영된다
- review/final 모드에 따라 `content_mode` 가 기대대로 반영된다
- subtitle/podcast cut 에서 report artifact 가 항상 생긴다
- 모든 핵심 경로에서 `fcpxml` artifact 가 생성되고 XML 파싱 가능하다
- transcription 이 있는 project 를 reexport 하면 adjusted SRT 가 같이 나온다
- adjusted SRT 와 FCPXML cut 결과가 시간적으로 일관된다

### P2: live dependency 검증

- `doctor` 가 실제 설치 환경을 통과한다
- 기본 `doctor --json` 실행이 `claude` 와 `codex` binary 를 둘 다 확인한다
- `doctor --probe-providers --json` 실행이 실제 Claude/Codex 호출까지 수행한다
- provider live smoke 가 실제 API/auth/model/reasoning 옵션 조합으로 통과한다
- baseline profile 은 `claude-opus-4-6 + medium`, `gpt-5.4 + medium` 으로 1회 이상 검증한다
- TODO: Chalna 가 deep health/test API 를 제공하면 doctor live smoke 에 실제 transcription probe 를 추가한다
- 작은 fixture 로 `transcribe` live smoke 가 통과한다
- 작은 fixture 로 `transcript-overview` live smoke 가 통과한다
- 작은 fixture 로 `subtitle-cut` 또는 `podcast-cut` live smoke 가 통과한다
- sample pair 로 audio sync smoke 가 통과한다
- multicam export 결과를 수동으로 열어 connected clip 구조를 spot-check 한다

## 추천 pytest marker

- `unit`
- `integration`
- `live`
- `ffmpeg`
- `chalna`
- `provider`
- `sync`

예시:

```python
import pytest

pytestmark = [pytest.mark.integration]
```

## 분해 후 우선 테스트 순서

1. `tests/unit/cli/test_apply_evaluation.py`
2. `tests/integration/cli/test_export_project_contract.py`
3. `tests/integration/cli/test_rebuild_multicam_contract.py`
4. `tests/integration/cli/test_cli_reexport_compat.py`

## 실행 명령 제안

초기 세팅:

```bash
cd apps/backend
pip install -e '.[dev,sync]'
```

기본 unit run:

```bash
PYTHONPATH=src pytest tests/unit -q
```

CLI integration run:

```bash
PYTHONPATH=src pytest tests/integration/cli -q
```

live smoke run:

```bash
PYTHONPATH=src pytest tests/live -m live -q
```

전체 coverage run:

```bash
PYTHONPATH=src pytest --cov=src/avid --cov-report=term-missing
```

## Fixture 전략

가장 먼저 준비할 fixture 는 아래다.

- 아주 짧은 `sample.srt`
- 최소 구조의 `storyline.json`
- transcription 과 edit decision 이 들어 있는 작은 `sample.avid.json`
- human override 가 2~3개 들어 있는 `evaluation.json`
- live test 에만 쓸 아주 짧은 미디어 fixture

원칙:
- unit/integration 은 최대한 텍스트 기반 fixture 로 끝낸다
- 무거운 미디어 fixture 는 live test 에만 둔다
- provider/chalna 의 실제 호출은 opt-in 으로만 돌린다

## 구현 순서 제안

1. `tests/unit/cli/test_version.py`
2. `tests/unit/cli/test_provider_resolution.py`
3. `tests/unit/cli/test_provider_argv.py`
4. `tests/unit/cli/test_doctor.py`
5. `tests/unit/cli/test_manifest_output.py`
6. `tests/unit/cli/test_apply_evaluation.py`
7. `tests/unit/cli/test_export_project.py`
8. `tests/unit/cli/test_rebuild_multicam.py`
9. `tests/unit/cli/test_clear_extra_sources.py`
10. `tests/unit/cli/test_reexport_logic.py`
11. `tests/integration/cli/test_cli_contract.py`
12. `tests/integration/cli/test_cli_reexport_contract.py`
13. `tests/unit/export/test_fcpxml_multicam.py`
14. `tests/unit/export/test_adjusted_srt_consistency.py`
15. 마지막으로 `tests/live/*`

## eogum 연결 전 완료 기준

- [ ] `CLI_INTERFACE.md` 가 현재 구현과 일치
- [ ] P0 테스트가 모두 green
- [ ] `reexport` 포함 모든 핵심 명령이 `--json` 지원
- [ ] `--manifest-out` contract 확인 완료
- [ ] live smoke 는 최소 1회 수동 통과
- [ ] 그 다음에만 `eogum` 통합 수정
