# AVID Backend Manual Verification

> 목표: 실제 작업 순서 그대로 `avid-cli` 를 검증한다.
> 원칙: `reexport` 로 시작하지 않고, source input 부터 final FCPXML 까지 따라간다.

## 관련 문서

- [CLI_INTERFACE.md](CLI_INTERFACE.md)
- [TEST_API_SPECS.md](TEST_API_SPECS.md)
- [TEST_DATA_GUIDE.md](TEST_DATA_GUIDE.md)
- [PROVIDER_RUNTIME_SPEC.md](PROVIDER_RUNTIME_SPEC.md)
- [REEXPORT_SPLIT_PLAN.md](REEXPORT_SPLIT_PLAN.md)

## 기본 원칙

- 자동화된 테스트 스위트는 유지하지 않는다.
- 검증은 실제 `avid-cli` 명령을 직접 돌려서 본다.
- 기본 워크플로우는 아래 순서다.
  - source input
  - `transcribe`
  - `transcript-overview`
  - `subtitle-cut` 또는 `podcast-cut`
  - `review-segments`
  - `apply-evaluation`
  - `rebuild-multicam`
  - `export-project`
  - Final Cut Pro 에서 FCPXML 확인
- `reexport` 는 compatibility check 용으로만 마지막에 본다.

## 준비

```bash
REPO_ROOT=/home/jonhpark/workspace/auto-video-edit
TMP_DIR=/tmp/avid-workflow
mkdir -p "$TMP_DIR"

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

## Canonical Workflow Scenario

기본 시나리오는 아래 source 를 쓴다.

- 메인 source: `samples/test_multisource/main_live.mp4`
- extra source: `samples/test_multisource/cam_sony.mp4`
- 참고 artifact:
  - `samples/test_multisource/main_live.srt`
  - `samples/test_multisource/main_live.storyline.json`
  - `samples/test_multisource/main_live.podcast.avid.json`
  - `samples/test_multisource/main_live.final.fcpxml`

### 0. Preflight

목적:
- workflow 를 시작하기 전에 런타임이 살아 있는지 본다.

```bash
avid-cli doctor --json
avid-cli doctor --probe-providers --json
```

### 1. Source -> SRT

목적:
- 원본 소스에서 자막이 생성되는지 본다.

```bash
avid-cli transcribe \
  samples/test_multisource/main_live.mp4 \
  -d "$TMP_DIR/01_transcribe" \
  --json
```

기대 결과:

- `artifacts.srt` 생성
- 결과 파일이 `samples/test_multisource/main_live.srt` 와 같은 종류의 출력인지 확인

### 2. SRT -> Storyline

목적:
- 생성된 SRT 를 기반으로 story analysis 가 되는지 본다.

```bash
avid-cli transcript-overview \
  "$TMP_DIR/01_transcribe/main_live.srt" \
  -o "$TMP_DIR/02_overview/main_live.storyline.json" \
  --content-type podcast \
  --provider codex \
  --provider-model gpt-5.4 \
  --provider-effort medium \
  --json
```

기대 결과:

- `artifacts.storyline` 생성
- chapter / dependency / key moment 가 채워짐
- 결과 shape 가 `samples/test_multisource/main_live.storyline.json` 과 같은 계열인지 확인

### 3. Storyline -> Initial Edit Decisions

목적:
- source + srt + storyline 를 기반으로 initial cut/edit decision 이 생성되는지 본다.

```bash
avid-cli podcast-cut \
  samples/test_multisource/main_live.mp4 \
  --srt "$TMP_DIR/01_transcribe/main_live.srt" \
  --context "$TMP_DIR/02_overview/main_live.storyline.json" \
  --provider codex \
  --provider-model gpt-5.4 \
  --provider-effort medium \
  -d "$TMP_DIR/03_cut" \
  --json
```

기대 결과:

- `artifacts.project_json` 생성
- `artifacts.fcpxml`, `artifacts.report`, `artifacts.srt` 도 같이 생성될 수 있음
- 여기서 중요한 것은 **initial project JSON / edit decisions 가 생겼는지**다
- final delivery 검증은 아직 하지 않는다

참고:

- 강의형 워크플로우를 보고 싶으면 `podcast-cut` 대신 `subtitle-cut` 을 쓰면 된다.

### 4. Review Payload

목적:
- 엔진이 review payload 를 직접 내보내는지 본다.

```bash
mkdir -p "$TMP_DIR/04_review"
avid-cli review-segments \
  --project-json "$TMP_DIR/03_cut/main_live.podcast.avid.json" \
  --json > "$TMP_DIR/04_review/main_live.review.json"
