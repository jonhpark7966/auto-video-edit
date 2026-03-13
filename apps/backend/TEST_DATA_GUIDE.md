# AVID Manual Data Guide

> 목적: 수동 검증에 쓸 source, snapshot, historical sample 을 어디서 볼지 고정한다.
> 원칙: 사람이 직접 돌려볼 때 바로 꺼내 쓸 수 있는 입력만 canonical 로 둔다.

## 1. 현재 canonical 데이터 위치

검증용 데이터는 세 군데로 나뉜다.

- `apps/backend/manual-fixtures/text/`: 작은 SRT/JSON 입력
- `apps/backend/manual-fixtures/snapshots/`: 비교용 산출물 snapshot
- `apps/backend/manual-fixtures/historical/`: 실제 실행에서 남긴 historical sample 세트
- `samples/`: 큰 live media source

scratch 출력은 `output/` 또는 `/tmp` 를 사용하고, canonical fixture 자체는 덮어쓰지 않는다.

## 2. 디렉터리 레이아웃

```text
apps/backend/manual-fixtures/
  text/
    c1718_compressed.srt
    c1718_compressed.storyline.json
    e2e_source.srt
    e2e_source.storyline.json
    e2e_eval_comparison.json
    e2e_summary.json
    provider_smoke_prompt.txt
  snapshots/
    two-pass/
      C1718_subtitle_cut_with_context.avid.json
      C1718_subtitle_cut_with_context.fcpxml
      C1718_two_pass_cut.fcpxml
      C1718_two_pass_cut.srt
      C1718_two_pass_disabled.fcpxml
      C1718_two_pass_disabled.srt
  historical/
    20260207_192336/
      source.mp4
      source.srt
      source.storyline.json
      eval_comparison.json
      podcast_cut_final/
      podcast_cut_review/
      source_podcast_cut_output/
samples/
  test_multisource/
  sample_10min.m4a
  C1718_compressed.mp4
```

## 3. 무엇을 어디에 쓰나

### text

용도:

- `transcript-overview` 입력
- provider smoke prompt
- 작은 JSON/SRT 검증

우선 볼 파일:

- `apps/backend/manual-fixtures/text/c1718_compressed.srt`
- `apps/backend/manual-fixtures/text/e2e_source.srt`
- `apps/backend/manual-fixtures/text/provider_smoke_prompt.txt`

### snapshots

용도:

- FCPXML 비교
- adjusted SRT 비교
- two-pass 결과 비교

우선 볼 파일:

- `apps/backend/manual-fixtures/snapshots/two-pass/C1718_subtitle_cut_with_context.fcpxml`
- `apps/backend/manual-fixtures/snapshots/two-pass/C1718_two_pass_cut.srt`

### historical

용도:

- 이미 한 번 실행된 end-to-end 결과를 기준점으로 삼기
- `apply-evaluation`, `export-project`, deprecated `reexport` 의 입력 source 로 재사용

우선 볼 파일:

- `apps/backend/manual-fixtures/historical/20260207_192336/podcast_cut_final/source.podcast.avid.json`
- `apps/backend/manual-fixtures/historical/20260207_192336/source.mp4`
- `apps/backend/manual-fixtures/historical/20260207_192336/source.srt`

### live media

용도:

- multicam / extra source
- audio sync
- Final Cut Pro 열기 검증

우선 볼 파일:

- `samples/test_multisource/main_live.mp4`
- `samples/test_multisource/cam_sony.mp4`
- `samples/test_multisource/main_live.podcast.avid.json`

## 4. 리뷰 순서

1. [CLI_INTERFACE.md](CLI_INTERFACE.md)
2. [TESTING.md](TESTING.md)
3. [TEST_API_SPECS.md](TEST_API_SPECS.md)
4. `apps/backend/manual-fixtures/text/`
5. `apps/backend/manual-fixtures/historical/20260207_192336/`
6. `samples/test_multisource/`
7. `apps/backend/manual-fixtures/snapshots/two-pass/`

## 5. doctor 검토 포인트

- 기본 `doctor --json` 은 빠르게 binary 와 runtime 만 확인해야 한다.
- `doctor --probe-providers --json` 은 실제 Claude/Codex 호출을 확인해야 한다.
- Chalna 는 현재 deep probe API 가 없으므로 존재/endpoint 수준까지만 본다.

## 6. 관리 원칙

- 새 fixture 는 `manual-fixtures` 아래로 넣는다.
- 큰 미디어는 계속 `samples/` 에 둔다.
- historical sample 은 날짜 디렉터리로 추가한다.
- scratch output, 로그, 캐시는 fixture 로 승격하지 않는다.
