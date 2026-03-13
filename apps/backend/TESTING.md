# AVID Backend Manual Verification

> 목표: `avid-cli` 표면을 사람이 직접 확인하면서 깨지는 지점을 빠르게 찾는다.
> 원칙: 외부 통합 전에 CLI 입력, 산출물, 오류 처리를 눈으로 검증한다.

## 관련 문서

- [CLI_INTERFACE.md](CLI_INTERFACE.md)
- [TEST_API_SPECS.md](TEST_API_SPECS.md)
- [TEST_DATA_GUIDE.md](TEST_DATA_GUIDE.md)
- [PROVIDER_RUNTIME_SPEC.md](PROVIDER_RUNTIME_SPEC.md)
- [REEXPORT_SPLIT_PLAN.md](REEXPORT_SPLIT_PLAN.md)

## 기본 원칙

- 자동화된 테스트 스위트는 유지하지 않는다.
- 검증은 실제 `avid-cli` 명령을 직접 돌려서 본다.
- 결과 확인은 세 가지로 한다.
  - stdout/stderr
  - `--json` 또는 `--manifest-out` payload
  - 실제 생성된 산출물 파일

## 준비

```bash
REPO_ROOT=/home/jonhpark/workspace/auto-video-edit
cd "$REPO_ROOT/apps/backend"
pip install -e '.[sync]'
cd "$REPO_ROOT"
```

필수 의존성:

- `ffmpeg`
- `ffprobe`
- `git`

선택 의존성:

- `claude`
- `codex`
- Chalna
- `audio-offset-finder`

## 검증 순서

### 1. Fast doctor

목적:
- 바이너리와 기본 런타임이 즉시 살아 있는지 본다.

명령:

```bash
avid-cli doctor --json
```

기대 결과:

- exit code `0`
- `checks.python`, `checks.ffmpeg`, `checks.ffprobe`, `checks.provider` 존재
- `provider_probe_requested` 는 `false`
- `provider_probes` 는 비어 있음
- deep probe 안내 hint 가 출력에 포함됨

### 2. Deep doctor

목적:
- Claude/Codex API 인증과 실제 짧은 호출이 되는지 본다.

명령:

```bash
avid-cli doctor --probe-providers --json
```

단일 provider override:

```bash
avid-cli doctor --provider claude --probe-providers --provider-model claude-opus-4-6 --provider-effort medium --json
avid-cli doctor --provider codex --probe-providers --provider-model gpt-5.4 --provider-effort medium --json
```

기대 결과:

- `provider_configs` 또는 `provider_config` 에 resolved `provider/model/effort` 가 남음
- `provider_probes` 또는 `provider_probe` 에 실제 응답 요약이 남음
- 실패 시 어떤 provider/model/effort 조합에서 실패했는지 바로 보임

### 3. `apply-evaluation`

목적:
- 기존 `.avid.json` 의 cut decision 이 사람 평가로 patch 되는지 본다.

준비:

```bash
TMP_DIR=/tmp/avid-manual
mkdir -p "$TMP_DIR"
cat > "$TMP_DIR/evaluation.json" <<'EOF'
{
  "segments": [
    {
      "start_ms": 2720,
      "end_ms": 3699,
      "human": {"action": "keep"}
    },
    {
      "start_ms": 16000,
      "end_ms": 17000,
      "human": {"action": "cut"}
    }
  ]
}
EOF
```

명령:

```bash
avid-cli apply-evaluation \
  --project-json apps/backend/manual-fixtures/historical/20260207_192336/podcast_cut_final/source.podcast.avid.json \
  --evaluation "$TMP_DIR/evaluation.json" \
  --output-project-json "$TMP_DIR/source.eval.avid.json" \
  --json
```

기대 결과:

- `artifacts.project_json` 생성
- `stats.applied_evaluation_segments` 가 `2`
- `stats.applied_changes` 가 `1` 이상
- 결과 project JSON 에서 `2720-3699` 구간 기존 cut overlap 이 줄어들거나 사라짐

### 4. `export-project`

목적:
- project JSON 만으로 FCPXML/SRT 산출물이 다시 생성되는지 본다.

명령:

