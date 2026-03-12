# AVID Test Data Guide

> 목적: 현재 저장소에 흩어져 있는 테스트 데이터를 어떤 기준으로 볼지 정리하고, 리뷰 순서를 고정한다.
> 원칙: 큰 미디어 파일은 섣불리 옮기지 않고, 작은 텍스트 fixture 와 snapshot 부터 canonical 경로를 만든다.

## 1. 지금 상태 요약

현재 테스트 관련 데이터는 네 군데에 나뉘어 있다.

- `tests/`: 기존 unit/e2e 테스트 코드와 일부 e2e 산출물
- `samples/`: 수동 실행과 live smoke 에 쓰인 실제 미디어와 결과물
- `srcs/`: 작은 텍스트 입력과 two-pass 결과 snapshot
- `output/`: 임시/실험/수동 실행 결과물이 섞여 있는 scratch 영역

이 중에서 앞으로 테스트 기준으로 삼을 것은 아래다.

- 작은 deterministic fixture: `tests/fixtures/text/`
- expected output snapshot: `tests/fixtures/snapshots/`
- 큰 live media: 당분간 `samples/`
- scratch output: `output/` 는 기준 데이터로 쓰지 않음

## 2. Canonical Test Data Layout

```text
tests/
  fixtures/
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
    live/
      README.md
samples/
  test_multisource/
  sample_10min.m4a
  C1718_compressed.mp4
```

## 3. Keep / Move / Ignore 기준

### Keep as canonical text fixtures

이 파일들은 작고 deterministic 해서 앞으로 테스트 입력/비교 기준으로 쓰기 좋다.

- `tests/fixtures/text/c1718_compressed.srt`
- `tests/fixtures/text/c1718_compressed.storyline.json`
- `tests/fixtures/text/e2e_source.srt`
- `tests/fixtures/text/e2e_source.storyline.json`
- `tests/fixtures/text/e2e_eval_comparison.json`
- `tests/fixtures/text/e2e_summary.json`
- `tests/fixtures/text/provider_smoke_prompt.txt`

### Keep as canonical snapshot fixtures

이 파일들은 exporter/two-pass 결과 비교에 쓸 수 있다.

- `tests/fixtures/snapshots/two-pass/C1718_subtitle_cut_with_context.avid.json`
- `tests/fixtures/snapshots/two-pass/C1718_subtitle_cut_with_context.fcpxml`
- `tests/fixtures/snapshots/two-pass/C1718_two_pass_cut.fcpxml`
- `tests/fixtures/snapshots/two-pass/C1718_two_pass_cut.srt`
- `tests/fixtures/snapshots/two-pass/C1718_two_pass_disabled.fcpxml`
- `tests/fixtures/snapshots/two-pass/C1718_two_pass_disabled.srt`

### Keep in place as live media fixtures

이 파일들은 크기가 크고 실제 미디어라서 당장은 `samples/` 에 두는 것이 낫다.

- `samples/test_multisource/main_live.mp4`
- `samples/test_multisource/cam_sony.mp4`
- `samples/test_multisource/main_live.srt`
- `samples/test_multisource/main_live.storyline.json`
- `samples/test_multisource/main_live.podcast.avid.json`
- `samples/test_multisource/main_live.final.fcpxml`
- `samples/sample_10min.m4a`
- `samples/C1718_compressed.mp4`
- `samples/trimmed_video.mp4`
- `tests/e2e/data/20260207_192336/source.mp4`

### Do not use as canonical fixtures

이 경로는 scratch 성격이 강하므로 기준 데이터로 직접 의존하지 않는 편이 낫다.

- `output/`
- `output/test/cloudflared.deb`
- `.pytest_cache/`
- `__pycache__/`

## 4. 무엇을 어디에 쓰는가

### text fixtures

용도:
- `transcript-overview` input
- `reexport` evaluation/input JSON
- API validation 테스트용 작은 입력
- provider smoke prompt fixture
- SRT/JSON parser 테스트

### snapshot fixtures

용도:
- FCPXML structure regression
- review/final 비교
- adjusted SRT consistency 비교
- two-pass 결과 회귀 확인

### live media fixtures

용도:
- multicam / extra source sync
- 실제 ffmpeg/ffprobe 의존 경로 검증
- live smoke
- 수동 Final Cut Pro 열기 검증

## 5. 어디부터 보면 되는가

리뷰 순서는 이 순서가 가장 낫다.

1. `apps/backend/CLI_INTERFACE.md`
2. `apps/backend/TEST_DATA_GUIDE.md`
3. `apps/backend/TEST_API_SPECS.md`
4. `apps/backend/TESTING.md`
5. 기존 unit test
   - `tests/unit/test_audio_sync.py`
   - `tests/unit/test_fcpxml_multisource.py`
6. canonical text/snapshot fixture
   - `tests/fixtures/text/`
   - `tests/fixtures/snapshots/two-pass/`
7. live media fixture
   - `samples/test_multisource/`
   - `samples/sample_10min.m4a`
8. 마지막으로 기존 e2e 흐름
   - `tests/e2e/test_podcast_e2e.py`
   - `tests/e2e/data/20260207_192336/`

## 6. 내가 보기엔 지금 가장 먼저 확인할 것

### 1차 검토

- `CLI_INTERFACE.md` 의 artifact key 와 실제 샘플 파일 이름이 맞는지
- `TEST_API_SPECS.md` 의 multicam / FCPXML 섹션이 실제 데이터로 검증 가능한지
- `tests/unit/test_audio_sync.py` 가 현재 `samples/test_multisource` 시나리오와 맞는지
- `tests/unit/test_fcpxml_multisource.py` 가 현재 exporter 기대와 맞는지

### 2차 검토

- `samples/test_multisource/` 를 canonical multicam live set 으로 삼아도 되는지
- `output/` 을 fixture 에서 완전히 제외해도 되는지
- `tests/e2e/data/20260207_192336/` 를 historical snapshot 으로 둘지, 일부를 fixture 로 승격할지

## 7. Doctor 검토 포인트

`doctor` 는 단순 존재 확인 문서가 아니라 실행 가능성 문서로 봐야 한다.

- `claude` / `codex` 는 binary 존재만 확인하면 안 된다
- 아주 작은 smoke prompt 를 실제로 호출해 auth 와 API 경로가 살아 있는지 봐야 한다
- 가능하면 `model`, `reasoning_effort` 또는 동등 옵션을 함께 전달해 옵션 parsing 도 확인해야 한다
- `chalna` 는 현재 deep health/test API 가 없으므로 지금 문서에서는 존재/endpoint 수준까지만 검토한다
- TODO: Chalna 가 짧은 transcription probe API 를 제공하면 fixture 와 live smoke 절차를 이 문서에도 추가한다

## 8. 다음 단계 제안

문서 검토가 끝나면 다음으로 갈 일은 이것이다.

1. `tests/fixtures/` 기준으로 새 테스트 파일 경로를 고정
2. 기존 unit test 를 `apps/backend/tests/...` 체계로 옮길지 결정
3. multicam / FCPXML / reexport 테스트를 fixture 기반으로 추가
4. live smoke 와 contract test 를 분리
