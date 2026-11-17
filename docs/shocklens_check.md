# ShockLens 점검: 사건 해석에서 모델들이 함께 틀리는가

2026-11-17 · EchoGuard의 측정 방법을 [ShockLens](https://github.com/minyoungkang1227/shocklens)에 적용한다. 스크립트는 `integrations/shocklens_agreement.py`이고 ShockLens 저장소는 고치지 않는다.

## 무엇을 점검하나

ShockLens는 뉴스를 읽어 사건을 구조화하는 단계(Event Analyst)에 큰 Claude를, 1차 분류와 검증에 작은 Claude를 쓴다. 작성자와 검증자를 다른 모델로 나눴지만 같은 회사다. 해석하는 모델이 틀릴 때 다른 모델도 같은 사건에서 틀린다면, 모델을 바꿔 검증해도 걸러지지 않는다.

점검하는 질문은 세 가지다.

1. 사건 해석에서 모델들의 오류가 얼마나 겹치는가 (쌍별 오답 상관, 유효 모델 수)
2. 같은 회사 모델끼리 더 겹치는가 (Claude 두 모델, GPT 두 모델)
3. 큰 Claude가 틀린 사건에서 작은 Claude가 틀릴 확률은 평소보다 얼마나 높은가

## 방법

| 항목 | 내용 |
|---|---|
| 입력 | ShockLens 사건 라이브러리 39건의 제목 + 설명 |
| 정답 | 같은 파일에 사람이 붙인 라벨 |
| 모델 | GPT 2개, Claude 2개 (EchoGuard 패널 중 `--only`로 고름) |
| 지시문 | ShockLens의 Event Analyst 지시문과 가드레일 그대로 |
| 묻는 방식 | 모든 모델에 글로 JSON을 받는다. ShockLens 본래 방식(Claude는 도구 호출)과 다르다 |
| 반복 | 모델당 사건당 3회. 반복의 중앙값으로 맞음·틀림을 정한다 |
| 채점 필드 | 수단, 방향, 발동국, 대상국(겹치면 맞음), 산업(자카드 0.5 이상이면 맞음), 강도 등급 |
| 주 지표 | 수단·방향·발동국 세 필드가 모두 맞았는가. 충격 계산의 경로를 이 셋이 정한다 |

강도를 여러 번 물어 큰 모델과 작은 모델의 답을 섞는 ShockLens의 기능은 끈다. 모델 하나의 판단만 보기 위해서다.

## 실행

두 저장소가 같은 폴더 아래 나란히 있다고 가정한다.

```
cd C:\Users\admin\shocklens
python ..\echoguard\integrations\shocklens_agreement.py --mock
python ..\echoguard\integrations\shocklens_agreement.py
```

첫 줄은 호출 없이 흐름만 확인한다. 둘째 줄이 실제 실행이고 사건 39건 × 모델 4개 × 3회 = 468번의 사건 해석을 한다. 응답은 `echoguard/data/runs/shocklens/agreement.jsonl`에 쌓이고, 멈춰도 다시 실행하면 이어서 한다.

## 이 점검의 한계

- **모델이 사건을 이미 안다.** 라이브러리는 2002~2026년의 실제 사건이다. 모델의 학습 자료에 들어 있을 가능성이 높다. EchoGuard 본 실험은 뉴스 기간으로 이를 막았지만 여기서는 막지 못한다. 그래서 정확도는 부풀려질 수 있고, 결과는 "이 라이브러리에서의 겹침"으로만 읽는다.
- **39건이다.** 신뢰구간이 넓다. 강도 라벨이 없는 사건은 강도 채점에서 빠진다.
- **정답도 사람의 판단이다.** 특히 강도와 산업은 라벨러에 따라 달라질 수 있다. 수단·방향·발동국이 가장 객관적이라 주 지표로 삼았다.
- **묻는 방식이 ShockLens 본래와 다르다.** Claude의 정확도가 실제 운용 때와 다를 수 있다.
- **해석 단계만 본다.** 해석 오류가 손실 위험(ES) 숫자를 얼마나 바꾸는지는 다음 단계다. ShockLens의 데이터 파이프라인이 준비된 곳에서 따로 돌려야 한다.
- 스크립트는 가짜 모델로 흐름을 확인했다. 실제 API 호출로는 아직 돌려 보지 않았다.

## 결과

아직 없다.

## 뉴스를 ShockLens로 해석하고 EchoGuard로 거르기

위의 점검은 정답이 있는 과거 사건으로 "모델들이 함께 틀리는가"를 잰다. 아래는 정답이 없는 오늘의 뉴스에 필터를 실제로 거는 것이다.

```
cd C:\Users\admin\shocklens
python ..\echoguard\integrations\shocklens_screen.py --mock --file 뉴스.txt    # 호출 없이 흐름 확인
python ..\echoguard\integrations\shocklens_screen.py --today                   # 오늘 헤드라인에서 정책 토픽을 골라 판정
```

같은 뉴스를 모델 네 개가 각자 ShockLens의 Event Analyst로 해석한다. EchoGuard가 그 해석들을 보고 통과, 검토, 범위 밖 중 하나로 판정한다.

| 검사 | 걸리는 경우 |
|---|---|
| G0 입력 점검 | 글 안에 지시문으로 의심되는 문장이 있다 (ShockLens의 탐지 결과). 본문이 300자보다 짧다 |
| 응답 | 호출이 실패해 답을 내지 못한 모델이 있다 |
| 정책 사건 여부 | 정책 사건인지부터 모델들의 판단이 갈린다. 전부 아니라고 하면 "범위 밖" |
| G1 답의 일치 | 수단, 방향, 발동국 중 하나라도 갈린다 |
| G6 근거 대조 | 수단이나 발동국에 근거 문장을 대지 못한 모델이 있다 |
| G4a 보도 매체 수 | 이 토픽을 다룬 매체가 한 곳뿐이다. 받아쓴 기사도 세므로 독립 확인은 아니다 |

판정은 `data/audit/shocklens_decisions.jsonl`에 남고, 모델별 답은 `data/runs/shocklens/screen_날짜.jsonl`에 남는다.

정답이 없으므로 "통과"가 "맞았다"를 뜻하지 않는다. 모델들이 같은 근거로 같은 해석을 했다는 뜻이다. 함께 틀린 해석은 통과한다. 그 비율이 얼마인지는 위의 과거 사건 점검이 답한다.

잠정실적 공시는 ShockLens가 다루지 않는다. 공시는 `python -m echoguard.filter --numbers`로 판정한다.
