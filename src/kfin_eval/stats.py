"""모델 비교 검정, 다중비교 보정, 라쉬(1PL) 문항 반응 모형.

점수표의 구간은 모델마다 따로 낸다. 두 모델의 차이를 말하려면 같은 문항 위에서 차이 자체의 구간을 내야 한다.
따로 낸 두 구간이 겹쳐도 차이는 0에서 떨어져 있을 수 있다(같은 문항을 풀어 점수가 함께 움직이기 때문이다).
"""
import math
import random
from collections import defaultdict
from itertools import combinations

N_BOOT = 4000
SEED = 20261122
MIN_MODELS_IRT = 5   # 이보다 모델이 적으면 문항 모수 추정이 불안정하다는 경고를 붙인다


def paired_diff(rows, a, b, group_of, n_boot=N_BOOT, seed=SEED):
    """모델 a − b의 평균 점수 차이(100점 척도), 95% 구간, 양측 p값.

    두 모델이 모두 푼 문항만 쓴다. 공시(meta.group) 단위로 복원추출한다.
    p값은 부트스트랩 분포에서 0의 반대편에 놓인 비율의 두 배다(최소 1/n_boot).
    """
    sa, sb = {}, {}
    for r in rows:
        if r["model"] == a:
            sa[r["item_id"]] = r["score"]
        elif r["model"] == b:
            sb[r["item_id"]] = r["score"]
    groups = defaultdict(list)
    for iid in sa.keys() & sb.keys():
        groups[group_of.get(iid, iid)].append(sa[iid] - sb[iid])
    keys = sorted(groups, key=str)
    if not keys:
        return None
    n = sum(len(v) for v in groups.values())
    est = 100 * sum(sum(v) for v in groups.values()) / n
    rng, boots = random.Random(seed), []
    for _ in range(n_boot):
        tot = cnt = 0
        for k in (rng.choice(keys) for _ in keys):
            tot += sum(groups[k]); cnt += len(groups[k])
        boots.append(100 * tot / cnt)
    boots.sort()
    lo, hi = boots[int(0.025 * n_boot)], boots[int(0.975 * n_boot) - 1]
    if est == 0:
        p = 1.0
    else:
        other_side = sum(x <= 0 for x in boots) if est > 0 else sum(x >= 0 for x in boots)
        p = min(1.0, max(2 * other_side, 1) / n_boot)
    return {"a": a, "b": b, "n_items": n, "n_groups": len(keys), "diff": est, "lo": lo, "hi": hi, "p": p}


def holm(pvals):
    """Holm 보정 p값. 입력과 같은 순서로 돌려준다."""
    order = sorted(range(len(pvals)), key=lambda i: pvals[i])
    adj, running = [0.0] * len(pvals), 0.0
    m = len(pvals)
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (m - rank) * pvals[i]))
        adj[i] = running
    return adj


def pairwise(rows, group_of, alpha=0.05):
    """모든 모델 쌍의 차이 검정 + Holm 보정."""
    models = sorted({r["model"] for r in rows})
    mean = {m: sum(r["score"] for r in rows if r["model"] == m) / max(1, sum(r["model"] == m for r in rows)) for m in models}
    res = []
    for x, y in combinations(models, 2):
        a, b = (x, y) if mean[x] >= mean[y] else (y, x)   # 점수가 높은 쪽을 앞에 둔다
        d = paired_diff(rows, a, b, group_of)
        if d:
            res.append(d)
    for d, p in zip(res, holm([d["p"] for d in res])):
        d["p_holm"] = p
        d["significant"] = p < alpha
    return res


def render_pairwise(res):
    if not res:
        return ""
    lines = ["## 모델 쌍 비교", "",
             "같은 문항 위에서 낸 점수 차이다. 구간은 공시 단위로 다시 뽑아 계산했고, p값은 비교 횟수만큼 Holm 보정했다.", "",
             "| 비교 | 차이(점) | 차이의 95% 구간 | p(보정 전) | p(Holm) | 판정 |", "|---|---|---|---|---|---|"]
    for d in res:
        verdict = "차이 있음" if d["significant"] else "차이를 말할 수 없음"
        lines.append(f"| {d['a']} − {d['b']} | {d['diff']:+.1f} | {d['lo']:+.1f} ~ {d['hi']:+.1f} "
                     f"| {d['p']:.3f} | {d['p_holm']:.3f} | {verdict} |")
    lines += ["", "모델별 구간이 겹쳐도 차이의 구간이 0을 빼면 차이가 있다고 본다. 보정 후 p가 0.05 미만일 때만 '차이 있음'이다."]
    return "\n".join(lines) + "\n"


# ---- 라쉬(1PL) 모형 ----

def _sigmoid(x):
    return 1 / (1 + math.exp(-x)) if x > -35 else 0.0


