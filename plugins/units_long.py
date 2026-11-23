"""긴 글 속 단위 환산: 같은 계산을 글 길이만 바꿔 묻는 통제 실험.

배경. real2에서 claude-haiku는 공시 요약문 속 '전년 동기 영업이익 역산 + 백만원→억원'을 39문항 중 17건 틀렸다.
real3에서 같은 환산을 한 문장으로 물은 5문항은 모두 맞혔다. 글이 길어서 틀린 것인지, 문항이 달라서 틀린 것인지
그 두 결과로는 가를 수 없다.

방법. 핵심 사실 하나(당해 분기 영업이익과 전년 동기 대비 증감률)를 정하고, 그 사실을 네 가지 글에 똑같이 넣는다.
정답은 네 글 모두 같다. 같은 meta.group의 네 문항을 비교하면 글 길이와 방해 숫자의 효과만 남는다.

  short1   한 문장. units_inverse와 같은 대조군
  short4   매출·영업이익·순이익 세 문장의 요약(숫자 여섯 개)
  long16   부문 셋·지표 여럿, 숫자 열여섯 개 이상. 핵심 문장의 위치를 앞·중간·끝으로 돌린다
  mixed    long16과 같되 다른 숫자들이 억원·천원으로 섞여 있다. 핵심 숫자는 여전히 백만원
"""
import datetime
import random
import re

CORPS = ["가온정밀", "나래바이오", "다솜에너지", "로운물산", "미르반도체", "보람식품", "세움건설", "아라해운", "온새미로", "한결화학"]
SEGMENTS = ["소재 부문", "부품 부문", "서비스 부문"]
LENGTHS = ["short1", "short4", "long16", "mixed"]
TO_EOK = {"백만원": 0.01, "억원": 1.0, "천원": 0.00001}
ASK = "물음: 전년 동기(지난해 같은 분기)의 연결 영업이익을 억원 단위로 소수 둘째 자리까지 구하라."


def _pct(rng, lo, hi):
    return round(rng.choice([-1, 1]) * rng.uniform(lo, hi), 1)


def _chg(p):
    return f"전년 동기 대비 {abs(p)}% {'증가' if p > 0 else '감소'}"


def _money(eok, unit):
    """억원 금액을 주어진 단위의 정수 문자열로."""
    return f"{round(eok / TO_EOK[unit]):,}{unit}"


def _distractors(rng, corp, op_eok, mixed):
    """핵심 사실과 무관한 문장들. mixed면 금액 단위를 섞는다. 모든 숫자는 가상."""
    units = (lambda: rng.choice(["억원", "천원", "백만원"])) if mixed else (lambda: "백만원")
    rev = op_eok * rng.uniform(8, 20)
    out = [f"{corp}의 2026년 3분기 연결 매출액은 {_money(rev, units())}({_chg(_pct(rng, 2, 30))})이다.",
           f"연결 순이익은 {_money(op_eok * rng.uniform(0.4, 0.9), units())}({_chg(_pct(rng, 5, 60))})이다."]
    raw = [rng.uniform(0.2, 0.5) for _ in SEGMENTS]
    shares = [x / sum(raw) for x in raw]                 # 부문 합 = 연결 실적(내부거래 조정은 없다고 둔다)
    for seg, s in zip(SEGMENTS, shares):
        out.append(f"{seg}의 매출액은 {_money(rev * s, units())}, 영업이익은 {_money(op_eok * s, units())}"
                   f"(전기 대비 {abs(_pct(rng, 1, 25))}% {'증가' if rng.random() < 0.5 else '감소'})이다.")
    out += [f"누계 매출액은 {_money(rev * rng.uniform(2.6, 3.2), units())}, "
            f"누계 영업이익은 {_money(op_eok * rng.uniform(2.6, 3.4), units())}({_chg(_pct(rng, 3, 40))})이다.",
            f"분기 말 자산총계는 {_money(rev * rng.uniform(3, 6), units())}, 총차입금은 {_money(rev * rng.uniform(0.5, 1.5), units())}이다.",
            f"연구개발비는 {_money(rev * rng.uniform(0.02, 0.06), units())}으로 매출액의 {round(rng.uniform(2, 6), 1)}% 수준이다."]
    return out


def units_long_items(n, seed):
    """n은 핵심 사실의 수가 아니라 문항 수다. 핵심 사실 하나에서 길이별 문항 네 개가 나온다."""
    rng, items, k = random.Random(seed), [], 0
    today = datetime.date.today().isoformat()
    while len(items) < n:
        k += 1
        corp = rng.choice(CORPS)
        op_mil = rng.randrange(3000, 900000)              # 당해 분기 연결 영업이익(백만원)
        pct = _pct(rng, 4, 70)
        ans = op_mil / (1 + pct / 100) * TO_EOK["백만원"]
        if abs(ans) < 1:
            continue
        core = f"당해 분기 연결 영업이익은 {op_mil:,}백만원으로 {_chg(pct)}했다."
        group = f"ulong-s{seed}-{k:03d}"
        for j, length in enumerate(LENGTHS):
            if len(items) >= n:
                break
            if length == "short1":
                body = f"{corp}의 2026년 3분기 {core}"
            elif length == "short4":
                d = _distractors(rng, corp, op_mil * 0.01, False)
                body = " ".join([d[0], core, d[1]])
            else:
                d = _distractors(rng, corp, op_mil * 0.01, length == "mixed")
                pos = (k + j) % 3                              # 앞·중간·끝을 번갈아
                at = {0: 1, 1: len(d) // 2, 2: len(d)}[pos]
                d.insert(at, core)
                body = " ".join(d)
            items.append({
                "id": f"{group}-{length}", "domain": "disclosure", "answer_type": "numeric", "difficulty": 6,
                "author": "gen-units-long", "answer_source": "engine",
                "question": f"아래는 가상의 잠정실적 요약이다. 글에 적힌 숫자만으로 물음에 답하라.\n\n{body}\n\n{ASK}",
                "answer": {"value": round(ans, 4), "unit": "억원", "rel_tol": 0.01},
                "sources": [{"title": "가상 수치. 정답은 plugins/units_long.py가 계산", "as_of": today}],
                "meta": {"level": 6, "variant": f"len_{length}", "group": group, "pair": None,
                         "n_numbers": len(re.findall(r"\d[\d,.]*", body))},
            })
    return items


GENERATORS = {"units_long": units_long_items}
