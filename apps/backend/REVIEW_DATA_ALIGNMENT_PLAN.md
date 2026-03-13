# Review Data Alignment Plan

> 상태: 구현 전
> 목표: `eogum` review 데이터와 `avid-cli` 입력/출력 스키마를 같은 엔진 표면으로 정렬

## 1. 배경

현재 구조는 아래처럼 어긋난다.

- `avid` content decision 은 transcript segment 기준으로 생성된다.
- `avid` 전체 `edit_decisions` 에는 silence gap decision 도 섞인다.
- `eogum` review API 는 `edit_decisions` 를 직접 노출하지 않고 transcript segment 에 AI decision 을 overlap 으로 얹는다.
- 저장된 evaluation 은 그 overlap 결과를 그대로 다시 `apply-evaluation` 에 넘긴다.
- 현재 `apply-evaluation` 도 overlap 기반으로 patch 한다.

이 구조에서는 다음이 깨지기 쉽다.

- 사람 review row 와 AI content decision 의 정확한 1:1 대응
- 다른 UI 가 `avid-cli` 를 직접 엔진으로 사용할 때의 호환성
- legacy sample 이 아닌 새 영상으로 검증할 때의 재현성

## 2. 이번 작업의 고정 원칙

1. review 의 기준 단위는 `transcription segment index` 다.
2. `avid` 가 reviewable content decision 에 `source_segment_index` 를 명시적으로 보존한다.
3. `silence` 는 review 대상 content segment 와 다른 종류의 decision 으로 분리한다.
4. `avid-cli` 가 review payload 를 직접 생성한다.
5. `eogum` 은 그 payload 를 저장/전달하는 소비자여야 한다.
6. `eogum` 이 저장한 review JSON 은 `avid-cli apply-evaluation` 에 그대로 들어가야 한다.
7. 다른 UI 도 같은 JSON 을 이용해 `avid-cli` 를 바로 사용할 수 있어야 한다.

## 3. 목표 상태

### 3.1 `avid` project JSON

`TranscriptSegment`

- `index`
- `start_ms`
- `end_ms`
- `text`
- `confidence`
- `speaker`

`EditDecision`

- `range`
- `edit_type`
- `reason`
- `confidence`
- `note`
- `active_video_track_id`
- `active_audio_track_ids`
- `speed_factor`
- `origin_kind`
- `source_segment_index`

`origin_kind` 값:

- `content_segment`
- `silence_gap`
- `manual_override`

규칙:

- content decision 은 `source_segment_index` 를 반드시 가진다.
- silence decision 은 `source_segment_index = null` 이다.
- manual override 는 기본적으로 target segment 의 `source_segment_index` 를 가진다.

### 3.2 `avid-cli review-segments`

엔진이 review payload 를 직접 만든다.

예상 출력 shape:

```json
{
  "schema_version": "review-segments/v1",
  "project_json": "/abs/path/input.avid.json",
  "segments": [
    {
      "index": 12,
      "start_ms": 32199,
      "end_ms": 36959,
      "text": "....",
      "ai": {
        "action": "cut",
        "reason": "dragging",
        "confidence": 0.9,
        "note": "...",
        "source_segment_index": 12,
        "origin_kind": "content_segment"
      },
      "human": null
    }
  ]
}
```

### 3.3 `avid-cli apply-evaluation`

새 기본 규칙:

- `EvalSegment.index` 기준으로 patch
- `keep`:
  - 같은 `source_segment_index` 를 가진 content/manual decision 만 제거
- `cut`:
  - 같은 segment range 로 manual override decision upsert
- `silence_gap` decision 은 유지

legacy 규칙:

- `source_segment_index` 가 전혀 없는 old project / old evaluation 에 대해서만 overlap fallback 허용
- fallback 사용 시 deprecated warning 출력

## 4. 커밋 단위 체크리스트

### Commit 1. avid 모델에 segment identity 추가