def rasch(rows, n_iter=500, lr=0.5, ridge=0.1):
    """정답 확률 = σ(θ_모델 − b_문항). 결합 최대우도 + 작은 릿지 벌점(완전분리 문항이 무한대로 가지 않게).

    점수는 0~1 사이 값을 그대로 쓴다(반복 실행 평균이어도 된다).
    모든 모델이 맞히거나 모두 틀린 문항은 난도를 정할 정보가 없으므로 따로 센다.
    난도 b의 평균을 0으로 맞춘다(척도의 원점).
    """
    score = defaultdict(dict)
    for r in rows:
        score[r["item_id"]].setdefault(r["model"], []).append(r["score"])
    resp = {i: {m: sum(v) / len(v) for m, v in by.items()} for i, by in score.items()}
    models = sorted({m for by in resp.values() for m in by})
    informative = {i: by for i, by in resp.items() if len(by) >= 2 and 0 < sum(by.values()) < len(by)
                   and len(set(by.values())) > 1}
    all_right = sorted(i for i, by in resp.items() if all(v == 1 for v in by.values()))
    all_wrong = sorted(i for i, by in resp.items() if all(v == 0 for v in by.values()))
    theta = {m: 0.0 for m in models}
    b = {i: 0.0 for i in informative}
    for _ in range(n_iter):
        gt, gb = defaultdict(float), defaultdict(float)
        for i, by in informative.items():
            for m, y in by.items():
                e = y - _sigmoid(theta[m] - b[i])
                gt[m] += e
                gb[i] -= e
        for m in models:
            theta[m] += lr * (gt[m] - ridge * theta[m]) / max(1, len(informative))
        for i in b:
            b[i] += lr * (gb[i] - ridge * b[i])
        if b:
            c = sum(b.values()) / len(b)
            for i in b:
                b[i] -= c
            for m in models:
                theta[m] -= c
    # 문항 정보량: 2PL에서 a=1이면 Σ p(1−p). 클수록 이 모델들을 잘 가른다
    info = {i: sum(_sigmoid(theta[m] - b[i]) * (1 - _sigmoid(theta[m] - b[i])) for m in informative[i]) for i in b}
    return {"models": models, "theta": theta, "b": b, "info": info,
            "n_items": len(resp), "n_informative": len(informative), "all_right": all_right, "all_wrong": all_wrong}


def render_rasch(res, items):
    lines = ["# 문항 반응 분석 (라쉬 1PL)", "",
             "정답 확률 = σ(θ − b). θ는 모델 실력, b는 문항 난도다. b의 평균을 0으로 맞췄다.", ""]
    if len(res["models"]) < MIN_MODELS_IRT:
        lines += [f"> 주의: 모델이 {len(res['models'])}개다. {MIN_MODELS_IRT}개보다 적으면 문항 난도 b가 불안정하다. "
                  "아래 값은 방향을 보는 참고용이고, 기존 단별 정답률(calibration.md)을 대체하지 않는다.", ""]
    lines += [f"문항 {res['n_items']}개 중 난도를 정할 수 있는 문항 {res['n_informative']}개. "
              f"모든 모델이 맞힌 문항 {len(res['all_right'])}개, 모두 틀린 문항 {len(res['all_wrong'])}개는 정보가 없다.", "",
              "## 모델 실력 θ", "", "| 모델 | θ |", "|---|---|"]
    lines += [f"| {m} | {res['theta'][m]:+.2f} |" for m in sorted(res["models"], key=lambda m: -res["theta"][m])]
    by_cell = defaultdict(list)
    for i, bi in res["b"].items():
        it = items.get(i, {})
        meta = it.get("meta", {})
        by_cell[(it.get("author", "?"), meta.get("level", it.get("difficulty")), meta.get("variant", "-"))].append((bi, res["info"][i]))
    if by_cell:
        lines += ["", "## 유형별 평균 난도", "", "정보량이 클수록 지금 모델들을 잘 가르는 유형이다. 다음 생성 때 이 유형을 늘린다.", "",
                  "| 생성기 | 단 | 변형 | 문항 수 | 평균 b | 평균 정보량 |", "|---|---|---|---|---|---|"]
        for (author, level, variant), v in sorted(by_cell.items(), key=lambda kv: -sum(x[1] for x in kv[1]) / len(kv[1])):
            lines.append(f"| {author} | {level} | {variant} | {len(v)} | {sum(x[0] for x in v) / len(v):+.2f} "
                         f"| {sum(x[1] for x in v) / len(v):.2f} |")
    lines += ["", "다음 단계: 같은 문항을 모델마다 여러 번 돌려 정답률을 0~1 값으로 넣으면, 모두 맞히거나 모두 틀린 문항에서도 정보가 생긴다.", ""]
    return "\n".join(lines)
