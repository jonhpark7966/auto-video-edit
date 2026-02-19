# avid 프롬프트 개선 루프

당신은 AI 영상 편집 시스템(avid)의 프롬프트를 반복적으로 개선하는 엔지니어입니다.

## 목표

사람이 만든 ground truth와 비교하여 **F1 score를 최대화**하세요.
F1 달성 목표: **≥ 0.99** (medium reasoning effort 기준)

## 대상 스킬

이 루프를 시작할 때 아래 환경변수를 설정하세요. `run_and_eval.sh`가 이 값을 사용합니다.

| 환경변수 | 설명 | 예시 |
|----------|------|------|
| `SKILL` | 개선할 스킬 | `subtitle-cut` 또는 `podcast-cut` |
| `SOURCE_DIR` | 평가 대상 프로젝트 경로 | `/tmp/eogum/a7445a5c-dca9-4c11-aa85-49652d314688` |
| `GROUND_TRUTH` | 사람 평가 JSON 경로 | `$SOURCE_DIR/output/eval_segments.json` |
| `SOURCE_CONTEXT` | Storyline 파일명 (없으면 빈 문자열) | `source.storyline.json` 또는 `""` |

**실행 예시:**
```bash
SKILL=podcast-cut \
SOURCE_DIR=/tmp/eogum/a7445a5c-dca9-4c11-aa85-49652d314688 \
GROUND_TRUTH=/tmp/eogum/a7445a5c-dca9-4c11-aa85-49652d314688/output/eval_segments.json \
SOURCE_CONTEXT="" \
./scripts/run_and_eval.sh "iter_$(date +%s)" medium
```

**스킬별 핵심 파일:**

### subtitle-cut

| 파일 | 경로 |
|------|------|
| **프롬프트 (수정 대상)** | `skills/subtitle-cut/codex_analyzer.py` |
| **CutReason enum** | `skills/subtitle-cut/models.py` |
| **reason 매핑** | `skills/subtitle-cut/main.py` → `reason_to_edit_reason` |
| **EditReason enum** | `apps/backend/src/avid/models/timeline.py` |

프롬프트: `CHUNK_ANALYSIS_PROMPT`, `ANALYSIS_PROMPT`, `DEDUP_VERIFICATION_PROMPT`

### podcast-cut

| 파일 | 경로 |
|------|------|
| **프롬프트 (수정 대상)** | `skills/podcast-cut/codex_analyzer.py` |
| **CutReason/KeepReason enum** | `skills/podcast-cut/models.py` |
| **reason 매핑** | `skills/podcast-cut/main.py` → `reason_to_edit_reason` |
| **EditReason enum** | `apps/backend/src/avid/models/timeline.py` |

프롬프트: `PODCAST_ANALYSIS_PROMPT`

### 공통 파일

| 파일 | 경로 |
|------|------|
| **Codex 호출 (effort 설정)** | `skills/_common/cli_utils.py` |
| **Chunk 병렬 처리** | `skills/_common/parallel.py` |
| **Context 유틸** | `skills/_common/context_utils.py` |
| **Eval 스크립트** | `scripts/eval_subtitle_cut.py` |
| **실행+평가 스크립트** | `scripts/run_and_eval.sh` |
| **Tracking 히스토리** | `scripts/eval_tracking.jsonl` |

> 모든 경로는 `/home/jonhpark/workspace/auto-video-edit/` 기준 상대경로입니다.

## 매 반복 절차

### Step 1: 이전 결과 확인

tracking 파일을 읽어서 이전 반복의 F1, 에러 수, 에러 분류를 확인하세요:

```bash
cat /home/jonhpark/workspace/auto-video-edit/scripts/eval_tracking.jsonl
```

가장 최근 eval_result.json에서 `disagreements`를 분석하세요. 특히:
- FP (AI가 잘못 자른 것): AI의 reason별 분류
- FN (AI가 놓친 것): 사람의 reason별 분류

첫 반복이라면 baseline을 먼저 측정하세요 (Step 3으로).

### Step 2: 에러 분석 & 프롬프트 수정

남은 에러를 분석하고 해당 스킬의 프롬프트를 수정하세요.

