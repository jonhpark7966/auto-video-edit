# AVID Backend

`apps/backend` 는 `avid` 패키지와 `avid-cli` 의 실제 소스 루트다.
외부 오케스트레이터는 이 디렉터리의 Python 내부 구조를 import 하지 말고, 설치된 `avid-cli` 만 사용해야 한다.

## 문서 우선순위

- [CLI_INTERFACE.md](CLI_INTERFACE.md): 외부 통합에서 기대해도 되는 CLI 표면과 JSON/manifest 규칙
- [REEXPORT_SPLIT_PLAN.md](REEXPORT_SPLIT_PLAN.md): `reexport` 분해 계획, deprecated 전략, eogum 마이그레이션 순서
- [TEST_API_SPECS.md](TEST_API_SPECS.md): CLI/HTTP 수동 검증 대상 스펙, 준비물, dependency 목록
- [PROVIDER_RUNTIME_SPEC.md](PROVIDER_RUNTIME_SPEC.md): Claude/Codex model/effort 설정 표면, 기본 프로필, smoke/test 계획
- [TEST_DATA_GUIDE.md](TEST_DATA_GUIDE.md): 수동 검증용 fixture 분류, canonical source, 리뷰 순서
- [TESTING.md](TESTING.md): 어떤 순서로 직접 검증할지, 명령별 기대 결과가 무엇인지
- [../../SPEC.md](../../SPEC.md): 제품/도메인 수준 스펙
- [../../ARCHITECTURE.md](../../ARCHITECTURE.md): 서비스 계층과 데이터 흐름

## 빠른 체크

```bash
cd apps/backend
pip install -e '.[sync]'
avid-cli version --json
avid-cli doctor --json
avid-cli doctor --probe-providers --json
```

권장 workflow 검증 시작점:

1. `doctor`
2. `transcribe`
3. `transcript-overview`
4. `subtitle-cut` 또는 `podcast-cut`
5. `review-segments`
6. `apply-evaluation`
7. `rebuild-multicam`
8. `export-project`

즉, `reexport` 나 split command 부터 보지 말고 source input 부터 final export 까지 따라가는 것이 맞다.

## 외부 통합 원칙

- 외부 호출자는 `avid-cli` 를 실행한다.
- machine-readable 결과가 필요하면 `--json` 또는 `--manifest-out` 을 사용한다.
- `src/avid/*` 내부 모듈 경로는 public API가 아니다.
- `eogum` 같은 상위 시스템과 맞물리는 표면은 [CLI_INTERFACE.md](CLI_INTERFACE.md)를 source of truth 로 본다.

## 현재 우선순위

1. CLI 표면 고정
2. 실제 workflow 기준 수동 검증 시나리오 정리
3. live dependency 를 분리한 smoke 절차 확립
4. 그 다음 상위 시스템 통합
