# Collatio

[![tests](https://github.com/minyoungkang1227/collatio/actions/workflows/tests.yml/badge.svg)](https://github.com/minyoungkang1227/collatio/actions/workflows/tests.yml)


금융회사가 AI에 문서를 읽힐 때, 틀린 답이 그대로 쓰이지 않게 거르는 장치와 그것을 시험한 기록.

A filter for LLM readings of Korean financial disclosures, and the experiments that reshaped it.

> 상태 (2026-11-22): 탐색용 실험 세 번과 원문 대조의 실제 확인을 마쳤다. 사전에 정한 본 실행은 하지 않았다. 여기서 일단락한다.

## 한 줄 결과

**여러 AI는 함께 틀리지 않았다. 대신 함께 속았다.**

| 입력 | 답 수 | 결과 |
|---|---|---|
| 공시 원문 그대로 (요약 두 가지, 원문 표) | 600 | 오답 0 |
| 숫자를 뒤집은 글 | 560 | 546개가 글대로 답함 |

공시 10건, 모델 4개(GPT 2, Claude 2), 판단 기준을 적어 준 과제 하나에서의 결과다. 자세한 내용과 말할 수 없는 것은 [docs/findings.md](docs/findings.md).

## 그래서 무엇을 만들었나

처음에는 여러 모델의 답을 서로 대조하려 했다. 실험에서 그 방법은 조작된 글을 하나도 잡지 못했다. 모델들이 틀린 글을 똑같이 정확하게 읽었기 때문이다. 그래서 무게를 입력 쪽으로 옮겼다.

```
받은 숫자 → G0 숫자끼리 앞뒤가 맞는가 → G4c 전자공시 원문과 같은가 → 모델 패널 → G1·G6 답과 근거 → 통과 / 검토
```

- 공시 원문은 사람도 AI도 옮기지 않고 코드가 읽는다 (`src/collatio/dart.py`, 실제 공시 50건 중 47건을 읽음).
- 받은 숫자를 전자공시 원문과 맞춰 본다. 실제 전자공시에 대고 돌렸을 때 원문 그대로인 숫자 47개는 전부 통과했고, 부호만 바꾼 숫자 35개는 전부 걸렸다.
- 하나라도 걸리면 사람에게 넘긴다. 답을 고치지 않는다.
- 판정과 사람의 검토 결과는 기록에 남는다 (`src/collatio/audit.py`).

필터 사용법은 [docs/filter.md](docs/filter.md), 운영 쪽 위험(모델 변경, 공급사 장애, 숨긴 지시문)은 [docs/operations.md](docs/operations.md), 다루는 문제의 지도는 [docs/problem_register.md](docs/problem_register.md).

## 거르는 장치를 재는 도구 (kfin_eval)

2026-11-23에 [kfin-eval](https://github.com/minyoungkang1227/kfin-eval) 저장소를 이 저장소로 합쳤다(`src/kfin_eval/`, 커밋 기록 포함).
정답이 있는 문항으로 모델을 시험하고, 거기서 나온 실제 오답을 위의 가드가 잡는지 센다.

| | real1 | real2 | real3 | 합계 |
|---|---|---|---|---|
| 호출 | 423 | 813 | 360 | 1,596 |
| 오답 | 0 | 26 | 6 | 32 |
| 일치도 검사가 넘긴 문항 = 누군가 틀린 문항 | - | 26 = 26 | 6 = 6 | 32 = 32 |

세 모델이 같은 오답을 낸 경우는 아직 없어서, 그때 가드가 잡는지는 모른다. 문항마다 한 번씩만 물었고 사람 검수자는 없다.
자세한 내용은 [docs/kfin_eval.md](docs/kfin_eval.md), 검증 보고서는 [docs/validation_report.md](docs/validation_report.md).
모델 목록·호출 코드·가드·프롬프트가 바뀌면 CI가 고정 30문항으로 다시 잰다(`.github/workflows/eval-live.yml`, API 키 시크릿이 있을 때).

```bash
PYTHONPATH=src python -m kfin_eval ci-key                                     # 엔진이 계산한 정답이 고정본과 같은가
PYTHONPATH=src python -m kfin_eval ci-smoke --models mock-perfect,mock-noisy  # 키 없이 소규모 eval 흐름
```

## 문서

다음 방향 [docs/roadmap.md](docs/roadmap.md) · 결과 [docs/findings.md](docs/findings.md) · 실험 기록 [docs/pilot_log.md](docs/pilot_log.md) · 가설과 분석 방법 [docs/experiment_spec.md](docs/experiment_spec.md) · 선행연구 [docs/related_work.md](docs/related_work.md) · 코드 구조 [docs/architecture.md](docs/architecture.md)  
데이터 규칙 [docs/data_dictionary.md](docs/data_dictionary.md) · 평가 세트 커버리지 [docs/coverage.md](docs/coverage.md)

## 실행

```bash
pip install -r requirements.txt
pytest
PYTHONPATH=src python -m collatio.pipeline --mock   # 모의 모델로 전체 흐름 실행
PYTHONPATH=src python -m collatio.filter --mock     # 필터: 문서 한 건을 통과/검토로 판정하는 예시
PYTHONPATH=src python -m collatio.drift 예전.jsonl 지금.jsonl   # 모델이 바뀌었는지 점검
PYTHONPATH=src python -m collatio.check             # 실제 모델 시험 호출 (API 키 필요)
python scripts/fetch_disclosures.py 10 && python scripts/dart_to_labels.py 10   # 공시 원문을 받아 코드로 읽기 (DART_API_KEY 필요)
python scripts/check_against_dart.py                 # 받은 숫자를 전자공시 원문과 대조
```

API 키 준비는 [docs/setup.md](docs/setup.md), 뉴스 라벨링 순서는 [docs/labeling_guide.md](docs/labeling_guide.md).

## 내 데이터로 돌려 보기, 의견 보내기

다른 문서와 다른 모델 조합에 같은 방법을 적용하는 순서는 [docs/use_your_own_data.md](docs/use_your_own_data.md). 돌려 본 결과, 막힌 곳, 방법에 대한 이의는 [이슈](https://github.com/minyoungkang1227/collatio/issues/new/choose)로 받는다.

모의 실행의 숫자는 실제 모델과 무관하다. 되는 것과 안 되는 것은 [docs/architecture.md](docs/architecture.md) 6장.

## 한계

- 공시 10건, 모델 4개의 탐색용 결과다. 시장 전체나 다른 종류의 문서에 대한 주장이 아니다.
- 모델이 틀리지 않아서, 오답의 상관을 재는 지표와 답을 대조하는 가드는 시험되지 못했다.
- 원문 대조는 전자공시에 원문이 있는 글에만 쓸 수 있다.

`integrations/`의 ShockLens 연동은 시험 삼아 붙여 본 선택 기능이고 본체는 그것에 기대지 않는다.
