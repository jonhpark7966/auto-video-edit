# Live Media Fixtures

큰 미디어 파일은 저장소 루트 `samples/` 에 둔다.
이 디렉터리는 사람이 직접 검증할 때 어떤 source 를 우선 볼지 안내하는 용도다.

현재 canonical live source:

- `samples/test_multisource/`: multicam + extra source + export 검증
- `samples/sample_10min.m4a`: podcast-cut 기본 live sample
- `samples/C1718_compressed.mp4`: subtitle-cut / two-pass 관련 live sample
- `apps/backend/manual-fixtures/historical/20260207_192336/source.mp4`: historical single-source sample

원칙:

- 작은 입력은 `apps/backend/manual-fixtures/text` 와 `apps/backend/manual-fixtures/snapshots` 를 우선 본다.
- 큰 미디어 검증은 `doctor` fast check 후에만 진행한다.
- 수동 검증 결과는 scratch output 디렉터리에 따로 저장하고 fixture 자체는 덮어쓰지 않는다.
