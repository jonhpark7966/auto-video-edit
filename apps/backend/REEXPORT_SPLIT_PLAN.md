# Reexport Split Plan

> 상태: 구현 완료, 문서 정리 단계
> 위치: split command 는 존재하고 `reexport` 는 deprecated compatibility wrapper 로 남아 있다.

## 0. 이 문서의 위치

이 문서는 **주 workflow 문서가 아니다**.

주 workflow 는 아래다.

1. `transcribe`
2. `transcript-overview`
3. `subtitle-cut` 또는 `podcast-cut`
4. `apply-evaluation`
5. `rebuild-multicam`
6. `export-project`

즉 이 문서는 초기 cut 이후의 refinement / compatibility 명령을 설명하는 보조 문서다.

## 1. 왜 쪼갰는가

원래 `reexport` 는 아래 세 가지 책임을 한 명령에 묶고 있었다.

- evaluation override 적용
- multicam / extra source 재구성
- FCPXML / adjusted SRT export

이 구조는 이름과 실제 동작이 어긋났고, 주 workflow 검증도 흐리게 만들었다.
그래서 refinement 단계와 export 단계를 명시적으로 분리했다.

## 2. 현재 split command

### 2.1 `apply-evaluation`

목적:
- 기존 project JSON 에 human evaluation override 만 적용

입력:
- `--project-json`
- `--evaluation`
- `--output-project-json`

출력:
- `artifacts.project_json`
- `stats.applied_evaluation_segments`
- `stats.applied_changes`
- `stats.join_strategy`

규칙:

- 기본 patch 기준은 `segment index`
- `review-segments/v1` payload 를 그대로 받아야 한다
- old project / old evaluation 에 대해서만 `legacy_overlap` fallback 을 허용한다

### 2.2 `rebuild-multicam`

목적:
- 기존 project JSON 에 extra source 를 붙이고 offset 을 반영

입력:
- `--project-json`
- `--source`
- `--extra-source` repeated
- `--offset` repeated
- `--output-project-json`

출력:
- `artifacts.project_json`
- `stats.extra_sources`
- `stats.stripped_extra_sources`

### 2.3 `clear-extra-sources`

목적:
- 기존 project JSON 에서 extra source 를 명시적으로 제거

입력:
- `--project-json`
- `--output-project-json`

출력:
- `artifacts.project_json`
- `stats.stripped_extra_sources`

### 2.4 `export-project`

목적:
- 준비된 project JSON 을 FCPXML / adjusted SRT 로 export

입력:
- `--project-json`
- `--output-dir`
- 선택: `--output`
- 선택: `--silence-mode`
- 선택: `--content-mode`

출력:
- `artifacts.fcpxml`
- `artifacts.srt` if transcription exists

규칙:
- project JSON 을 수정하지 않는다
- report 는 생성하지 않는다

## 3. `reexport` 의 현재 위치

`reexport` 는 바로 제거하지 않는다.

역할:

- deprecated compatibility wrapper
- 기존 외부 호출자를 즉시 깨지 않게 유지

내부 동작:

1. 필요 시 `apply-evaluation`
2. 필요 시 `rebuild-multicam`
3. 필요 시 `clear-extra-sources`
4. 마지막 `export-project`

추가 규칙:

- stderr 에 deprecated warning 출력
- 새 workflow 검증은 이 명령으로 시작하지 않는다
- 주 용도는 backward compatibility 확인이다

## 4. 검증 위치

주 workflow 에서 각 명령의 위치는 아래다.

- `apply-evaluation`: initial cut 다음
- `rebuild-multicam`: human eval 다음
- `clear-extra-sources`: maintenance path
- `export-project`: 마지막 최종 export
- `reexport`: compatibility only

## 5. `eogum` 쪽 의미

`eogum` 입장에서도 재처리는 아래처럼 이해하는 것이 맞다.

1. 초기 create job 에서 `transcribe -> transcript-overview -> subtitle-cut/podcast-cut`
2. 사람 검토 후 `apply-evaluation`
3. 필요 시 `rebuild-multicam`
4. 필요 시 `clear-extra-sources`
5. 마지막 `export-project`

즉 `reexport` 는 더 이상 개념적 주 경로가 아니다.