**수정 원칙:**
- ❌ 특정 영상에만 해당하는 구체적 예시를 넣지 마세요 (특정 인물명, 브랜드명, 주제 등)
- ✅ 일반적인 패턴과 규칙을 추가하세요
- ❌ 프롬프트를 너무 길게 만들지 마세요. 핵심만 명확하게.
- ✅ 같은 스킬 내 모든 프롬프트를 항상 동기화하세요
- ❌ 새 reason을 추가할 때 enum과 매핑을 같이 업데이트하는 것을 잊지 마세요
- ✅ 에러 패턴을 구조적으로 해결하세요 (개별 케이스가 아닌 패턴 단위)

**새 CutReason 추가 시 체크리스트:**
1. 해당 스킬의 `models.py` enum에 추가
2. `apps/backend/src/avid/models/timeline.py`의 EditReason enum에 추가
3. 해당 스킬의 `main.py`의 `reason_to_edit_reason` 매핑에 추가
4. 프롬프트의 reason 값 목록에 추가

**프롬프트 외 수정 가능 항목:**
- `codex_analyzer.py`의 CHUNK_SIZE, CHUNK_OVERLAP 조정
- 후처리 함수 로직 수정 (e.g. dedup verification, score threshold)

### Step 3: medium effort로 실행 & 평가

수정 후 **medium** effort로 실행하고 평가하세요:

```bash
/home/jonhpark/workspace/auto-video-edit/scripts/run_and_eval.sh "iter_$(date +%s)" medium
```

> eval 스크립트가 현재 스킬에 맞지 않으면 (예: podcast-cut용이 없으면) 먼저 eval 스크립트를 복제·수정하세요.
> `eval_subtitle_cut.py`를 참고하되, reason enum과 avid.json 구조 차이를 반영하세요.

결과를 확인하세요:
- 가장 최근 출력 디렉토리의 `eval_result.json`
- tracking 파일의 마지막 줄

### Step 4: reasoning effort 비교 실험

medium 실행 후 **같은 프롬프트**로 low와 high도 각각 실행하세요:

```bash
/home/jonhpark/workspace/auto-video-edit/scripts/run_and_eval.sh "iter_$(date +%s)_low" low
/home/jonhpark/workspace/auto-video-edit/scripts/run_and_eval.sh "iter_$(date +%s)_high" high
```

이 단계는 매 반복이 아니라 **프롬프트를 변경한 후에만** 실행하세요.

### Step 5: 결과 판단

**⚠️ LLM 분산 주의**: Codex(GPT-5.2) 출력은 비결정적입니다. 같은 프롬프트로도 F1이 ±8%p 변동합니다.
따라서 단일 실행 결과만으로 판단하지 말고, **tracking 히스토리 전체 추세**를 보세요.

결과에 따라:

**F1 ≥ 0.99 (medium)이면** → 목표 달성. 커밋하고 완료 선언.
```
<promise>EVAL COMPLETE</promise>
```

**이전 최고 F1 대비 개선됐으면** → 커밋하고 다음 반복 진행.
```bash
cd /home/jonhpark/workspace/auto-video-edit
git add -A && git commit -m "<skill>: improve prompt (F1: X.X% → Y.Y%)"
```

**이전 최고보다 낮지만 에러 패턴이 다르면** → 프롬프트 변경 때문인지 LLM 분산인지 판단:
- 새로운 FP/FN 유형이 등장했다면 → 프롬프트 변경이 원인. 되돌리기.
- 같은 유형의 에러 수만 다르면 → LLM 분산일 수 있음. 한번 더 실행해서 확인.

**명확히 악화됐으면** → 변경 되돌리고 다른 접근 시도.
```bash
cd /home/jonhpark/workspace/auto-video-edit
git checkout -- skills/<skill>/codex_analyzer.py
```

**3번 연속 새로운 개선 아이디어가 없으면** → plateau 도달. 아래 최종 보고서를 작성하고 완료.
```
<promise>EVAL COMPLETE</promise>
```

## 최종 보고서 (완료 시 반드시 출력)

루프 종료 시 다음 형식으로 보고하세요:

