"""점수표 쪼개 보기와 수신자별 보고서.

BCBS 239 원칙 6(적응성): 모은 결과에서 분야·난도·형식·변형·오류 유형별로 세부를 꺼내 볼 수 있어야 한다.
BCBS 239 원칙 9(명확성·유용성): 같은 결과라도 받는 사람에 맞춰 내용을 고른다.
  cto  : 어떤 모델을 쓸지 정하는 사람. 순위, 차이 구간, 분야별 최고 모델, 피해야 할 칸
  risk : 그 모델의 위험을 관리하는 사람. 약한 칸, 오류 유형, 실제 틀린 문항, 이 결과로 말할 수 없는 것
"""
from collections import defaultdict

from .failures import ERROR_TYPES, latest_annotations

DIMS = {
    "domain": ("분야", lambda it: it.get("domain", "?")),
    "difficulty": ("난도", lambda it: f"{it.get('difficulty', '?')}단"),
    "answer_type": ("답 형식", lambda it: it.get("answer_type", "?")),
    "variant": ("변형", lambda it: (it.get("meta") or {}).get("variant") or "-"),
}
MIN_N = 5          # 이보다 문항이 적은 칸은 '표본 적음'으로 표시한다
WEAK = 90.0        # 이 점수 미만인 칸을 약한 칸으로 본다


def _avg(xs):
    return 100 * sum(xs) / len(xs)


def cells(grades, items, dim):
    """{model: {값: [점수...]}}"""
    _, key = DIMS[dim]
    out = defaultdict(lambda: defaultdict(list))
    for g in grades:
        it = items.get(g["item_id"], {"domain": g.get("domain"), "answer_type": g.get("answer_type")})
        out[g["model"]][key(it)].append(g["score"])
    return out


def error_table(failures, annotations, run_id=None):
    """{model: {오류 유형 이름: 건수}}. 분류 안 된 실패는 '미분류'."""
    ann = latest_annotations(annotations)
    out = defaultdict(lambda: defaultdict(int))
    for f in failures:
        if run_id and f.get("run_id") != run_id:
            continue
        for t in set(ann.get(f["id"], {}).values()) or {"미분류"}:
            out[f["model"]][ERROR_TYPES.get(t, t)] += 1
    return out


def _fmt(xs):
    if not xs:
        return "-"
    s = f"{_avg(xs):.1f} ({len(xs)})"
    return s + "*" if len(xs) < MIN_N else s


def render_drill(run_id, grades, items, failures, annotations, dims=tuple(DIMS)):
    models = sorted({g["model"] for g in grades})
    lines = [f"# 쪼개 본 점수표 ({run_id})", "",
             f"100점 만점 평균, 괄호는 문항 수. `*`는 문항 {MIN_N}개 미만이라 칸 사이 비교가 어려운 칸이다.", ""]
    for dim in dims:
        name, _ = DIMS[dim]
        c = cells(grades, items, dim)
        vals = sorted({v for m in c for v in c[m]})
        if len(vals) <= 1 and dim != "domain":
            continue
        lines += [f"## {name}별", "", "| 모델 | " + " | ".join(vals) + " |", "|---|" + "---|" * len(vals)]
        for m in models:
            lines.append(f"| {m} | " + " | ".join(_fmt(c[m].get(v, [])) for v in vals) + " |")
        lines.append("")
    et = error_table(failures, annotations, run_id)
    if et:
        types = sorted({t for m in et for t in et[m]})
        lines += ["## 오류 유형별 (틀린 응답 건수)", "", "| 모델 | " + " | ".join(types) + " |", "|---|" + "---|" * len(types)]
        for m in models:
            lines.append(f"| {m} | " + " | ".join(str(et.get(m, {}).get(t, 0)) for t in types) + " |")
        lines += ["", "오류 유형은 `failures` → `annotate`로 붙인다. 미분류가 많으면 아직 사람이 보지 않은 것이다.", ""]
    else:
        lines += ["## 오류 유형별", "", "이 실행의 실패 사례가 없다. `failures --run-id`로 먼저 모은다.", ""]
    return "\n".join(lines) + "\n"


