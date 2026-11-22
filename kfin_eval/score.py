"""기여 점수. 사람이 아니라 기여 한 건에 매기고, AI의 판단이 아니라 측정값으로 매긴다.

문항 점수   = 100 × (그 문항을 틀린 모델의 비율). 검증을 통과한 문항만.
검토 점수   = 심은 오답을 잡으면 +5, 놓치면 −5, 정답을 틀렸다고 하면 −2. 0 아래로는 내려가지 않는다.
사람의 점수 = 그 사람이 낸 문항 점수의 합 + 검토 점수.

점수는 저장해 두는 값이 아니다. 실행 결과, 검수, 오류 분류가 바뀌면 다시 계산되어 달라진다.
거짓이거나 모호한 문항으로 점수를 얻지 못하게 하는 장치:
  검증 전 문항은 0점, 문항 오류로 분류되면 0점,
  모든 모델이 틀린 문항은 사람 검수가 한 건도 없으면 보류.
"""
from collections import defaultdict

from . import probe

CATCH, MISS, FALSE_REJECT = 5, -5, -2


def item_rows(items, status, grades, failures, annotations):
    scores = defaultdict(lambda: defaultdict(list))
    for g in grades:
        scores[g["item_id"]][g["model"]].append(g["score"])
    fail_item = {f["id"]: f["item_id"] for f in failures}
    broken = {fail_item[a["failure_id"]] for a in annotations if a["error_type"] == "item" and a["failure_id"] in fail_item}

    rows = []
    for it in items:
        st = status[it["id"]]
        per_model = [sum(v) / len(v) for v in scores[it["id"]].values()]
        fail = 1 - sum(per_model) / len(per_model) if per_model else None
        row = {"item_id": it["id"], "author": it["author"], "n_models": len(per_model),
               "fail_rate": fail, "points": 0.0, "note": ""}
        if st["status"] != "approved":
            row["note"] = "검증 전" if st["status"] == "pending" else "반려됨"
        elif it["id"] in broken:
            row["note"] = "문항 오류로 분류됨"
        elif len(per_model) < 2:
            row["note"] = "실행 결과 부족(모델 2개 이상 필요)"
        elif fail == 1 and st["approvals"] == 0:
            row["note"] = "보류: 모든 모델이 틀림. 사람 검수 필요"
        else:
            row["points"] = round(100 * fail, 1)
        rows.append(row)
    return rows


def people(rows, reviewer_scores):
    out = defaultdict(lambda: {"items": 0, "scored_items": 0, "item_points": 0.0, "review_points": 0.0, "caught": 0, "missed": 0})
    for r in rows:
        p = out[r["author"]]
        p["items"] += 1
        p["scored_items"] += r["points"] > 0
        p["item_points"] += r["points"]
    for reviewer, a in probe.totals(reviewer_scores).items():
        p = out[reviewer]
        p["caught"], p["missed"] = a["caught"], a["missed"]
        p["review_points"] = max(0.0, CATCH * a["caught"] + MISS * a["missed"] + FALSE_REJECT * a["false_reject"])
    for p in out.values():
        p["total"] = round(p["item_points"] + p["review_points"], 1)
    return dict(out)


def render(rows, ppl, untrusted):
    lines = ["# 기여 점수", "", "지금 있는 실행 결과와 검수 기록으로 계산한 값이다. 기록이 바뀌면 점수도 바뀐다.", "",
             "## 사람별", "", "| 이름 | 합계 | 문항 점수 | 점수 받은 문항 / 낸 문항 | 검토 점수 | 오답 포착 / 놓침 |", "|---|---|---|---|---|---|"]
    for name, p in sorted(ppl.items(), key=lambda kv: -kv[1]["total"]):
        tag = " (검토 신뢰 미달)" if name in untrusted else " (엔진)" if name.startswith("gen-") else ""
        lines.append(f"| {name}{tag} | {p['total']:.1f} | {p['item_points']:.1f} | {p['scored_items']} / {p['items']} "
                     f"| {p['review_points']:.1f} | {p['caught']} / {p['missed']} |")
    top = sorted((r for r in rows if r["points"] > 0), key=lambda r: -r["points"])[:10]
    lines += ["", "## 점수 높은 문항", "", "| 문항 | 낸 사람 | 틀린 모델 비율 | 점수 |", "|---|---|---|---|"]
    lines += [f"| {r['item_id']} | {r['author']} | {r['fail_rate']:.0%} ({r['n_models']}개 모델) | {r['points']:.1f} |" for r in top] or ["| 없음 | | | |"]
    held = defaultdict(int)
    for r in rows:
        if r["note"]:
            held[r["note"]] += 1
    lines += ["", "## 점수를 받지 못한 문항", ""] + ([f"- {k}: {v}개" for k, v in sorted(held.items())] or ["없음"])
    return "\n".join(lines) + "\n"
