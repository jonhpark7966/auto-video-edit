# AVID Backend

`apps/backend` 는 `avid` 패키지와 `avid-cli` 의 실제 소스 루트다.
외부 오케스트레이터는 이 디렉터리의 Python 내부 구조를 import 하지 말고, 설치된 `avid-cli` 만 사용해야 한다.

## 문서 우선순위

- [CLI_INTERFACE.md](CLI_INTERFACE.md): 외부 통합에서 기대해도 되는 CLI 표면과 JSON/manifest 규칙
- [REEXPORT_SPLIT_PLAN.md](REEXPORT_SPLIT_PLAN.md): `reexport` 분해 계획, deprecated 전략, eogum 마이그레이션 순서
- [TEST_API_SPECS.md](TEST_API_SPECS.md): CLI/HTTP 테스트 대상 스펙, 준비물, dependency 목록
- [PROVIDER_RUNTIME_SPEC.md](PROVIDER_RUNTIME_SPEC.md): Claude/Codex model/effort 설정 표면, 기본 프로필, smoke/test 계획
- [TEST_DATA_GUIDE.md](TEST_DATA_GUIDE.md): 현재 테스트 데이터 분류, canonical fixture 기준, 리뷰 순서
- [TESTING.md](TESTING.md): 어떤 테스트를 어떤 순서로 만들고 어떻게 실행할지
- [../../SPEC.md](../../SPEC.md): 제품/도메인 수준 스펙
- [../../ARCHITECTURE.md](../../ARCHITECTURE.md): 서비스 계층과 데이터 흐름

## 빠른 체크

```bash
cd apps/backend
pip install -e '.[dev,sync]'
avid-cli version --json
avid-cli doctor --json
avid-cli doctor --probe-providers --json
avid-cli doctor --provider claude --probe-providers --provider-model claude-opus-4-6 --provider-effort medium --json
avid-cli apply-evaluation --project-json /tmp/in.avid.json --evaluation /tmp/evaluation.json --output-project-json /tmp/out.avid.json --json
```

## 외부 통합 원칙

- 외부 호출자는 `avid-cli` 를 실행한다.
- machine-readable 결과가 필요하면 `--json` 또는 `--manifest-out` 을 사용한다.
- `src/avid/*` 내부 모듈 경로는 public API가 아니다.
- `eogum` 같은 상위 시스템과 맞물리는 표면은 [CLI_INTERFACE.md](CLI_INTERFACE.md)를 source of truth 로 본다.

## 현재 우선순위

1. CLI 표면 고정
2. CLI 테스트 추가
3. live dependency 를 분리한 smoke test 확립
4. 그 다음 상위 시스템 통합