```
## Eval Improvement Report

### 대상
- 스킬: <skill>
- 프로젝트: <project_dir>

### 메트릭 변화
| 버전 | F1 | Accuracy | Precision | Recall | Errors | FP | FN | Effort | Time |
|------|-----|----------|-----------|--------|--------|----|----|--------|------|
(tracking에서 추출)

### Reasoning Effort 비교
| Effort | F1 (avg) | Time (avg) | 비고 |
|--------|----------|------------|------|
| low    |          |            |      |
| medium |          |            |      |
| high   |          |            |      |

### 남은 에러 분석
(해결 불가능한 에러와 그 이유)

### 프롬프트 변경 이력
(각 반복에서 무엇을 바꿨고 어떤 효과가 있었는지)
```

## 평가 기준 (변경 금지)

- **Cut = positive class** (AI가 자르기로 결정)
- **Keep = negative class** (AI가 유지하기로 결정)
- **TP**: AI=cut, Human=cut (올바른 절삭)
- **TN**: AI=keep, Human=keep (올바른 유지)
- **FP**: AI=cut, Human=keep (잘못된 절삭 — precision 하락)
- **FN**: AI=keep, Human=cut (놓친 절삭 — recall 하락)
- Human이 리뷰하지 않은 세그먼트 = AI 결정에 암묵적 동의
- **F1 = 2 * precision * recall / (precision + recall)**

## 이전 루프에서 배운 교훈 (subtitle-cut)

아래는 subtitle-cut 루프(V1→V7, F1: 73.4%→91.1%)에서 얻은 범용 교훈입니다.

### 효과적이었던 접근

1. **FP 먼저 해결**: FP는 precision을 직접 떨어뜨림. "~이 아닌 것" 규칙을 명시적으로 추가하면 효과적.
2. **Two-pass 아키텍처**: 1차 분석 후 keep 세그먼트 대상 2차 검증(dedup verification)으로 FN 감소.
3. **판정 기준 강화**: 모호한 reason(e.g. fumble)의 기준을 "인접 자기교정 필수" 같이 구체화하면 FP 감소.
4. **패턴 기반 규칙**: 특정 케이스 대신 구조적 패턴("trailing connective fragment", "나열형 설명") 추가.

### 역효과가 나타난 접근

1. **강조 어조**: "반드시 찾으세요", "⚠️ 주의" 같은 강조 표현 → AI가 과도하게 보수적 → recall 하락.
2. **Chunk 크기 축소**: context 부족으로 retake/duplicate 감지력 하락. 기본 크기 유지 권장.
3. **High reasoning effort**: 과도한 추론으로 FP 증가. medium이 안정적, low가 가장 빠르고 때때로 최고 성능.
4. **Overlap 증가**: chunk overlap을 늘려도 성능 개선 없음. 오히려 악화.

### 프롬프트 엔지니어링 일반 원칙

- **규칙은 선언적으로**: "X이면 cut" 형태로 명확하게. 감정적·강조적 표현 지양.
- **반례 명시**: "중복으로 보이지만 자르면 안 되는 것"을 명시하면 FP 급감.
- **작은 변경, 빠른 검증**: 한 번에 하나의 패턴만 수정하고 바로 평가.
- **LLM 분산 고려**: 동일 프롬프트로 ±8%p 변동. 2회 이상 실행으로 추세 확인.
- **Plateau 인식**: 프롬프트 튜닝만으로 해결 불가한 에러(의미적 유사도, 도메인 지식)가 있음. 이를 인식하고 아키텍처 변경으로 넘어갈 것.

## 중요 제약

1. **avid는 Codex CLI (GPT-5.2)를 subprocess로 호출합니다.** 직접 API 호출이 아닙니다.
2. **Chunk 처리**: 세그먼트 수 > 임계값이면 chunk로 나눠서 병렬 처리. chunk 경계에서 비교 불가 한계 있음.
3. **Reasoning effort**: `CODEX_REASONING_EFFORT` 환경변수로 low/medium/high 제어. **medium 기본 사용**.
4. **일반화**: 특정 영상에만 맞추면 다른 영상에서 성능 하락. 항상 일반 원칙으로 작성.
5. **Eval 스크립트 적합성**: 스킬에 맞는 eval 스크립트가 있는지 먼저 확인. 없으면 `eval_subtitle_cut.py`를 참고하여 생성.
