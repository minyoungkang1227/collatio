"""Collatio 가드를 평가 세트 위에서 돌려 본다.

평가 세트에는 정답이 있다. 그래서 '모델들의 다수결 답이 틀린 문항'을 가드가 얼마나 잡는지 셀 수 있다.
가드 함수(majority, g1_agreement, evaluate)는 Collatio의 것을 그대로 쓴다.
"""
from collections import defaultdict

from . import bridges
from .grade import NUM_RE, final_answer


def normalize(item, response):
    """응답을 비교 가능한 값으로. 정답과 같으면 'TRUE', 답이 없으면 'NONE'."""
    fa = final_answer(response)
    if item["answer_type"] == "choice":
        got = next((l for l in sorted(item["choices"], key=len, reverse=True) if fa.upper().startswith(l.upper())), None)
        return "NONE" if got is None else "TRUE" if got == item["answer"]["value"] else got
    if item["answer_type"] == "numeric":
        m = NUM_RE.search(fa.replace(",", "").replace("−", "-"))
        if not m:
            return "NONE"
        got, exp = float(m.group()), item["answer"]["value"]
        return "TRUE" if abs(got - exp) <= item["answer"].get("rel_tol", 0.01) * abs(exp) + 1e-12 else f"{got:.3g}"
    return None  # 서술형은 다수결을 낼 수 없다


def check(items, responses, threshold=None):
    """{summary, rows}. rows는 문항별 다수결·일치 비율·가드 판정."""
    import numpy as np
    G = bridges.collatio("guard")
    if threshold is None:
        threshold = bridges.collatio_config()["guard"]["agreement_alert"]

    by = defaultdict(dict)
    for r in responses:
        it = items.get(r["item_id"])
        if it is not None and (v := normalize(it, r["response"])) is not None:
            by[r["item_id"]][r["model"]] = v
    models = sorted({m for d in by.values() for m in d})
    ids = sorted(i for i, d in by.items() if len(d) == len(models))
    if len(models) < 2 or not ids:
        raise SystemExit("가드 점검에는 모델 2개 이상과, 모든 모델이 답한 객관식·수치 문항이 필요합니다.")

    # 문항마다 답을 정수 코드로 바꾼다. 정답은 0, 무응답은 모델마다 다른 음수(서로 일치로 세지 않기 위해).
    answers = np.zeros((len(models), len(ids)), dtype=int)
    for j, iid in enumerate(ids):
        codes = {"TRUE": 0}
        for i, m in enumerate(models):
            v = by[iid][m]
            answers[i, j] = -(i + 1) if v == "NONE" else codes.setdefault(v, len(codes))
    truth = np.zeros(len(ids), dtype=int)

    flagged = G.g1_agreement(answers, threshold)
    winners, shares = G.majority(answers)
    summary = G.evaluate(flagged, answers, truth)
    # 다수결과 별개로: 모델 하나라도 틀린 문항을 가드가 검토로 넘겼는가.
    # 모델 하나만 쓰는 곳에서 다른 모델을 곁에 두고 대조하는 쓰임에 해당한다.
    any_wrong = (answers != 0).any(axis=0)
    hit = int((flagged & any_wrong).sum())
    summary.update(threshold=threshold, n_items=len(ids), models=models, n_any_wrong=int(any_wrong.sum()),
                   any_recall=hit / int(any_wrong.sum()) if any_wrong.any() else float("nan"),
                   any_precision=hit / int(flagged.sum()) if flagged.any() else float("nan"))
    rows = [{"item_id": iid, "majority_correct": bool(winners[j] == 0), "share": float(shares[j]),
             "flagged": bool(flagged[j]), "answers": by[iid]} for j, iid in enumerate(ids)]
    return {"summary": summary, "rows": rows}


