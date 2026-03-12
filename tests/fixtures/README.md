# Test Fixtures

이 디렉터리는 `auto-video-edit` 테스트에서 canonical fixture 로 사용할 작은 입력과 snapshot 을 모아두는 위치다.

- `text/`: 작은 SRT/JSON 입력
- `snapshots/`: expected output 비교용 snapshot
- `live/`: 큰 미디어 fixture 의 현재 authoritative 위치 설명

큰 미디어 파일은 당분간 `samples/` 에서 관리하고, 이 디렉터리에는 설명 문서만 둔다.
상세 기준은 [apps/backend/TEST_DATA_GUIDE.md](../../apps/backend/TEST_DATA_GUIDE.md)를 본다.
