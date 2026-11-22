"""금융 밖 예시 생성기: 증감률에서 과거 값을 거꾸로 계산하고 단위를 바꾸는 문항.

이 파일은 두 가지를 보여 준다.
1. 새 분야를 붙이는 법. plugins/ 폴더에 GENERATORS = {이름: 함수}를 가진 파일을 두면 `gen --source 이름`으로 쓸 수 있다.
   함수는 (n, seed)를 받아 문항 목록을 돌려준다. 정답은 함수 안에서 계산한다.
2. 실제 실행(real2)에서 나온 실패가 금융에만 있는 것인지 보는 실험. 한 모델이 공시의 '전년 동기 금액 역산'에서
   백만원을 억원으로 바꿀 때 자릿수를 틀렸다. 같은 구조의 문항을 다른 분야·다른 단위로 만들어,
   그 오류가 한국어 금액 단위에서만 나는지, 단위 환산이 낀 역산 전반에서 나는지 가른다.
"""
import datetime
import random

# (분야, 주어, 지표, 적힌 단위, 답 단위, 환산 계수, 값의 범위)
CASES = [
    ("finance", "한 회사", "분기 영업이익", "백만원", "억원", 0.01, (3000, 900000)),          # 대조군: real2에서 틀린 바로 그 환산
    ("finance", "한 회사", "분기 매출액", "억원", "조원", 0.0001, (12000, 900000)),
    ("manufacturing", "한 공장", "월 생산량", "천 개", "만 개", 0.1, (120, 90000)),
    ("manufacturing", "한 제철소", "월 출하량", "kg", "t", 0.001, (150000, 90000000)),
    ("logistics", "한 물류센터", "분기 처리 물동량", "건", "만 건", 0.0001, (150000, 90000000)),
    ("population", "한 도시", "연간 방문객 수", "천 명", "만 명", 0.1, (120, 90000)),
    ("energy", "한 발전소", "월 발전량", "MWh", "GWh", 0.001, (12000, 9000000)),
    ("health", "한 병원", "연간 외래 환자 수", "명", "만 명", 0.0001, (150000, 9000000)),
]


def units_items(n, seed):
    rng, items, k = random.Random(seed), [], 0
    today = datetime.date.today().isoformat()
    while len(items) < n:
        k += 1
        domain, who, what, unit, out_unit, factor, (lo, hi) = CASES[len(items) % len(CASES)]
        now = rng.randrange(lo, hi)
        pct = round(rng.choice([-1, 1]) * rng.uniform(4, 70), 1)
        ans = now / (1 + pct / 100) * factor
        if abs(ans) < 1:      # 소수 둘째 자리 반올림이 허용 오차를 넘지 않게
            continue
        change = f"{abs(pct)}% {'증가' if pct > 0 else '감소'}"
        q = (f"{who}의 올해 {what}은 {now:,}{unit}이며, 이는 지난해 같은 기간보다 {change}한 값이다.\n"
             f"물음: 지난해 같은 기간의 {what}을 {out_unit} 단위로 소수 둘째 자리까지 구하라.")
        items.append({
            "id": f"units-s{seed}-{k:03d}", "domain": domain, "answer_type": "numeric", "difficulty": 6,
            "author": "gen-units", "answer_source": "engine", "question": q,
            "answer": {"value": round(ans, 4), "unit": out_unit, "rel_tol": 0.01},
            "sources": [{"title": "가상 수치. 정답은 plugins/units_inverse.py가 계산", "as_of": today}],
            "meta": {"level": 6, "variant": f"{unit}→{out_unit}", "factor": factor},
        })
    return items


GENERATORS = {"units": units_items}