```bash
avid-cli export-project \
  --project-json "$TMP_DIR/source.eval.avid.json" \
  --output-dir "$TMP_DIR/exported" \
  --content-mode cut \
  --json
```

기대 결과:

- `artifacts.fcpxml` 생성
- transcription 이 있으면 `artifacts.srt` 생성
- `report` 는 생성하지 않음

### 5. `rebuild-multicam`

목적:
- extra source strip 후 재구성, manual offset 반영을 본다.

명령:

```bash
avid-cli rebuild-multicam \
  --project-json samples/test_multisource/main_live.podcast.avid.json \
  --source samples/test_multisource/main_live.mp4 \
  --extra-source samples/test_multisource/cam_sony.mp4 \
  --offset 0 \
  --output-project-json "$TMP_DIR/main_live.multicam.avid.json" \
  --json
```

기대 결과:

- `stats.extra_sources` 가 `1`
- `stats.stripped_extra_sources` 가 `1` 이상
- 결과 project JSON 의 source/tracks 에 secondary source 가 들어감

### 6. `clear-extra-sources`

목적:
- multicam project 를 single-source 로 명시적으로 되돌린다.

명령:

```bash
avid-cli clear-extra-sources \
  --project-json samples/test_multisource/main_live.podcast.avid.json \
  --output-project-json "$TMP_DIR/main_live.cleared.avid.json" \
  --json
```

기대 결과:

- `stats.stripped_extra_sources` 가 `1` 이상
- 결과 project JSON 에 extra source 가 남지 않음

### 7. Deprecated `reexport`

목적:
- compatibility wrapper 가 아직 동작하는지 본다.

명령:

```bash
avid-cli reexport \
  --project-json samples/test_multisource/main_live.podcast.avid.json \
  --output-dir "$TMP_DIR/reexported" \
  --content-mode disabled \
  --json
```

기대 결과:

- stderr 에 deprecated warning
- `project_json`, `fcpxml`, `srt` artifact 가 생성됨
- legacy wrapper 이지만 split 명령과 같은 결과 계열을 유지함

### 8. `transcribe`, `transcript-overview`, `subtitle-cut`, `podcast-cut`

목적:
- live dependency 가 실제로 동작하는지 본다.

권장 순서:

```bash
avid-cli transcribe samples/sample_10min.m4a -d "$TMP_DIR/transcribe" --json
avid-cli transcript-overview apps/backend/manual-fixtures/text/e2e_source.srt --provider claude --json
avid-cli subtitle-cut samples/C1718_compressed.mp4 --srt apps/backend/manual-fixtures/text/c1718_compressed.srt --provider claude --json
avid-cli podcast-cut samples/sample_10min.m4a --srt apps/backend/manual-fixtures/historical/20260207_192336/source.srt --provider codex --json
```

기대 결과:

- 각 명령이 `artifacts.*` 를 남김
- 실패 시 stderr 에 dependency 또는 provider 원인이 드러남

### 9. FCPXML 수동 검토

목적:
- 생성된 FCPXML 을 실제 편집기에서 열어 구조를 확인한다.

우선 확인할 것:

- single-source 에서 lane 이 과하게 생기지 않는지
- multicam 에서 connected clip 이 붙는지
- manual offset 을 준 source 가 시각적으로 맞는지
- adjusted SRT 와 cut 결과가 크게 어긋나지 않는지

## 실패 시 먼저 볼 것

- `doctor --json`
- `doctor --probe-providers --json`
- 입력 경로 오타
- `AVID_*`, `CLAUDE_*`, `CODEX_*`, `CHALNA_*` 환경 변수
- `ffmpeg`, `ffprobe`, `audio-offset-finder` 설치 여부

## 완료 기준

- [ ] fast doctor 통과
- [ ] deep doctor 통과
- [ ] `apply-evaluation` 산출물 확인
- [ ] `export-project` 산출물 확인
- [ ] `rebuild-multicam` 산출물 확인
- [ ] `clear-extra-sources` 산출물 확인
- [ ] deprecated `reexport` 동작 확인
- [ ] 최소 1개 FCPXML 을 Final Cut Pro 에서 열어 확인
