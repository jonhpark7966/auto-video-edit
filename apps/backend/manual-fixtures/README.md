# Manual Fixtures

이 디렉터리는 `avid-cli` 를 사람이 직접 검증할 때 쓰는 canonical 입력과 historical snapshot 을 모아둔 위치다.

- `text/`: 작은 SRT/JSON 입력
- `snapshots/`: 비교용 산출물 snapshot
- `historical/`: 실제 실행에서 수집한 sample 세트
- `live/`: 큰 미디어 source 위치 안내

기본 workflow fixture 는 아래 순서로 본다.

1. `samples/test_multisource/main_live.mp4`
2. `samples/test_multisource/main_live.srt`
3. `samples/test_multisource/main_live.storyline.json`
4. `samples/test_multisource/main_live.podcast.avid.json`
5. runtime 에서 생성한 `04_review/main_live.review.json`
6. 사람이 `human` 필드를 채운 `04_review/main_live.eval.json`
7. `samples/test_multisource/cam_sony.mp4`
8. 최종 export 결과

원칙:

- 자동화된 테스트 스위트는 유지하지 않는다.
- 검증은 [TESTING.md](../TESTING.md) 의 수동 시나리오 순서대로 수행한다.
- 새 fixture 는 scratch output 이 아니라 재현 가능한 입력과 기대 산출물만 올린다.
- `human eval` 예시는 고정 JSON 보다 `review-segments` 출력에서 생성한 payload 를 우선 사용한다.
