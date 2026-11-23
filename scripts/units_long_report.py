"""units_long 실험의 길이별 결과표. runs/<run-id>/grades.jsonl을 읽어 runs/<run-id>/units_long.md를 쓴다.

  python scripts/units_long_report.py --run-id ulong1

보는 것
1. 모델 × 글 길이별 정답률.
2. 짝 비교: 같은 핵심 사실에서 short1은 맞고 긴 글은 틀린 묶음 수(b)와 그 반대(c). 정확 McNemar(양측 이항) p.
   b와 c가 모두 작으면 p는 의미가 없다. 결과 전에 정한 기준: b − c ≥ 3이고 p < 0.05일 때만 '길이 효과 있음'.
3. 오답이 정답의 10의 거듭제곱 배인지(자릿수 오류). real2·real3에서 나온 오답 유형이다.
"""
import argparse
import json
import math
import re
from collections import defaultdict
from pathlib import Path

LENGTHS = ["short1", "short4", "long16", "mixed"]
ID = re.compile(r"^(ulong-s\d+-\d+)-(short1|short4|long16|mixed)$")
DETAIL = re.compile(r"응답 (-?[\d.]+(?:e-?\d+)?) / 정답 (-?[\d.]+)")


def binom_two_sided(b, c):
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    p = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return min(1.0, 2 * p)


def digit_error(detail):
    """오답이 정답의 10^k배(k ≠ 0)면 k, 아니면 None."""
    m = DETAIL.search(detail or "")
    if not m:
        return None
    got, want = float(m[1]), float(m[2])
    if got == 0 or want == 0 or (got > 0) != (want > 0):
        return None
    k = math.log10(got / want)
    r = round(k)
    return r if r != 0 and abs(k - r) < 0.005 else None


def analyze(rows):
    cell = defaultdict(lambda: [0, 0])            # (model, length) -> [맞음, 전체]
    by_group = defaultdict(dict)                  # (model, group) -> {length: 맞음 여부}
    digits = defaultdict(lambda: defaultdict(int))  # (model, length) -> {k: 건수}
    for r in rows:
        m = ID.match(r.get("item_id", ""))
        if not m:
            continue
        group, length = m[1], m[2]
        ok = r.get("score", 0) >= 1.0
        cell[(r["model"], length)][0] += ok
        cell[(r["model"], length)][1] += 1
        by_group[(r["model"], group)][length] = ok
        if not ok:
            k = digit_error(r.get("detail"))
            digits[(r["model"], length)]["자릿수 10^%+d" % k if k is not None else "그 밖"] += 1
    models = sorted({m for m, _ in cell})
    pairs = {}
    for model in models:
        for length in LENGTHS[1:]:
            b = c = 0
            for (mm, _), d in by_group.items():
                if mm != model or "short1" not in d or length not in d:
                    continue
                b += d["short1"] and not d[length]
                c += d[length] and not d["short1"]
            pairs[(model, length)] = (b, c, binom_two_sided(b, c))
    return models, cell, pairs, digits


def render(run_id, models, cell, pairs, digits):
    out = [f"# 글 길이별 단위 환산 ({run_id})", "",
           "같은 핵심 사실(당해 분기 영업이익과 증감률)을 네 가지 길이의 글에 넣고 전년 동기 영업이익을 억원으로 물었다. 정답은 네 글 모두 같다.", "",
           "| 모델 | " + " | ".join(LENGTHS) + " |", "|---|" + "---|" * len(LENGTHS)]
    for m in models:
        cells = []
        for L in LENGTHS:
            ok, n = cell.get((m, L), (0, 0))
            cells.append(f"{100 * ok / n:.1f}% ({ok}/{n})" if n else "-")
        out.append(f"| {m} | " + " | ".join(cells) + " |")
    out += ["", "## 짝 비교 (short1 대비)", "",
            "b = short1은 맞고 이 글은 틀린 묶음, c = 그 반대. 기준(결과 전에 정함): b − c ≥ 3이고 p < 0.05면 '길이 효과 있음'.", "",
            "| 모델 | 비교 | b | c | p(정확 McNemar) | 판정 |", "|---|---|---|---|---|---|"]
    for m in models:
        for L in LENGTHS[1:]:
            b, c, p = pairs[(m, L)]
            verdict = "길이 효과 있음" if b - c >= 3 and p < 0.05 else ("표본 부족" if b + c < 5 else "차이 없음")
            out.append(f"| {m} | short1 → {L} | {b} | {c} | {p:.3f} | {verdict} |")
    out += ["", "## 오답의 모양", "", "| 모델 | 글 | 유형 | 건수 |", "|---|---|---|---|"]
    rows = [(m, L, k, v) for (m, L), d in sorted(digits.items()) for k, v in sorted(d.items())]
    out += [f"| {m} | {L} | {k} | {v} |" for m, L, k, v in rows] or ["| - | - | 오답 없음 | 0 |"]
    out += ["", "문항마다 한 번씩만 물은 결과다. 묶음이 적으면 p값은 참고만 한다."]
    return "\n".join(out) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--root", default=".")
    a = ap.parse_args(argv)
    d = Path(a.root, "runs", a.run_id)
    rows = [json.loads(x) for x in (d / "grades.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    md = render(a.run_id, *analyze(rows))
    (d / "units_long.md").write_text(md, encoding="utf-8")
    print(md)


if __name__ == "__main__":
    main()
