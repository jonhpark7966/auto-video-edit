# subtitle-cut 프롬프트 개선 루프

당신은 AI 영상 편집 시스템(avid subtitle-cut)의 프롬프트를 반복적으로 개선하는 엔지니어입니다.

## 목표

사람이 만든 ground truth와 비교하여 **F1 score를 최대화**하세요.
F1 달성 목표: **≥ 0.99** (medium reasoning effort 기준)

## 파일 위치

| 파일 | 경로 |
|------|------|
| **프롬프트 (수정 대상)** | `/home/jonhpark/workspace/auto-video-edit/skills/subtitle-cut/codex_analyzer.py` |
| **CutReason enum** | `/home/jonhpark/workspace/auto-video-edit/skills/subtitle-cut/models.py` |
| **EditReason enum** | `/home/jonhpark/workspace/auto-video-edit/apps/backend/src/avid/models/timeline.py` |
| **reason 매핑** | `/home/jonhpark/workspace/auto-video-edit/skills/subtitle-cut/main.py` (reason_to_edit_reason) |
| **Codex 호출 (effort 설정)** | `/home/jonhpark/workspace/auto-video-edit/skills/_common/cli_utils.py` |
| **Ground truth** | `/tmp/eogum/eval_segments.json` |
| **Source video** | `/tmp/eogum/22200e46/source.mp4` |
| **Source SRT** | `/tmp/eogum/22200e46/source.srt` |
| **Storyline context** | `/tmp/eogum/22200e46/source.storyline.json` |
| **Eval 스크립트** | `/home/jonhpark/workspace/auto-video-edit/scripts/eval_subtitle_cut.py` |
| **실행+평가 스크립트** | `/home/jonhpark/workspace/auto-video-edit/scripts/run_and_eval.sh` |
| **Tracking 히스토리** | `/home/jonhpark/workspace/auto-video-edit/scripts/eval_tracking.jsonl` |

## 매 반복 절차

### Step 1: 이전 결과 확인

tracking 파일을 읽어서 이전 반복의 F1, 에러 수, 에러 분류를 확인하세요:

```bash
cat /home/jonhpark/workspace/auto-video-edit/scripts/eval_tracking.jsonl
```

가장 최근 eval_result.json에서 `disagreements`를 분석하세요. 특히:
- FP (AI가 잘못 자른 것): AI의 reason별 분류
- FN (AI가 놓친 것): 사람의 reason별 분류

### Step 2: 에러 분석 & 프롬프트 수정

남은 에러를 분석하고 `codex_analyzer.py`의 CHUNK_ANALYSIS_PROMPT와 ANALYSIS_PROMPT를 수정하세요.

**수정 원칙:**
- ❌ 이 영상에만 해당하는 구체적 예시를 넣지 마세요 (예: "피지컬 AI", "테슬라 FSD" 같은 특정 내용)
- ✅ 일반적인 패턴과 규칙을 추가하세요 (예: "나열형 설명은 중복이 아닙니다")
- ❌ 프롬프트를 너무 길게 만들지 마세요. 핵심만 명확하게.
- ✅ 두 프롬프트(CHUNK_ANALYSIS_PROMPT, ANALYSIS_PROMPT)를 항상 동기화하세요
- ❌ 새 reason을 추가할 때 enum과 매핑을 같이 업데이트하는 것을 잊지 마세요
- ✅ 에러 패턴을 구조적으로 해결하세요 (chunk 경계 문제 → chunk 크기/overlap 조정 등)

**새 CutReason 추가 시 체크리스트:**
1. `skills/subtitle-cut/models.py`의 CutReason enum에 추가
2. `apps/backend/src/avid/models/timeline.py`의 EditReason enum에 추가
3. `skills/subtitle-cut/main.py`의 `reason_to_edit_reason` 매핑에 추가
4. 두 프롬프트의 reason 값 목록에 추가

**프롬프트 외 수정 가능 항목:**
- `codex_analyzer.py`의 CHUNK_SIZE, CHUNK_OVERLAP 조정
- chunk 경계 문제가 FN의 원인이면 overlap을 늘리거나 chunk 크기를 키우는 것을 고려

### Step 3: medium effort로 실행 & 평가

수정 후 **medium** effort로 실행하고 평가하세요:

```bash
/home/jonhpark/workspace/auto-video-edit/scripts/run_and_eval.sh "iter_$(date +%s)" medium
```

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
tracking 파일에 effort별 F1과 시간이 기록됩니다. 나중에 보고용으로 사용.

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
git add -A && git commit -m "subtitle-cut: improve prompt (F1: X.X% → Y.Y%)"
```

**이전 최고보다 낮지만 에러 패턴이 다르면** → 프롬프트 변경 때문인지 LLM 분산인지 판단:
- 새로운 FP/FN 유형이 등장했다면 → 프롬프트 변경이 원인. 되돌리기.
- 같은 유형의 에러 수만 다르면 → LLM 분산일 수 있음. 한번 더 실행해서 확인.

**명확히 악화됐으면** → 변경 되돌리고 다른 접근 시도.
```bash
cd /home/jonhpark/workspace/auto-video-edit
git checkout -- skills/subtitle-cut/codex_analyzer.py
```

**3번 연속 새로운 개선 아이디어가 없으면** → plateau 도달. 아래 최종 보고서를 작성하고 완료.
```
<promise>EVAL COMPLETE</promise>
```

## 최종 보고서 (완료 시 반드시 출력)

루프 종료 시 다음 형식으로 보고하세요:

```
## Eval Improvement Report

### 메트릭 변화
| 버전 | F1 | Accuracy | Precision | Recall | Errors | Effort | Time |
|------|-----|----------|-----------|--------|--------|--------|------|
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

## 현재 남은 에러 패턴 (참고)

최근 V3 기준 남은 11건 (F1=91.3%):
- FN duplicate 8: 같은 주제를 다른 표현으로 재시도한 것을 감지 못함 (주제 수준 take detection 한계)
- FN filler 1: 전환문을 filler로 인식 못함
- FN fumble 1: 잘못된 정의를 말실수로 인식 못함 (도메인 지식 필요)
- FP fumble 1: 정상 발화를 fumble로 오판

## 중요 제약

1. **subtitle-cut은 Codex CLI (GPT-5.2)를 subprocess로 호출합니다.** 직접 API 호출이 아닙니다.
2. **281 세그먼트 → chunk 처리** (80개씩, 5개 overlap, 병렬 4 chunk). CHUNK_ANALYSIS_PROMPT가 실제 사용됨.
3. **Chunk 경계 한계**: 첫 테이크와 마지막 테이크가 다른 chunk에 있으면 비교 불가. overlap 늘리기나 chunk 크기 키우기로 완화 가능.
4. **실행 비용**: 매 실행마다 Codex API 호출 4회 (chunk당 1회). ~160초/run (medium).
5. **일반화**: 이 영상에만 맞추면 다른 영상에서 성능 하락. 항상 일반 원칙으로 작성.
6. **Reasoning effort**: `CODEX_REASONING_EFFORT` 환경변수로 low/medium/high 제어. run_and_eval.sh의 두 번째 인자.
