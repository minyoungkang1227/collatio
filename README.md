# EchoGuard

여러 AI가 같은 금융 뉴스에 **다 같이 틀리는 순간**을 재고, 그때 경보를 내는 방어 계층.

Black-box stress test for correlated errors across LLMs on Korean financial news.

> 상태 (2026-11-16): 모의 모델로 전체 흐름이 돈다. 실제 공시 10건으로 시범 실행을 하는 중이다(1,080회 호출 중 720회 완료). 뉴스 100건의 본 실행과 그 결과는 아직 없다.

## 방향

목적은 방어다. AI 사용이 늘면서 금융회사와 일반 이용자에게 생길 문제를 미리 찾고, 재고, 대안을 준비한다. 다루는 문제의 목록은 [docs/problem_register.md](docs/problem_register.md).

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
PYTHONPATH=src python -m echoguard.check             # 실제 모델 시험 호출 (API 키 필요)
```

API 키 준비는 [docs/setup.md](docs/setup.md), 뉴스 라벨링 순서는 [docs/labeling_guide.md](docs/labeling_guide.md).

## 내 데이터로 돌려 보기, 의견 보내기

다른 문서와 다른 모델 조합에 같은 방법을 적용하는 순서는 [docs/use_your_own_data.md](docs/use_your_own_data.md). 돌려 본 결과, 막힌 곳, 방법에 대한 이의는 [이슈](https://github.com/minyoungkang1227/echoguard/issues/new/choose)로 받는다.

모의 실행의 숫자는 실제 모델과 무관하다. 되는 것과 안 되는 것은 [docs/architecture.md](docs/architecture.md) 6장.

## 한계

- 모델 5~7개 패널의 결과다. 시장 전체에 대한 주장이 아니다.
- 변형 뉴스를 AI로 만들면 사람이 쓴 가짜뉴스와 문체가 다를 수 있다.
- 정답 라벨은 한 사람이 붙인다. 라벨 근거를 열로 남겨 검토할 수 있게 한다.
