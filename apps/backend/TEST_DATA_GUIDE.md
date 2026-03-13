# AVID Manual Data Guide

> 목적: 실제 workflow 검증에 어떤 source 와 reference 를 어떤 순서로 볼지 고정한다.
> 원칙: source -> srt -> storyline -> project_json -> human eval -> multicam -> fcpxml 순서를 그대로 따라가게 한다.

## 1. 주 workflow 데이터

현재 canonical workflow sample 은 `samples/test_multisource/` 다.

주요 파일:

- source input: `samples/test_multisource/main_live.mp4`
- extra source: `samples/test_multisource/cam_sony.mp4`
- transcribe reference: `samples/test_multisource/main_live.srt`
- overview reference: `samples/test_multisource/main_live.storyline.json`
- initial cut reference: `samples/test_multisource/main_live.podcast.avid.json`
- final export reference: `samples/test_multisource/main_live.final.fcpxml`
- review payload input: runtime 에서 생성한 `$TMP_DIR/04_review/main_live.review.json`
- human eval input: review payload 를 복사해 만든 `$TMP_DIR/04_review/main_live.eval.json`

이 세트 하나로 아래를 전부 볼 수 있다.

- source -> srt
- srt -> storyline
- storyline -> initial edit decision
- human eval override
- multicam add
- final fcpxml export

## 2. 보조 데이터

### `apps/backend/manual-fixtures/text/`

용도:

- 작은 SRT/JSON 입력
- provider smoke prompt
- 강의형 / single-source 보조 시나리오

주요 파일:

- `c1718_compressed.srt`
- `c1718_compressed.storyline.json`
- `provider_smoke_prompt.txt`

### `apps/backend/manual-fixtures/historical/20260207_192336/`

용도:

- single-source historical reference
- `apply-evaluation`, deprecated `reexport`, export 결과 shape 확인

### `apps/backend/manual-fixtures/snapshots/`

용도:

- FCPXML / adjusted SRT 비교
- two-pass reference 확인

## 3. 리뷰 순서

실제 workflow 기준 리뷰 순서는 아래가 맞다.

1. `samples/test_multisource/main_live.mp4`
2. `samples/test_multisource/main_live.srt`
3. `samples/test_multisource/main_live.storyline.json`
4. `samples/test_multisource/main_live.podcast.avid.json`
5. runtime 에서 생성한 `04_review/main_live.review.json`
6. 사람이 `human` 필드를 채운 `04_review/main_live.eval.json`
7. `samples/test_multisource/cam_sony.mp4`
8. `samples/test_multisource/main_live.final.fcpxml`
9. 보조로 `apps/backend/manual-fixtures/historical/20260207_192336/`

## 4. 언제 무엇을 쓰나

### source -> srt 검증

- `samples/test_multisource/main_live.mp4`

### srt -> storyline 검증

- 생성한 `main_live.srt`
- reference 로 `samples/test_multisource/main_live.storyline.json`

### initial cut 검증

- 생성한 `main_live.podcast.avid.json`
- reference 로 `samples/test_multisource/main_live.podcast.avid.json`

### human eval 검증

- `review-segments` 로 생성한 `main_live.review.json`
- 그 파일을 복사하고 `segments[].human` 만 채운 `main_live.eval.json`

### multicam 검증

- `samples/test_multisource/cam_sony.mp4`

### final export 검증

- 생성한 최종 FCPXML
- reference 로 `samples/test_multisource/main_live.final.fcpxml`

## 5. doctor 검토 포인트

- 기본 `doctor --json` 은 빠르게 binary 와 runtime 만 확인해야 한다.
- `doctor --probe-providers --json` 은 실제 Claude/Codex 호출을 확인해야 한다.
- Chalna 는 현재 deep probe API 가 없으므로 존재/endpoint 수준까지만 본다.

## 6. 관리 원칙

- 새 workflow fixture 는 source 단계가 드러나게 이름을 붙인다.
- canonical human eval 입력은 고정 fixture 가 아니라 `review-segments` 출력에서 만든다.
- 큰 미디어는 계속 `samples/` 에 둔다.
- historical sample 은 날짜 디렉터리로 추가한다.
- scratch output, 로그, 캐시는 fixture 로 승격하지 않는다.
