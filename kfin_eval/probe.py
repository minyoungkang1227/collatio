"""검토자 점검: 정답을 아는 오답을 섞어 넣고, 검토자가 잡아내는지 본다.

AI 답을 사람에게 넘겨도 사람이 습관적으로 승인하면 브레이크가 아니다.
검토 묶음에는 정답과 오답이 섞여 있고, 어느 것이 오답인지는 열쇠 파일에만 적힌다.
오답은 두 종류다. 실제 모델이 냈던 오답(실패 사례)과, 정답을 그럴듯하게 비튼 오답.
"""
import csv
import random
from pathlib import Path

from . import store
from .grade import final_answer
from .guardlink import normalize
from .models import build_prompt

RIGHT = {"맞음", "정답", "right", "o", "ㅇ", "y", "yes", "1"}
WRONG = {"틀림", "오답", "wrong", "x", "n", "no", "0"}
MIN_SEEDED = 5       # 심은 오답이 이만큼은 쌓여야 검토자를 판정한다
MIN_CATCH = 0.5      # 포착률이 이보다 낮으면 그 검토자의 승인은 세지 않는다


def _show(item, value):
    if item["answer_type"] == "choice":
        return f"{value}. {item['choices'][value]}"
    shown = f"{value:,.4f}".rstrip("0").rstrip(".")   # 큰 수도 1,467,300처럼 풀어서 보여준다
    return f"{shown} {item['answer']['unit']}"


def _twist(item, rng):
    """정답을 그럴듯하게 비튼 오답. 허용 오차 밖인 것만 쓴다."""
    a = item["answer"]
    if item["answer_type"] == "choice":
        return rng.choice([l for l in item["choices"] if l != a["value"]])
    v, tol = a["value"], a.get("rel_tol", 0.01)
    cands = [v * 1.1, v * 0.9, -v, v * 10, v / 10]
    rng.shuffle(cands)
    return next(c for c in cands if abs(c - v) > max(tol * abs(v) * 2, 1e-9))


def make(items, failures, reviewer, n, wrong_rate, seed):
    """(tasks, key). tasks는 검토자에게 주는 것, key는 채점용 정답."""
    rng = random.Random(seed)
    pool = [i for i in items.values() if i["answer_type"] in ("numeric", "choice")]
    if not pool:
        raise SystemExit("점검에 쓸 수치·객관식 문항이 없습니다.")
    rng.shuffle(pool)
    pool = pool[:n]
    n_wrong = max(1, round(len(pool) * wrong_rate))

    # 실제 모델이 냈던 오답: 문항당 하나, 답이 읽히는 것만
    real = {}
    for f in failures:
        it = items.get(f["item_id"])
        if it and it["answer_type"] in ("numeric", "choice") and normalize(it, f["response"]) not in ("TRUE", "NONE"):
            real.setdefault(f["item_id"], final_answer(f["response"])[:80])

    batch = f"{reviewer}-s{seed}"
    tasks, key = [], []
    for k, it in enumerate(pool):
        if k < n_wrong:
            if it["id"] in real:
                shown, kind = real[it["id"]], "real_failure"
            else:
                shown, kind = _show(it, _twist(it, rng)), "twisted"
            truth = "wrong"
        else:
            shown, kind, truth = _show(it, it["answer"]["value"]), "reference", "right"
        tasks.append({"item_id": it["id"], "question": build_prompt(it), "shown_answer": shown})
        key.append({"truth": truth, "kind": kind, "item_id": it["id"]})
    order = list(range(len(tasks)))
    rng.shuffle(order)   # 오답이 앞에 몰리지 않게
    tasks, key = [tasks[i] for i in order], [key[i] for i in order]
    rate = round(sum(c["truth"] == "wrong" for c in key) / len(key), 2)
    for k, (t, c) in enumerate(zip(tasks, key), 1):
        t["task_id"] = c["task_id"] = f"{batch}-{k:02d}"
        c["wrong_rate"] = rate   # 실제로 심긴 비율
    return batch, tasks, key


