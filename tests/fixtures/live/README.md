# Live Media Fixtures

큰 미디어 파일은 아직 이 디렉터리로 옮기지 않았다.
현재 canonical live fixture 는 아래를 본다.

- `samples/test_multisource/`: multicam + extra source + export 검증
- `samples/sample_10min.m4a`: podcast-cut 기본 live sample
- `samples/C1718_compressed.mp4`: subtitle-cut / two-pass 관련 live sample
- `tests/e2e/data/20260207_192336/source.mp4`: historical e2e snapshot input

원칙:
- unit/integration 테스트는 되도록 `tests/fixtures/text` 와 `tests/fixtures/snapshots` 를 우선 사용
- live smoke 에서만 큰 미디어 fixture 를 직접 사용