def check_probe(items, responses, threshold=None):
    """말 바꿔 다시 묻기(Collatio G3). 같은 공시의 원문 요약과 말 바꾼 글에 대한 다수결 답이 다르면 검토로 넘긴다.

    일치도 검사(G1)는 모델들이 같은 오답에 일치하면 통과시킨다. G3는 모델끼리가 아니라
    같은 내용의 두 표현 사이를 비교하므로, 한쪽 표현에서만 함께 틀린 경우를 잡을 수 있다.
    짝이 있는 공시(meta.group이 같고 variant가 original·paraphrase인 방향 문항)만 대상이다.
    """
    import numpy as np
    G = bridges.collatio("guard")
    if threshold is None:
        threshold = bridges.collatio_config()["guard"]["agreement_alert"]
    pairs = defaultdict(dict)
    for it in items.values():
        m = it.get("meta", {})
        if it["answer_type"] == "choice" and m.get("group") and m.get("variant") in ("original", "paraphrase"):
            pairs[m["group"]][m["variant"]] = it["id"]
    by = defaultdict(dict)
    for r in responses:
        it = items.get(r["item_id"])
        if it is not None and (v := normalize(it, r["response"])) is not None:
            by[r["item_id"]][r["model"]] = v
    models = sorted({m for d in by.values() for m in d})
    groups = sorted(g for g, p in pairs.items() if len(p) == 2 and all(len(by.get(i, {})) == len(models) for i in p.values()))
    if len(models) < 2 or not groups:
        return None
    base = np.zeros((len(models), len(groups)), dtype=int)
    probe = np.zeros_like(base)
    for j, g in enumerate(groups):
        codes = {"TRUE": 0}   # 두 표현이 같은 코드표를 쓴다: 같은 오답은 같은 숫자
        for arr, variant in ((base, "original"), (probe, "paraphrase")):
            for i, m in enumerate(models):
                v = by[pairs[g][variant]][m]
                arr[i, j] = -(i + 1) if v == "NONE" else codes.setdefault(v, len(codes))
    truth = np.zeros(len(groups), dtype=int)
    g1, g3 = G.g1_agreement(base, threshold), G.g3_probe(base, probe, threshold)
    wrong = G.majority(base)[0] != truth
    return {"n_groups": len(groups), "models": models, "threshold": threshold,
            "g1": G.evaluate(g1, base, truth), "g3": G.evaluate(g3, base, truth),
            "only_g3": [groups[j] for j in range(len(groups)) if wrong[j] and g3[j] and not g1[j]],
            "missed_both": [groups[j] for j in range(len(groups)) if wrong[j] and not g3[j]]}


def render_probe(p):
    if p is None:
        return "## 말 바꿔 다시 묻기(G3)\n\n짝이 있는 공시가 없어 건너뜀.\n"
    pct = lambda x: "해당 없음" if x != x else f"{100 * x:.0f}%"
    row = lambda name, e: f"| {name} | {e['n_wrong']}개 | {pct(e['recall'])} | {pct(e['precision'])} | {pct(e['review_rate'])} |"
    return "\n".join([
        "## 말 바꿔 다시 묻기(G3)", "",
        f"원문 요약과 말 바꾼 글이 둘 다 있는 공시 {p['n_groups']}건. 원문 요약에 대한 다수결 답이 틀린 경우를 잡는지 본다.", "",
        "| 가드 | 다수결이 틀린 공시 | 잡은 비율 | 정밀도 | 검토로 넘긴 비율 |", "|---|---|---|---|---|",
        row("G1 일치도만", p["g1"]), row("G1 + G3 말 바꿔 다시 묻기", p["g3"]), "",
        "일치도는 통과했는데 G3가 잡은 공시: " + (", ".join(p["only_g3"]) or "없음"),
        "둘 다 놓친 공시: " + (", ".join(p["missed_both"]) or "없음"), ""]) + "\n"


def render(result, items):
    s = result["summary"]
    pct = lambda x: "해당 없음" if x != x else f"{100 * x:.0f}%"
    missed = [r for r in result["rows"] if not r["majority_correct"] and not r["flagged"]]
    caught = [r for r in result["rows"] if not r["majority_correct"] and r["flagged"]]
    false_alarm = [r for r in result["rows"] if r["majority_correct"] and r["flagged"]]
    lines = ["# 가드 점검 (Collatio G1: 모델 일치도)", "",
             f"모델 {len(s['models'])}개({', '.join(s['models'])}), 문항 {s['n_items']}개, 일치 기준 {s['threshold']}.", "",
             "| 항목 | 값 |", "|---|---|",
             f"| 다수결 답이 틀린 문항 | {s['n_wrong']}개 |",
             f"| 그중 가드가 잡은 비율(재현율) | {pct(s['recall'])} |",
             f"| 검토로 넘긴 것 중 실제로 틀린 비율(정밀도) | {pct(s['precision'])} |",
             f"| 검토로 넘긴 비율 | {pct(s['review_rate'])} |",
             f"| 모델 하나라도 틀린 문항 | {s['n_any_wrong']}개 |",
             f"| 그중 가드가 검토로 넘긴 비율 | {pct(s['any_recall'])} |",
             f"| 검토로 넘긴 것 중 실제로 누군가 틀린 비율 | {pct(s['any_precision'])} |", "",
             "다수결이 틀린 문항이 없어도, 한 모델만 틀린 문항을 일치도 검사가 가려내는지는 아래 세 줄로 본다.", ""]
    lines += ["## 함께 틀렸는데 가드가 놓친 문항", "",
              "모델들이 같은 오답에 일치해서 일치도 검사를 통과했다. 가장 값진 실패 사례다.", ""]
    for r in missed:
        v = items[r["item_id"]].get("meta", {})
        lines.append(f"- {r['item_id']} (일치 {r['share']:.0%}, 변형 {v.get('variant', '-')}, 엇갈린 지표 {len(v.get('conflicts') or [])}개)")
    lines += [] if missed else ["없음"]
    lines += ["", f"가드가 잡은 오답 {len(caught)}개, 정답인데 검토로 넘긴 것 {len(false_alarm)}개.", ""]
    return "\n".join(lines) + "\n"
