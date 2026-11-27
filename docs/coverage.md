# 평가 세트 커버리지

문항 93개. 칸당 목표 5개. `kfin_eval coverage`로 다시 만든다.

## 분야 × 난도

| 분야 | 1단 | 2단 | 3단 | 4단 | 5단 | 6단 | 합계 |
|---|---|---|---|---|---|---|---|
| risk | 1 | 2 | 0 | 0 | 0 | 0 | 3 |
| product | 0 | 0 | 1 | 0 | 0 | 0 | 1 |
| regulation | 1 | 1 | 0 | 0 | 0 | 0 | 2 |
| disclosure | 1 | 14 | 15 | 15 | 29 | 13 | 87 |

## 분야 × 답 형식

| 분야 | numeric | choice | rubric |
|---|---|---|---|
| risk | 3 | 0 | 0 |
| product | 0 | 0 | 1 |
| regulation | 0 | 1 | 1 |
| disclosure | 42 | 45 | 0 |

## 없는 것

- 빈 칸 13개: risk 3단, risk 4단, risk 5단, risk 6단, product 1단, product 2단, product 4단, product 5단, product 6단, regulation 3단, regulation 4단, regulation 5단, regulation 6단
- 목표 미달 6개: risk 1단(1), risk 2단(2), product 3단(1), regulation 1단(1), regulation 2단(1), disclosure 1단(1)
- 실무 판단 문항(정답이 하나로 안 떨어지는 판단)은 현업 검수자 없이 만들지 않는다
- 사람 검수자 0명: 2인 교차 검수가 실제로 돈 적이 없다
- 규제 문항은 2차 출처로만 대조했다(국가법령정보센터 원문 미확인)
- real3의 상품·리스크 문항은 가상 숫자다

센 범위: `data/items`와 dist/public.jsonl. 비공개 문항(184개, `dist/MANIFEST.json`)과 생성기로 다시 만드는 문항(`gen`)은 이 표에 없다.
