# EchoGuard

AI가 낸 답을 사람이나 다음 시스템으로 넘기기 전에 거르는 필터. 여러 AI가 같은 금융 문서에 **다 같이 틀리는 순간**을 재고, 의심스러운 답을 사람에게 넘긴다.

A filter and black-box stress test for correlated errors across LLMs on Korean financial text.

> 상태 (2026-11-18): 필터와 실험 틀이 모의 모델로 끝까지 돈다. 실제 모델로 돌린 것은 두 가지뿐이다. 공시 10건 시범 실행(원문 오답 0건이라 설계를 바꿨다)과 오늘의 뉴스 4건 판정 두 차례(기사 본문 수집이 대부분 실패했다). 가드의 성능 수치는 아직 없다. 기록은 [docs/pilot_log.md](docs/pilot_log.md).

## 방향

목적은 방어다. 본체는 가드이고, 측정은 가드가 실제로 잡는지 확인하는 수단이다. 답을 고치지 않는다. 걸러서 사람에게 넘긴다. 다루는 문제의 목록은 [docs/problem_register.md](docs/problem_register.md), 운영 쪽 위험은 [docs/operations.md](docs/operations.md).

## 쓰는 법

```
python -m echoguard.filter --mock                                              # 지어낸 답으로 판정 과정 보기
python -m echoguard.filter --numbers data/examples/disclosure_example.json     # 공시 숫자 한 건을 실제 모델에 묻고 판정
```

잠정실적 공시의 숫자를 넣으면 요약을 만들어 모델 패널에 묻고, 답을 걸러 통과 또는 검토로 판정한다.
필터가 보는 것: 입력의 모순(G0), 답의 일치(G1), 말을 바꿔도 같은가(G3), 출처(G4b), 근거(G6). 하나라도 걸리면 검토다. 판정과 사람의 검토 결과는 기록에 남는다. 자세한 것은 [docs/filter.md](docs/filter.md).

EchoGuard는 다른 프로젝트 없이 혼자 돈다. `integrations/` 폴더의 ShockLens 연동은 시험 삼아 붙여 본 선택 기능이고, 본체와 실험은 그것에 기대지 않는다.

## 왜 만드나

금융당국은 금융회사들이 비슷한 AI를 쓰면 판단이 한쪽으로 쏠릴 수 있다고 경고한다. 그런데 그 쏠림을 어떤 데이터로 어떻게 잴지는 정해진 게 없고, 제안된 지표들은 각 회사의 비공개 모델 내부를 봐야 계산할 수 있다.

EchoGuard는 모델 내부를 보지 않는다. 같은 뉴스를 여러 모델에 넣고 출력만 비교한다. 모델들이 일치하는 것 자체는 문제가 아니다. 틀린 답에 일치하는 것이 문제이고, 이 프로젝트가 재는 것도 그것이다.

## 두 트랙

| 트랙 | 상황 | 모델에 묻는 것 |
|---|---|---|
| 기관 | 금융사가 뉴스를 AI로 해석 | 사건 강도(1~5)와 방향 |
| 개인 | 일반 투자자가 챗봇에 질문 | 매수·보유·매도·판단 안 함 |

## 구조

```
한국어 금융 뉴스 (정답 라벨 수기 작성)
   → 변형기: 원본 / 문체만 바꿈 / 사실 뒤집음 / AI 문체 / 출처 표기 바꿈 / 여러 건 보도로 꾸밈
   → 모델 패널: LLM 여러 개 × 반복 호출
   → 측정 엔진 (LLM 없음)
        ① 모델 내 분산
        ② 모델 간 일치도 (순서형 Krippendorff α)
        ③ 상관 오류: 일치했는데 틀린 비율
        ④ 동반 뒤집힘: 변형 시 같은 방향으로 바뀐 비율
   → 환산: 모델별 출력이 만드는 ES 차이
   → 가드: 일치도 / 출처 표기 / 변형 탐침 / 독립 출처 대조 / 학습 가드 → 통과·검토
```

코드 구조는 [docs/architecture.md](docs/architecture.md), 연구 설계는 [docs/design.md](docs/design.md), 학습하는 가드는 [docs/learned_guard.md](docs/learned_guard.md), 선행연구와의 차이는 [docs/related_work.md](docs/related_work.md), 가설과 분석 방법은 [docs/experiment_spec.md](docs/experiment_spec.md), 라벨 기준은 [docs/labeling_guide.md](docs/labeling_guide.md).

## 실행

```bash
pip install -r requirements.txt
pytest
PYTHONPATH=src python -m echoguard.pipeline --mock   # 모의 모델로 전체 흐름 실행
PYTHONPATH=src python -m echoguard.filter --mock     # 필터: 문서 한 건을 통과/검토로 판정하는 예시
PYTHONPATH=src python -m echoguard.drift 예전.jsonl 지금.jsonl   # 모델이 바뀌었는지 점검
PYTHONPATH=src python -m echoguard.check             # 실제 모델 시험 호출 (API 키 필요)
```

API 키 준비는 [docs/setup.md](docs/setup.md), 뉴스 라벨링 순서는 [docs/labeling_guide.md](docs/labeling_guide.md).

## 다른 프로젝트에 적용

같은 측정을 지경학 뉴스 해석 에이전트 [ShockLens](https://github.com/minyoungkang1227/shocklens)에 적용한다. 방법과 한계는 [docs/shocklens_check.md](docs/shocklens_check.md).

## 내 데이터로 돌려 보기, 의견 보내기

다른 문서와 다른 모델 조합에 같은 방법을 적용하는 순서는 [docs/use_your_own_data.md](docs/use_your_own_data.md). 돌려 본 결과, 막힌 곳, 방법에 대한 이의는 [이슈](https://github.com/minyoungkang1227/echoguard/issues/new/choose)로 받는다.

모의 실행의 숫자는 실제 모델과 무관하다. 되는 것과 안 되는 것은 [docs/architecture.md](docs/architecture.md) 6장.

## 한계

- 모델 5~7개 패널의 결과다. 시장 전체에 대한 주장이 아니다.
- 변형 뉴스를 AI로 만들면 사람이 쓴 가짜뉴스와 문체가 다를 수 있다.
- 정답 라벨은 한 사람이 붙인다. 라벨 근거를 열로 남겨 검토할 수 있게 한다.