```

기대 결과:

- `schema_version=review-segments/v1`
- `segments[].index` 가 transcript segment identity 로 채워짐
- `segments[].ai.source_segment_index` 존재
- 새 project JSON 기준으로 `join_strategy=source_segment_index`

review 입력 준비:

```bash
cp "$TMP_DIR/04_review/main_live.review.json" "$TMP_DIR/04_review/main_live.eval.json"
```

그 다음 `main_live.eval.json` 에서 필요한 `segments[].human` 만 직접 채운다.

### 5. Human Eval Override

목적:
- 사람이 저장한 evaluation 이 initial cut 을 덮어쓰는지 본다.

```bash
avid-cli apply-evaluation \
  --project-json "$TMP_DIR/03_cut/main_live.podcast.avid.json" \
  --evaluation "$TMP_DIR/04_review/main_live.eval.json" \
  --output-project-json "$TMP_DIR/04_eval/main_live.eval.avid.json" \
  --json
```

기대 결과:

- `artifacts.project_json` 생성
- `stats.applied_evaluation_segments` 존재
- `stats.join_strategy=source_segment_index`
- keep/cut override 가 실제로 반영됨

legacy 확인:

- old sample project 에 대해서는 `stats.join_strategy=legacy_overlap`
- stderr 에 deprecated warning 이 보여야 함

### 6. Multicam Add

목적:
- 사람 평가가 반영된 project JSON 에 extra source 를 붙인다.

```bash
avid-cli rebuild-multicam \
  --project-json "$TMP_DIR/04_eval/main_live.eval.avid.json" \
  --source samples/test_multisource/main_live.mp4 \
  --extra-source samples/test_multisource/cam_sony.mp4 \
  --offset 0 \
  --output-project-json "$TMP_DIR/05_multicam/main_live.multicam.avid.json" \
  --json
```

기대 결과:

- `stats.extra_sources` 가 `1`
- 결과 project JSON 에 secondary source 와 track 이 추가됨

### 7. Final Export

목적:
- human eval + multicam 이 반영된 최종 project JSON 에서 FCPXML 을 만든다.

```bash
avid-cli export-project \
  --project-json "$TMP_DIR/05_multicam/main_live.multicam.avid.json" \
  --output-dir "$TMP_DIR/06_export" \
  --content-mode cut \
  --json
```

기대 결과:

- `artifacts.fcpxml` 생성
- transcription 이 있으면 `artifacts.srt` 생성
- **이 단계의 FCPXML 이 최종 확인 대상**이다

### 8. Final Cut Pro Check

목적:
- 실제 편집기에서 결과가 자연스러운지 본다.

우선 볼 것:

- connected clip 이 붙는지
- manual offset 이 어긋나지 않는지
- human eval 로 keep/cut 한 부분이 기대대로 보이는지
- adjusted SRT 와 cut 결과가 크게 어긋나지 않는지

### 9. Optional Cleanup Path

목적:
- multicam 을 붙였다가 다시 single-source 로 되돌리는 명시적 경로를 본다.

```bash
avid-cli clear-extra-sources \
  --project-json "$TMP_DIR/05_multicam/main_live.multicam.avid.json" \
  --output-project-json "$TMP_DIR/07_cleared/main_live.cleared.avid.json" \
  --json
```

이건 기본 workflow 가 아니라 maintenance path 로 본다.

### 10. Compatibility Only: `reexport`

목적:
- legacy wrapper 가 아직 동작하는지만 본다.

```bash
avid-cli reexport \
  --project-json "$TMP_DIR/03_cut/main_live.podcast.avid.json" \
  --evaluation "$TMP_DIR/04_review/main_live.eval.json" \
  --source samples/test_multisource/main_live.mp4 \
  --extra-source samples/test_multisource/cam_sony.mp4 \
  --offset 0 \
  --output-dir "$TMP_DIR/08_reexport" \
  --content-mode cut \
  --json
```

기대 결과:

- stderr 에 deprecated warning
- split workflow 와 같은 계열의 artifact 생성
- **주 워크플로우 검증은 이 명령으로 하지 않는다**

## 실패 시 먼저 볼 것

- `doctor --json`
- `doctor --probe-providers --json`
- 입력 경로 오타
- `AVID_*`, `CLAUDE_*`, `CODEX_*`, `CHALNA_*` 환경 변수
- `ffmpeg`, `ffprobe`, `audio-offset-finder` 설치 여부

## 완료 기준

- [ ] preflight doctor 통과
- [ ] `transcribe` 통과
- [ ] `transcript-overview` 통과
- [ ] initial `podcast-cut` 또는 `subtitle-cut` 통과
- [ ] `apply-evaluation` 통과
- [ ] `rebuild-multicam` 통과
- [ ] `export-project` 통과
- [ ] 최종 FCPXML 을 Final Cut Pro 에서 열어 확인
- [ ] deprecated `reexport` 는 compatibility 용으로만 확인