목적:

- project JSON 안에서 reviewable content decision 의 identity 를 잃지 않게 한다.

수정 파일:

- `/home/jonhpark/workspace/auto-video-edit/apps/backend/src/avid/models/project.py`
- `/home/jonhpark/workspace/auto-video-edit/apps/backend/src/avid/models/timeline.py`
- `/home/jonhpark/workspace/auto-video-edit/skills/podcast-cut/main.py`
- `/home/jonhpark/workspace/auto-video-edit/skills/subtitle-cut/main.py`
- `/home/jonhpark/workspace/auto-video-edit/apps/backend/src/avid/services/podcast_cut.py`
- `/home/jonhpark/workspace/auto-video-edit/apps/backend/src/avid/services/subtitle_cut.py`
- `/home/jonhpark/workspace/auto-video-edit/apps/backend/src/avid/export/fcpxml.py`

할 일:

- [x] `TranscriptSegment.index` 추가
- [x] `EditDecision.origin_kind` 추가
- [x] `EditDecision.source_segment_index` 추가
- [x] content decision 생성 시 `source_segment_index` 채우기
- [x] silence decision 생성 시 `origin_kind="silence_gap"` 채우기
- [x] export/merge 시 새 필드 보존

완료 기준:

- 새 영상으로 생성한 `.avid.json` 에서 content decision 이 segment index 를 가진다.
- silence decision 은 명확히 구분된다.

### Commit 2. avid-cli review payload 명세와 명령 추가

목적:

- UI 가 직접 조합하지 않아도 되는 engine-native review payload 를 만든다.

수정 파일:

- `/home/jonhpark/workspace/auto-video-edit/apps/backend/src/avid/cli.py`
- `/home/jonhpark/workspace/auto-video-edit/apps/backend/CLI_INTERFACE.md`
- `/home/jonhpark/workspace/auto-video-edit/apps/backend/TEST_API_SPECS.md`
- `/home/jonhpark/workspace/auto-video-edit/apps/backend/TESTING.md`
- `/home/jonhpark/workspace/auto-video-edit/ARCHITECTURE.md`
- `/home/jonhpark/workspace/auto-video-edit/SPEC.md`

할 일:

- [x] `avid-cli review-segments --project-json ... --json` 추가
- [x] review payload `schema_version` 추가
- [x] content decision 은 `source_segment_index` 로만 join
- [x] silence decision 은 review payload 에 기본 제외
- [x] 문서에 engine-native review payload 명세 추가

완료 기준:

- `review-segments` 결과만으로 다른 UI 가 review 화면을 만들 수 있다.

### Commit 3. apply-evaluation 를 index 기반 patch 로 교체

목적:

- 저장된 review JSON 이 정확한 segment identity 로 다시 적용되게 만든다.

수정 파일:

- `/home/jonhpark/workspace/auto-video-edit/apps/backend/src/avid/cli.py`
- `/home/jonhpark/workspace/auto-video-edit/apps/backend/CLI_INTERFACE.md`
- `/home/jonhpark/workspace/auto-video-edit/apps/backend/TEST_API_SPECS.md`
- `/home/jonhpark/workspace/auto-video-edit/apps/backend/TESTING.md`
- `/home/jonhpark/workspace/auto-video-edit/apps/backend/REEXPORT_SPLIT_PLAN.md`

할 일:

- [ ] `apply-evaluation` 기본 경로를 `segment index` patch 로 변경
- [ ] `keep` 는 동일 segment content/manual decision 만 제거
- [ ] `cut` 은 동일 segment range 에 manual override upsert
- [ ] silence decision 보호
- [ ] legacy overlap fallback 추가
- [ ] fallback 사용 시 deprecated warning 추가

완료 기준:

- `review-segments` 로 받은 JSON 을 수정 후 바로 `apply-evaluation` 에 넣어도 의도대로 반영된다.

