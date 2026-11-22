"""남이 따라 하기 어려운 부분을 쌓는 도구: 난도 보정, 비공개 세트, 선점 증명.

코드는 누구나 베낄 수 있다. 베낄 수 없는 것은 세 가지다.
  1. 어느 난도에서 어느 모델이 틀리는지에 대한 실측 기록 (calibrate)
  2. 공개하지 않은 문항 (publish의 비공개 세트)
  3. 그 문항과 실패 기록이 언제부터 있었는지에 대한 증거 (publish의 해시 목록)
"""
import hashlib
import json
import uuid
from collections import defaultdict
from pathlib import Path

EASY, BROKEN = 0.95, 0.20   # 모델 평균 정답률이 이 위면 너무 쉬움, 이 아래면 문항부터 의심


def calibrate(items, grades):
    """(생성기, 난도)별 정답률. rows와 사람이 읽을 보고서를 돌려준다."""
    cell = defaultdict(lambda: defaultdict(list))
    for g in grades:
        it = items.get(g["item_id"])
        if it is None:
            continue
        key = (it["author"], it.get("meta", {}).get("level", it.get("difficulty")))
        cell[key][g["model"]].append(g["score"])
    models = sorted({m for c in cell.values() for m in c})
    rows = []
    for (author, level), by in sorted(cell.items(), key=lambda kv: (kv[0][0], kv[0][1] or 0)):
        per = {m: sum(v) / len(v) for m, v in by.items()}
        mean = sum(per.values()) / len(per)
        verdict = ("너무 쉬움: 빼거나 난도를 올린다" if mean >= EASY else
                   "거의 다 틀림: 문항·정답부터 확인한다" if mean < BROKEN else "쓸 만함: 이 단을 늘린다")
        rows.append({"author": author, "level": level, "n": max(len(v) for v in by.values()),
                     "mean": mean, "per_model": per, "spread": max(per.values()) - min(per.values()), "verdict": verdict})
    lines = ["# 난도 보정", "", "생성기와 난도 단별 정답률이다. 모델을 가르는 문항은 정답률이 중간이고 모델 간 차이가 큰 단에 있다.", "",
             "| 생성기 | 난도 | 문항 수 | 평균 정답률 | 모델 간 차이 | " + " | ".join(models) + " | 판정 |",
             "|---|---|---|---|---|" + "---|" * len(models) + "---|"]
    for r in rows:
        lines.append(f"| {r['author']} | {r['level']} | {r['n']} | {r['mean']:.0%} | {r['spread']:.0%} | "
                     + " | ".join(f"{r['per_model'].get(m, float('nan')):.0%}" for m in models) + f" | {r['verdict']} |")
    inj = defaultdict(lambda: defaultdict(list))   # 숨은 지시문은 문구·위치별로도 본다
    for g in grades:
        info = items.get(g["item_id"], {}).get("meta", {}).get("injection")
        if info:
            inj[("문구", info["template"])][g["model"]].append(g["score"])
            inj[("위치", info["position"])][g["model"]].append(g["score"])
    if inj:
        lines += ["", "## 숨은 지시문 유형별 정답률", "", "정답률이 낮을수록 그 수법에 잘 넘어간다는 뜻이다.", "",
                  "| 구분 | 유형 | 문항 수 | " + " | ".join(models) + " |", "|---|---|---|" + "---|" * len(models)]
        for (kind, name), by in sorted(inj.items()):
            lines.append(f"| {kind} | {name} | {max(len(v) for v in by.values())} | "
                         + " | ".join(f"{sum(by[m]) / len(by[m]):.0%}" if by.get(m) else "-" for m in models) + " |")
    keep = [f"{r['author']} {r['level']}단" for r in rows if BROKEN <= r["mean"] < EASY]
    lines += ["", "다음에 늘릴 단: " + (", ".join(keep) if keep else "없음. 모든 단이 너무 쉽거나 거의 다 틀린다."), ""]
    return rows, "\n".join(lines) + "\n"


def cluster_interval(pairs, n_boot=2000, seed=20261122):
    """(묶음, 점수) 목록에서 평균의 95% 구간(100점 척도). 묶음 단위로 복원추출한다."""
    import random
    groups = defaultdict(list)
    for g, s in pairs:
        groups[g].append(s)
    keys = sorted(groups, key=str)
    if not keys:
        return float("nan"), float("nan")
    rng, means = random.Random(seed), []
    for _ in range(n_boot):
        tot = cnt = 0
        for k in (rng.choice(keys) for _ in keys):
            tot += sum(groups[k]); cnt += len(groups[k])
        means.append(100 * tot / cnt)
    means.sort()
    return means[int(0.025 * n_boot)], means[int(0.975 * n_boot) - 1]


def _secret(path, make):
    path = Path(path)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(make(), encoding="utf-8")
    return path.read_text(encoding="utf-8").strip()


def publish(items, data_dir, out_dir, private_rate, seed):
    """승인된 문항을 공개 세트와 비공개 세트로 나누고, 공개분과 해시 목록을 out_dir에 쓴다.

    - 나누는 기준은 (seed, 공시 묶음 또는 문항 id)의 해시라 문항이 늘어도 기존 문항의 소속은 바뀌지 않는다.
    - 해시 목록에는 비공개 문항도 들어간다. 내용은 드러나지 않지만, 나중에 소금값과 문항을 공개하면
      그 문항이 이 시점에 이미 있었음을 증명할 수 있다.
    - 공개분에는 카나리 문자열을 넣는다. 어떤 모델이 이 문자열을 외우고 있으면 공개분이 학습에 쓰인 것이다.
    """
    data_dir, out_dir = Path(data_dir), Path(out_dir)
    salt = _secret(data_dir / "private_salt.txt", lambda: uuid.uuid4().hex + uuid.uuid4().hex)
    canary = _secret(data_dir / "canary.txt", lambda: f"kfin-eval-canary:{uuid.uuid4()}")
    public, manifest = [], []
    for it in sorted(items, key=lambda i: i["id"]):
        unit = it.get("meta", {}).get("group") or it["id"]   # 같은 공시의 문항은 통째로 한쪽에 둔다(본문이 같아서 일부만 공개하면 나머지가 샌다)
        frac = int(hashlib.sha256(f"{seed}|{unit}".encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
        split = "private" if frac < private_rate else "public"
        body = json.dumps(it, ensure_ascii=False, sort_keys=True)
        manifest.append({"id": it["id"], "split": split, "commit": hashlib.sha256((salt + body).encode()).hexdigest()})
        if split == "public":
            public.append(dict(it, canary=canary))
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "public.jsonl").write_text("".join(json.dumps(p, ensure_ascii=False, sort_keys=True) + "\n" for p in public), encoding="utf-8")
    (out_dir / "MANIFEST.json").write_text(json.dumps({"canary": canary, "items": manifest}, ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / "NOTICE.md").write_text(
        "# 공개 세트 안내\n\n이 문항은 AI 모델 평가용이다. 모델 학습 데이터로 쓰지 말 것.\n"
        f"학습 데이터 오염 탐지용 문자열: `{canary}`\n\n"
        "MANIFEST.json에는 비공개 문항의 해시도 들어 있다. 문항 내용은 해시에서 복원할 수 없다.\n", encoding="utf-8")
    return {"public": len(public), "private": len(manifest) - len(public), "canary": canary}


def verify_commit(item, salt, commit):
    """나중에 비공개 문항을 공개할 때: 이 문항이 해시 목록의 그 문항인지 확인한다."""
    body = json.dumps(item, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256((salt + body).encode()).hexdigest() == commit