def weak_cells(grades, items, dims=("domain", "difficulty", "variant")):
    """[(점수, 모델, 차원 이름, 값, n)] 약한 칸. 표본 적은 칸은 빼지 않고 n으로 보여 준다."""
    out = []
    for dim in dims:
        name, _ = DIMS[dim]
        for m, row in cells(grades, items, dim).items():
            for v, xs in row.items():
                if xs and v != "-" and _avg(xs) < WEAK:
                    out.append((_avg(xs), m, name, v, len(xs)))
    return sorted(out)


def render_cto(run_id, grades, items, pairwise_text=""):
    models = defaultdict(list)
    for g in grades:
        models[g["model"]].append(g["score"])
    rank = sorted(models, key=lambda m: -_avg(models[m]))
    lines = [f"# 모델 선택용 요약 ({run_id})", "", "받는 사람: 어떤 모델을 쓸지 정하는 사람.", "",
             "## 순위", "", "| 순위 | 모델 | 평균 | 문항 |", "|---|---|---|---|"]
    lines += [f"| {i} | {m} | {_avg(models[m]):.1f} | {len(models[m])} |" for i, m in enumerate(rank, 1)]
    lines += ["", "순위만으로 고르지 않는다. 차이가 우연인지는 아래 모델 쌍 비교로 본다.", ""]
    dom = cells(grades, items, "domain")
    lines += ["## 분야별 최고 모델", "", "| 분야 | 최고 | 점수 |", "|---|---|---|"]
    for d in sorted({v for m in dom for v in dom[m]}):
        best = max(dom, key=lambda m: _avg(dom[m][d]) if dom[m].get(d) else -1)
        lines.append(f"| {d} | {best} | {_fmt(dom[best][d])} |")
    weak = weak_cells(grades, items)
    lines += ["", f"## 피해야 할 칸 ({WEAK:.0f}점 미만)", ""]
    lines += [f"- {m}: {name} {v} {s:.1f}점 ({n}문항)" for s, m, name, v, n in weak[:10]] or ["- 없음"]
    if pairwise_text:
        lines += ["", pairwise_text.strip()]
    return "\n".join(lines) + "\n"


def render_risk(run_id, grades, items, failures, annotations, n_reviewers=0):
    lines = [f"# 위험 관리용 보고서 ({run_id})", "", "받는 사람: 이 모델을 쓰는 업무의 위험을 관리하는 사람.", ""]
    weak = weak_cells(grades, items)
    lines += [f"## 약한 칸 ({WEAK:.0f}점 미만)", ""]
    lines += [f"- {m}: {name} {v} {s:.1f}점 ({n}문항{', 표본 적음' if n < MIN_N else ''})" for s, m, name, v, n in weak] or ["- 없음"]
    et = error_table(failures, annotations, run_id)
    lines += ["", "## 오류 유형", ""]
    if et:
        lines += [f"- {m}: " + ", ".join(f"{t} {n}건" for t, n in sorted(et[m].items(), key=lambda x: -x[1])) for m in sorted(et)]
    else:
        lines.append("- 수집된 실패 사례 없음(`failures --run-id`)")
    wrong = [g for g in grades if g["score"] < 1]
    lines += ["", f"## 틀린 응답 ({len(wrong)}건, 앞 20건)", "", "| 모델 | 문항 | 분야 | 난도 | 점수 |", "|---|---|---|---|---|"]
    for g in sorted(wrong, key=lambda g: (g["model"], g["item_id"]))[:20]:
        it = items.get(g["item_id"], {})
        lines.append(f"| {g['model']} | {g['item_id']} | {it.get('domain', g.get('domain'))} | {it.get('difficulty', '?')} | {100 * g['score']:.0f} |")
    n_items = len({g["item_id"] for g in grades})
    lines += ["", "## 이 결과로 말할 수 없는 것", "",
              f"- 문항 {n_items}개, 문항마다 한 번씩 물은 결과다. 칸별 표본이 작다.",
              f"- 사람 검수자 {n_reviewers}명. " + ("문항과 정답지가 독립 검수를 거치지 않았다." if n_reviewers < 2 else ""),
              "- 문항에 없는 업무(실무 판단, 실제 고객 대응)의 위험은 이 점수로 알 수 없다."]
    return "\n".join(lines) + "\n"