def write_batch(folder, batch, reviewer, tasks, key):
    folder = Path(folder)
    sheet, keyfile = folder / f"{batch}.csv", folder / f"{batch}.key.jsonl"
    if sheet.exists() or keyfile.exists():
        raise SystemExit(f"이미 있는 묶음: {batch} (다른 --seed를 쓰세요)")
    folder.mkdir(parents=True, exist_ok=True)
    with sheet.open("w", encoding="utf-8-sig", newline="") as f:   # utf-8-sig: 엑셀에서 한글이 깨지지 않게
        w = csv.writer(f)
        w.writerow(["task_id", "문항", "제시된 답", "판정(맞음/틀림)", "메모"])
        for t in tasks:
            w.writerow([t["task_id"], t["question"], t["shown_answer"], "", ""])
    for c in key:
        store.append_jsonl(keyfile, dict(c, reviewer=reviewer))
    return sheet, keyfile


def score_batch(sheet, keyfile):
    key = {c["task_id"]: c for c in store.read_jsonl(keyfile)}
    if not key:
        raise SystemExit(f"열쇠 파일 없음: {keyfile}")
    with Path(sheet).open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))[1:]
    verdict = {}
    for r in rows:
        v = (r[3] if len(r) > 3 else "").strip().lower()
        verdict[r[0]] = "right" if v in RIGHT else "wrong" if v in WRONG else None
    out = {"reviewer": next(iter(key.values()))["reviewer"], "wrong_rate": next(iter(key.values())).get("wrong_rate"), "n_wrong": 0, "caught": 0, "missed": 0,
           "n_right": 0, "false_reject": 0, "unanswered": 0, "missed_items": []}
    for tid, c in key.items():
        v = verdict.get(tid)
        out["unanswered"] += v is None
        if c["truth"] == "wrong":
            out["n_wrong"] += 1
            if v == "wrong":
                out["caught"] += 1
            else:                       # 맞다고 했거나 답하지 않았으면 놓친 것
                out["missed"] += 1
                out["missed_items"].append(c["item_id"])
        else:
            out["n_right"] += 1
            out["false_reject"] += v == "wrong"
    return out


def totals(scores):
    """{검토자: 누적 합계}. 같은 묶음을 다시 채점했으면 마지막 것만 센다."""
    last = {}
    for s in scores:
        last[s["batch"]] = s
    agg = {}
    for s in last.values():
        a = agg.setdefault(s["reviewer"], {"n_wrong": 0, "caught": 0, "missed": 0, "n_right": 0, "false_reject": 0})
        for k in a:
            a[k] += s[k]
    return agg


def by_rate(scores):
    """심은 비율별 포착률. 비율에 따라 사람의 경계심이 달라지는지 보려는 것이다.

    참고: 오류를 조금만 심으면 실제 오류 포착이 오히려 줄고, 많이 심어야 늘었다는 실험 결과가 있다
    (Fang 외, "The Right Amount of Wrong", 2026. 참가자 17명의 모의 과제). 비율은 근거 없이 정하지 말고 재 봐야 한다.
    """
    last = {}
    for s in scores:
        last[s["batch"]] = s
    agg = {}
    for s in last.values():
        a = agg.setdefault(s.get("wrong_rate"), {"batches": 0, "n_wrong": 0, "caught": 0, "n_right": 0, "false_reject": 0})
        a["batches"] += 1
        for k in ("n_wrong", "caught", "n_right", "false_reject"):
            a[k] += s[k]
    return agg


def untrusted(scores):
    """심은 오답을 절반도 못 잡은 검토자. 이들의 승인·반려는 문항 상태에 반영하지 않는다."""
    return {r for r, a in totals(scores).items() if a["n_wrong"] >= MIN_SEEDED and a["caught"] / a["n_wrong"] < MIN_CATCH}
