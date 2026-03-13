# Reexport Split Plan

> 상태: 제안 단계
> 구현: 아직 하지 않음

## 1. 왜 쪼개는가

현재 `reexport` 는 아래 세 가지 책임을 한 명령에 묶고 있다.

- evaluation override 적용
- multicam / extra source 재구성
- FCPXML / adjusted SRT export

이 구조는 이름과 실제 동작이 어긋나고, 테스트도 한 번에 너무 많은 조건을 요구한다.
그래서 다음 단계에서는 기능을 아래 세 명령으로 분리한다.
추가로, extra source 를 제거만 하는 경우는 명시적 명령으로 분리한다.

## 2. 새 명령 제안

### 2.1 `apply-evaluation`

목적:
- 기존 project JSON 에 human evaluation override 만 적용한다.

입력:
- `--project-json <path>`
- `--evaluation <path>`
- `--output-project-json <path>`

출력:
- `artifacts.project_json`
- `stats.applied_evaluation_segments`
- `stats.applied_changes`

규칙:
- media source 는 필요 없다
- FCPXML / SRT export 를 하지 않는다
- `human.action=cut` 은 manual cut 추가
- `human.action=keep` 은 overlapping AI cut 제거

### 2.2 `rebuild-multicam`

목적:
- 기존 project JSON 의 extra source 를 교체하고 offset 을 다시 계산한다.

입력:
- `--project-json <path>`
- `--source <path>`
- `--extra-source <path>` repeatable
- `--offset <ms>` repeatable
- `--output-project-json <path>`

출력:
- `artifacts.project_json`
- `stats.extra_sources`
- `stats.stripped_extra_sources`

규칙:
- evaluation 적용을 하지 않는다
- export 를 하지 않는다
- implicit strip-only 동작은 피한다
- 최소 한 개 이상의 `--extra-source` 가 있어야 한다
- manual offset 은 public 표면으로 노출한다
- strip-only 는 `clear-extra-sources` 로만 처리한다

### 2.3 `clear-extra-sources`

목적:
- 기존 project JSON 에서 extra source 를 명시적으로 제거한다.

입력:
- `--project-json <path>`
- `--output-project-json <path>`

출력:
- `artifacts.project_json`
- `stats.stripped_extra_sources`

규칙:
- extra source 제거만 수행한다
- evaluation 적용을 하지 않는다
- export 를 하지 않는다
- implicit strip-only 대신 이 명령을 사용한다

### 2.4 `export-project`

목적:
- 이미 준비된 project JSON 을 FCPXML / adjusted SRT 로 export 한다.

입력:
- `--project-json <path>`
- `--output-dir <path>`
- 선택: `-o/--output <path>`
- 선택: `--silence-mode <cut|disabled>`
- 선택: `--content-mode <cut|disabled>`

출력:
- `artifacts.fcpxml`
- `artifacts.srt` if transcription exists

규칙:
- project JSON 을 수정하지 않는다
- evaluation 이나 multicam sync 를 하지 않는다
- report 는 생성하지 않는다

## 3. `reexport` 의 향후 위치

`reexport` 는 바로 제거하지 않는다.

역할:
- deprecated compatibility wrapper
- 기존 외부 호출자와 `eogum` 을 즉시 깨지 않게 유지

내부 동작 목표:
1. `apply-evaluation` 필요 시 호출
2. `rebuild-multicam` 필요 시 호출
3. `clear-extra-sources` 필요 시 호출
4. `export-project` 호출

추가 규칙:
- stderr 에 deprecated warning 출력
- 문서에서는 새 통합에 권장하지 않음
- parity test 는 유지

## 4. 테스트 순서 제안

### Phase 1: `apply-evaluation`

- 구현 완료
- unit test 추가 완료
- overlap 제거 / manual cut 추가 / keep semantics 고정
- media fixture 없이 빠르게 검증

### Phase 2: `export-project`

- 구현 완료
- unit test 추가 완료
- FCPXML / adjusted SRT artifact contract 고정
- `content-mode`, `silence-mode` matrix 확인

### Phase 3: `rebuild-multicam`

- 구현 완료
- unit test 추가 완료
- real sample manual-offset smoke 확인 완료
- auto sync / manual offset / strip-and-replace 정책 확인

### Phase 4: `clear-extra-sources`

- 구현 완료
- unit test 추가 완료
- real sample strip-only smoke 확인 완료
- explicit clear path 가 strip-only 역할을 대신하는지 확인

### Phase 5: deprecated `reexport`

- 구현 완료
- warning + parity unit test 추가 완료
- real sample deprecated smoke 확인 완료
- backward compatibility 만 검증

## 5. `eogum` 마이그레이션 계획

현재 `eogum` 은 `avid.reexport(...)` 를 한 번 호출한다.
다음 단계에서는 이 호출을 아래 순서로 치환한다.

1. `apply-evaluation` if evaluation exists
2. `rebuild-multicam` if extra sources exist
3. `clear-extra-sources` if explicit clear is requested
4. `export-project`

추가 TODO:
- `/projects/{id}/multicam` 이름은 의미가 넓으므로 나중에 endpoint 의미를 다시 정리
- preview / report 재생성 정책도 별도로 결정
- manual offset 은 `eogum` request/API 에 노출하는 방향으로 간다
- 중간 project JSON 은 새 경로를 만들지 않고 기존 `settings.avid_temp_dir` 아래 worker temp dir에서 단계별 파일로 둔다
  - 현재 기준 temp root: `/tmp/eogum`
  - 일반 작업: `/tmp/eogum/{project_id}`
  - 재처리 작업: `/tmp/eogum/multicam_{project_id}`
  - split 이후 권장 파일 예시:
    - `input.project.avid.json`
    - `01_eval_applied.project.avid.json`
    - `02_multicam.project.avid.json`
    - `output/`

## 6. 구현 전에 확인할 결정사항

- deprecated `reexport` warning 문구 형식
