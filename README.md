# Collatio

[![tests](https://github.com/minyoungkang1227/collatio/actions/workflows/tests.yml/badge.svg)](https://github.com/minyoungkang1227/collatio/actions/workflows/tests.yml)

> 이름: collatio는 라틴어로 필사본을 원본과 한 줄씩 맞춰 보는 일이다. 2026-11-22까지의 이름은 EchoGuard였다. 여러 AI가 서로의 메아리가 된다는 처음 가설에서 온 이름인데, 실험이 가리킨 것은 원문 대조였다.

금융회사가 AI에 문서를 읽힐 때, 틀린 답이 그대로 쓰이지 않게 거르는 장치와 그것을 시험한 기록.

A filter for LLM readings of Korean financial disclosures, and the experiments that reshaped it.

> 상태 (2026-11-22): 탐색용 실험 세 번을 마쳤다. 사전에 정한 본 실행은 하지 않았다.

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
- 하나라도 걸리면 사람에게 넘긴다. 답을 고치지 않는다.
- 판정과 사람의 검토 결과는 기록에 남는다 (`src/collatio/audit.py`).

필터 사용법은 [docs/filter.md](docs/filter.md), 운영 쪽 위험(모델 변경, 공급사 장애, 숨긴 지시문)은 [docs/operations.md](docs/operations.md), 다루는 문제의 지도는 [docs/problem_register.md](docs/problem_register.md).

## 문서

결과 [docs/findings.md](docs/findings.md) · 실험 기록 [docs/pilot_log.md](docs/pilot_log.md) · 가설과 분석 방법 [docs/experiment_spec.md](docs/experiment_spec.md) · 선행연구 [docs/related_work.md](docs/related_work.md) · 코드 구조 [docs/architecture.md](docs/architecture.md)

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