### Commit 4. eogum API 를 engine-native review payload 소비자로 변경

목적:

- `eogum` 의 독자적인 overlap merge 를 제거한다.

수정 파일:

- `/home/jonhpark/workspace/eogum/apps/api/src/eogum/services/avid.py`
- `/home/jonhpark/workspace/eogum/apps/api/src/eogum/models/schemas.py`
- `/home/jonhpark/workspace/eogum/apps/api/src/eogum/routes/evaluations.py`
- `/home/jonhpark/workspace/eogum/apps/api/src/eogum/routes/projects.py`
- `/home/jonhpark/workspace/eogum/docs/avid-cli-spec.md`
- `/home/jonhpark/workspace/eogum/ARCHITECTURE.md`

할 일:

- [ ] `avid.review_segments()` wrapper 추가
- [ ] `/projects/{id}/segments` 를 `review-segments` 결과 기반으로 변경
- [ ] 저장 스키마에 `schema_version`, `origin_kind`, `source_segment_index` 반영
- [ ] 재처리 시 evaluation JSON 을 그대로 `apply-evaluation` 에 전달
- [ ] 기존 overlap merge 제거

완료 기준:

- `eogum` 이 저장한 evaluation JSON 을 그대로 `avid-cli apply-evaluation` 에 넣어도 동작한다.

### Commit 5. eogum frontend 와 문서 정리

목적:

- review UI 와 문서가 새 엔진 표면을 그대로 따르게 만든다.

수정 파일:

- `/home/jonhpark/workspace/eogum/apps/web/src/lib/api.ts`
- `/home/jonhpark/workspace/eogum/apps/web/src/app/projects/[id]/review/page.tsx`
- `/home/jonhpark/workspace/eogum/TODO.md`
- `/home/jonhpark/workspace/eogum/docs/backend-refactoring-roadmap.md`
- `/home/jonhpark/workspace/eogum/docs/backend-testing-strategy.md`

할 일:

- [ ] review API 타입을 engine-native payload 에 맞춤
- [ ] cut/keep reason 목록을 avid enum 과 맞춤
- [ ] 저장/불러오기 흐름이 `review-segments` payload 를 그대로 유지하게 정리
- [ ] TODO / roadmap / testing strategy 갱신

완료 기준:

- `eogum` review UI 가 엔진 표면을 변환 없이 소비한다.

### Commit 6. 새 영상 기준 수동 검증 문서 갱신

목적:

- 개발 중 쓰던 샘플이 아니라 새 입력으로 workflow 를 다시 검증한다.

수정 파일:

- `/home/jonhpark/workspace/auto-video-edit/apps/backend/TESTING.md`
- `/home/jonhpark/workspace/auto-video-edit/apps/backend/TEST_API_SPECS.md`
- `/home/jonhpark/workspace/auto-video-edit/apps/backend/TEST_DATA_GUIDE.md`
- `/home/jonhpark/workspace/auto-video-edit/apps/backend/WORK_IN_PROGRESS.md`

할 일:

- [ ] 새 입력 소스로 전체 workflow 재실행
- [ ] `review-segments` 출력 확인
- [ ] `eogum` 저장 payload round-trip 확인
- [ ] `apply-evaluation` 반영 결과 확인
- [ ] multicam / export 재검증

완료 기준:

- 새 입력 데이터로도 workflow 와 review round-trip 이 유지된다.

## 5. 구현 순서

1. Commit 1
2. Commit 2
3. Commit 3
4. Commit 4
5. Commit 5
6. Commit 6

## 6. 구현 중 유지할 규칙

- 각 단계는 별도 commit 으로 끝낸다.
- 각 단계가 끝날 때 문서와 WIP 를 즉시 갱신한다.
- `eogum` 은 `avid-cli` 입력 shape 를 재해석하지 않는다.
- 다른 UI 도 같은 payload 로 `avid-cli` 를 사용할 수 있어야 한다.
