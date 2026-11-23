"""명령줄 진입점: python -m kfin_eval <명령>"""
import argparse
import datetime
import json
from collections import defaultdict
from pathlib import Path

from . import env as E
from . import failures as F
from . import gen as GEN
from . import grade as G
from . import guardlink as GL
from . import moat as MO
from . import probe as P
from . import score as S
from . import stats as ST
from . import store
from .models import expand, get_model, judge_conflicts
from .schema import content_hash, load_items, validate_all


class Paths:
    def __init__(self, root):
        r = Path(root)
        self.items, self.reviews = r / "data" / "items", r / "data" / "reviews.jsonl"
        self.log, self.runs = r / "data" / "provenance.jsonl", r / "runs"
        self.failures, self.fail_ann = r / "data" / "failures.jsonl", r / "data" / "failure_annotations.jsonl"
        self.envs, self.fail_report = r / "data" / "envs", r / "data" / "failure_report.md"
        self.probes, self.reviewer_scores = r / "data" / "probes", r / "data" / "reviewer_scores.jsonl"
        self.score_report = r / "data" / "contribution_scores.md"
        self.data, self.dist, self.root = r / "data", r / "dist", r

    def status(self, items):
        """검수 상태. 점검에서 신뢰 미달로 나온 검토자의 판정은 뺀다."""
        return store.review_status(items, store.read_jsonl(self.reviews), P.untrusted(store.read_jsonl(self.reviewer_scores)))


def cmd_validate(p, a):
    res = validate_all(load_items(p.items))
    n_err = 0
    for iid, (err, warn) in res.items():
        for e in err:
            print(f"[오류] {iid}: {e}")
        for w in warn:
            print(f"[경고] {iid}: {w}")
        n_err += bool(err)
    print(f"문항 {len(res)}개 중 오류 {n_err}개")
    return 1 if n_err else 0


def cmd_review(p, a):
    items = {i["id"]: i for i in load_items(p.items)}
    if a.item not in items:
        raise SystemExit(f"문항 없음: {a.item}")
    try:
        row = store.add_review(p.reviews, items[a.item], a.reviewer, a.verdict, a.note)
    except ValueError as e:
        raise SystemExit(str(e))
    store.log_event(p.log, "review", **{k: row[k] for k in ("item_id", "item_hash", "reviewer", "verdict")})
    print(f"기록됨: {a.item} {a.verdict} by {a.reviewer}")
    return 0


def cmd_status(p, a):
    items = load_items(p.items)
    st = p.status(items)
    for it in items:
        s = st[it["id"]]
        how = "엔진 계산" if s["by"] == "code" else f"승인 {s['approvals']} 반려 {s['rejects']}"
        print(f"{it['id']:<18} {s['status']:<9} {how}  [{it['domain']}/{it['answer_type']}]")
    cnt = defaultdict(int)
    for s in st.values():
        cnt[s["status"]] += 1
    print(dict(cnt))
    return 0


def _eligible(p, include_draft):
    items = load_items(p.items)
    res = validate_all(items)
    st = p.status(items)
    ok = [i for i in items if not res[i["id"]][0]]
    return ok if include_draft else [i for i in ok if st[i["id"]]["status"] == "approved"]


def cmd_run(p, a):
    items = _eligible(p, a.include_draft)
    if getattr(a, "authors", None):   # 일부 생성기의 문항만 돌린다. 이미 돌린 문항에 돈을 두 번 쓰지 않기 위해서다
        want = {x.strip() for x in a.authors.split(",")}
        items = [i for i in items if i["author"] in want]
    if not items:
        raise SystemExit("실행할 문항이 없습니다. 검수 승인 2건이 필요합니다(시험 삼아 돌리려면 --include-draft).")
    run_id = a.run_id or datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    out = p.runs / run_id / "responses.jsonl"
    if out.exists():
        raise SystemExit(f"이미 있는 run-id: {run_id}")
    for name in expand(a.models):
        model = get_model(name)
        for it in items:
            store.append_jsonl(out, {"model": model.name, "item_id": it["id"],
                                     "item_hash": content_hash(it), "response": model.answer(it)})
        print(f"{model.name}: {len(items)}문항 응답 완료")
    store.log_event(p.log, "run", run_id=run_id, models=a.models, include_draft=a.include_draft,
                    items={i["id"]: content_hash(i) for i in items})
    print(f"run-id: {run_id}")
    return 0


def cmd_grade(p, a):
    d = p.runs / a.run_id
    items = {i["id"]: i for i in load_items(p.items)}
    judge = get_model(a.judge) if a.judge else None
    responses = store.read_jsonl(d / "responses.jsonl")
    same = judge_conflicts(a.judge, {r["model"] for r in responses})
    if same and any(items.get(r["item_id"], {}).get("answer_type") == "rubric" for r in responses):
        print(f"[경고] 채점 모델 {a.judge}와 같은 계열의 피평가 모델: {', '.join(same)}. "
              "채점 모델은 자신과 관련된 모델의 답에 점수를 더 주는 편향이 보고돼 있습니다. 다른 회사 모델을 채점자로 쓰세요.")
    out = d / "grades.jsonl"
    out.unlink(missing_ok=True)
    n = 0
    for r in responses:
        it = items.get(r["item_id"])
        if it is None or content_hash(it) != r["item_hash"]:
            print(f"[건너뜀] {r['item_id']}: 응답 이후 문항이 바뀜")
            continue
        score, detail = G.grade(it, r["response"], judge)
        store.append_jsonl(out, {"model": r["model"], "item_id": it["id"], "domain": it["domain"],
                                 "answer_type": it["answer_type"], "score": score, "detail": detail})
        n += 1
    store.log_event(p.log, "grade", run_id=a.run_id, judge=a.judge or "keywords", graded=n, judge_same_family=same)
    print(f"{n}건 채점 완료")
    return 0


def cmd_report(p, a):
    d = p.runs / a.run_id
    rows = store.read_jsonl(d / "grades.jsonl")
    if not rows:
        raise SystemExit("채점 결과가 없습니다. 먼저 grade를 실행하세요.")
    by = defaultdict(lambda: defaultdict(list))
    for r in rows:
        by[r["model"]]["전체"].append(r["score"])
        by[r["model"]][r["domain"]].append(r["score"])
    cols = ["전체"] + sorted({r["domain"] for r in rows})
    # 같은 공시에서 나온 문항은 서로 독립이 아니다. 구간은 공시(meta.group) 단위로 다시 뽑아 계산한다.
    group_of = {i["id"]: i.get("meta", {}).get("group") or i["id"] for i in load_items(p.items)}
    lines = [f"# 점수표 ({a.run_id})", "", "100점 만점 평균. 괄호 안은 문항 수. 95% 구간은 같은 공시의 문항을 한 묶음으로 보고 계산했다.", "",
             "| 모델 | 전체 95% 구간 | " + " | ".join(cols) + " |", "|---|---|" + "---|" * len(cols)]
    avg = lambda xs: 100 * sum(xs) / len(xs)
    for m in sorted(by, key=lambda m: -avg(by[m]["전체"])):
        cells = [f"{avg(by[m][c]):.1f} ({len(by[m][c])})" if by[m][c] else "-" for c in cols]
        lo, hi = MO.cluster_interval([(group_of.get(r["item_id"], r["item_id"]), r["score"]) for r in rows if r["model"] == m])
        lines.append(f"| {m} | {lo:.1f} ~ {hi:.1f} | " + " | ".join(cells) + " |")
    lines += ["", "모델별 구간이다. 두 모델의 우열은 아래 '모델 쌍 비교'의 차이 구간으로 판단한다."]
    text = "\n".join(lines) + "\n"
    if len(by) >= 2:
        text += "\n" + ST.render_pairwise(ST.pairwise(rows, group_of))
    (d / "scoreboard.md").write_text(text, encoding="utf-8")
    print(text)
    return 0


def cmd_failures(p, a):
    items = {i["id"]: i for i in load_items(p.items)}
    n = F.collect(p.runs / a.run_id, a.run_id, items, p.failures, a.threshold)
    store.log_event(p.log, "failures", run_id=a.run_id, added=n)
    print(f"실패 사례 {n}건 추가 (누적 {len(store.read_jsonl(p.failures))}건) → {p.failures}")
    return 0


def cmd_annotate(p, a):
    try:
        F.annotate(p.fail_ann, store.read_jsonl(p.failures), a.failure, a.annotator, a.type, a.note)
    except ValueError as e:
        raise SystemExit(str(e))
    store.log_event(p.log, "annotate", failure_id=a.failure, annotator=a.annotator, error_type=a.type)
    print(f"분류됨: {a.failure} → {F.ERROR_TYPES[a.type]}")
    return 0


def cmd_failure_report(p, a):
    grades = [g for f in sorted(p.runs.glob("*/grades.jsonl")) for g in store.read_jsonl(f)]
    text = F.report(store.read_jsonl(p.failures), store.read_jsonl(p.fail_ann), grades)
    p.fail_report.write_text(text, encoding="utf-8")
    print(text)
    return 0


def cmd_env_run(p, a):
    f = p.envs / f"{a.scenario}.json"
    if not f.exists():
        raise SystemExit(f"시나리오 없음: {f}")
    sc = json.loads(f.read_text(encoding="utf-8"))
    run_id = a.run_id or datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    out = p.runs / run_id / "env_traces.jsonl"
    for name in a.agents.split(","):
        name = name.strip()
        agent = E.mock_agent(name, sc) if name.startswith("mock-") else E.LLMAgent(get_model(name))
        ep = E.run_episode(sc, agent)
        store.append_jsonl(out, ep)
        print(f"{name}: {100 * ep['score']:.0f}점 ({len(ep['trace'])}단계)")
        for c in ep["checks"]:
            print(f"   {'O' if c['ok'] else 'X'} {c['check']}")
    store.log_event(p.log, "env_run", run_id=run_id, scenario=a.scenario, agents=a.agents)
    print(f"기록: {out}")
    return 0


def cmd_gen(p, a):
    if a.source == "dart":
        if not a.file:
            raise SystemExit("--file 에 Collatio의 data/labels/disclosures.csv 경로를 주세요.")
        out = p.items / f"gen_dart_{Path(a.file).stem}.jsonl"
    else:
        out = p.items / f"gen_{a.source}_s{a.seed}.jsonl"
    if out.exists():
        raise SystemExit(f"이미 있음: {out} (다른 --seed를 쓰거나 파일을 지우세요)")
    gens = {**GEN.GENERATORS, **GEN.load_plugins(p.root)}
    if a.source != "dart" and a.source not in gens:
        raise SystemExit(f"없는 생성기: {a.source}. 쓸 수 있는 것: dart, {', '.join(sorted(gens))}")
    items = GEN.dart_items(a.file) if a.source == "dart" else gens[a.source](a.n, a.seed)
    if not items:
        raise SystemExit("만들 수 있는 문항이 없습니다.")
    for it in items:
        store.append_jsonl(out, it)
    store.log_event(p.log, "gen", source=a.source, n=len(items), seed=a.seed, items={i["id"]: content_hash(i) for i in items})
    print(f"{len(items)}문항 생성 → {out}")
    return 0


def cmd_guard_check(p, a):
    d = p.runs / a.run_id
    items = {i["id"]: i for i in load_items(p.items)}
    res = GL.check(items, store.read_jsonl(d / "responses.jsonl"), a.threshold)
    probe = GL.check_probe(items, store.read_jsonl(d / "responses.jsonl"), a.threshold)
    text = GL.render(res, items) + "\n" + GL.render_probe(probe)
    (d / "guard_check.md").write_text(text, encoding="utf-8")
    for r in res["rows"]:
        store.append_jsonl(d / "guard_rows.jsonl", r)
    s = res["summary"]
    store.log_event(p.log, "guard_check", run_id=a.run_id, threshold=s["threshold"], n_wrong=s["n_wrong"], n_items=s["n_items"])
    print(text)
    return 0


def cmd_pipeline(p, a):
    """검사 → 실행 → 채점 → 실패 수집 → 점수표 → 가드 점검을 한 번에."""
    ns = argparse.Namespace
    if cmd_validate(p, ns()):
        raise SystemExit("문항 오류부터 고치세요.")
    run_id = a.run_id or datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    cmd_run(p, ns(models=a.models, include_draft=a.include_draft, run_id=run_id, authors=a.authors))
    cmd_grade(p, ns(run_id=run_id, judge=a.judge))
    cmd_failures(p, ns(run_id=run_id, threshold=1.0))
    cmd_report(p, ns(run_id=run_id))
    engine = {i["id"] for i in load_items(p.items) if i.get("answer_source") == "engine"}
    if any(g["item_id"] in engine for g in store.read_jsonl(p.runs / run_id / "grades.jsonl")):
        cmd_calibrate(p, ns(run_id=run_id))
    if len(expand(a.models)) < 2:
        print("모델이 1개라 가드 점검은 건너뜀")
    else:
        cmd_guard_check(p, ns(run_id=run_id, threshold=None))
    print(f"결과 폴더: {p.runs / run_id}")
    return 0


def cmd_probe_make(p, a):
    items = {i["id"]: i for i in _eligible(p, True)}
    batch, tasks, key = P.make(items, store.read_jsonl(p.failures), a.reviewer, a.n, a.wrong_rate, a.seed)
    sheet, _ = P.write_batch(p.probes, batch, a.reviewer, tasks, key)
    n_wrong = sum(c["truth"] == "wrong" for c in key)
    store.log_event(p.log, "probe_make", batch=batch, reviewer=a.reviewer, n=len(tasks), n_wrong=n_wrong)
    print(f"검토 묶음 {len(tasks)}건(그중 심은 오답 {n_wrong}건) → {sheet}")
    print("이 CSV만 검토자에게 보내세요. 같은 폴더의 .key.jsonl은 정답이라 보내면 안 됩니다.")
    return 0


def cmd_probe_score(p, a):
    sheet = Path(a.file) if a.file else p.probes / f"{a.batch}.csv"
    res = P.score_batch(sheet, p.probes / f"{a.batch}.key.jsonl")
    store.append_jsonl(p.reviewer_scores, dict(res, batch=a.batch))
    store.log_event(p.log, "probe_score", batch=a.batch, reviewer=res["reviewer"], n_wrong=res["n_wrong"], caught=res["caught"])
    rate = lambda x, n: f"{100 * x / n:.0f}%" if n else "해당 없음"
    print(f"{res['reviewer']}: 심은 오답 {res['n_wrong']}건 중 {res['caught']}건 포착 ({rate(res['caught'], res['n_wrong'])}), "
          f"정답 {res['n_right']}건 중 {res['false_reject']}건을 틀렸다고 함 ({rate(res['false_reject'], res['n_right'])}), 미응답 {res['unanswered']}건")
    if res["missed_items"]:
        print("놓친 문항:", ", ".join(res["missed_items"]))
    if res["reviewer"] in P.untrusted(store.read_jsonl(p.reviewer_scores)):
        print(f"누적 포착률이 {P.MIN_CATCH:.0%} 미만입니다. 이 검토자의 승인·반려는 문항 상태에 반영하지 않습니다.")
    return 0


def cmd_score(p, a):
    items = load_items(p.items)
    files = [p.runs / a.run_id / "grades.jsonl"] if a.run_id else sorted(p.runs.glob("*/grades.jsonl"))
    grades = [g for f in files for g in store.read_jsonl(f) if not (a.real_only and g["model"].startswith("mock-"))]
    rs = store.read_jsonl(p.reviewer_scores)
    rows = S.adjust(S.item_rows(items, p.status(items), grades, store.read_jsonl(p.failures), store.read_jsonl(p.fail_ann)))
    text = S.render(rows, S.people(rows, rs), P.untrusted(rs))
    p.score_report.write_text(text, encoding="utf-8")
    print(text)
    return 0


def cmd_calibrate(p, a):
    d = p.runs / a.run_id
    items = {i["id"]: i for i in load_items(p.items)}
    grades = [g for g in store.read_jsonl(d / "grades.jsonl") if items.get(g["item_id"], {}).get("answer_source") == "engine"]
    if not grades:
        raise SystemExit("엔진 생성 문항의 채점 결과가 없습니다.")
    rows, text = MO.calibrate(items, grades)
    (d / "calibration.md").write_text(text, encoding="utf-8")
    store.log_event(p.log, "calibrate", run_id=a.run_id, cells=[[r["author"], r["level"], round(r["mean"], 3)] for r in rows])
    print(text)
    return 0


def cmd_irt(p, a):
    d = p.runs / a.run_id
    rows = store.read_jsonl(d / "grades.jsonl")
    if not rows:
        raise SystemExit("채점 결과가 없습니다. 먼저 grade를 실행하세요.")
    items = {i["id"]: i for i in load_items(p.items)}
    res = ST.rasch(rows)
    text = ST.render_rasch(res, items)
    (d / "irt.md").write_text(text, encoding="utf-8")
    store.log_event(p.log, "irt", run_id=a.run_id, n_informative=res["n_informative"],
                    theta={m: round(v, 3) for m, v in res["theta"].items()})
    print(text)
    return 0


def cmd_publish(p, a):
    items = _eligible(p, False)
    if not items:
        raise SystemExit("승인된 문항이 없습니다.")
    res = MO.publish(items, p.data, p.dist, a.private_rate, a.seed)
    store.log_event(p.log, "publish", public=res["public"], private=res["private"], seed=a.seed, private_rate=a.private_rate)
    print(f"공개 {res['public']}문항, 비공개 {res['private']}문항 → {p.dist}")
    print("dist 폴더만 공개하세요. data/private_salt.txt 와 비공개 문항은 공개하면 안 됩니다.")
    return 0


def cmd_probe_report(p, a):
    rs = store.read_jsonl(p.reviewer_scores)
    if not rs:
        raise SystemExit("채점된 검토 묶음이 없습니다.")
    pct = lambda x, n: f"{100 * x / n:.0f}%" if n else "-"
    print("| 심은 오답 비율 | 묶음 수 | 심은 오답 | 포착률 | 정답을 틀렸다고 한 비율 |\n|---|---|---|---|---|")
    for rate, v in sorted(P.by_rate(rs).items(), key=lambda kv: (kv[0] is None, kv[0] or 0)):
        print(f"| {'미기록' if rate is None else f'{rate:.0%}'} | {v['batches']} | {v['n_wrong']} | {pct(v['caught'], v['n_wrong'])} | {pct(v['false_reject'], v['n_right'])} |")
    print("\n| 검토자 | 심은 오답 | 포착률(적중) | 오경보율 | 민감도 d′ | 판단 기준 c | 신뢰 |\n|---|---|---|---|---|---|---|")
    bad = P.untrusted(rs)
    for name, v in sorted(P.totals(rs).items()):
        t = P.sdt(v)
        lean = "틀림 쪽" if t["c"] < -0.25 else "맞음 쪽" if t["c"] > 0.25 else "중립"
        print(f"| {name} | {v['n_wrong']} | {pct(v['caught'], v['n_wrong'])} | {pct(v['false_reject'], v['n_right'])} "
              f"| {t['dprime']:.2f} | {t['c']:+.2f} ({lean}) | {'미달' if name in bad else '판정 전' if v['n_wrong'] < P.MIN_SEEDED else '충족'} |")
    print(f"\nd′ {P.MIN_DPRIME} 미만 또는 포착률 {P.MIN_CATCH:.0%} 미만이면 신뢰 미달. d′와 c는 각 칸에 0.5를 더해 계산했다(표본이 작을 때 0%·100% 보정).")
    tr = {k: v for k, v in P.trend(rs).items() if len(v) >= 2}
    if tr:
        print("\n묶음 순서별 d′ (떨어지면 습관적 승인이 생기는 신호)")
        for name, seq in sorted(tr.items()):
            print(f"- {name}: " + " → ".join(f"{x}" for _, x in seq))
    return 0


def cmd_ci_key(p, a):
    """엔진 생성기 정답지가 ci/answer_key.json과 같은지. 다르면 1. --update면 갱신."""
    from . import ci
    path = p.root / "ci" / "answer_key.json"
    key, skipped = ci.build_key(p.root)
    if a.update:
        path.parent.mkdir(parents=True, exist_ok=True)
        old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        old.update(key)                              # 이번에 못 돈 생성기의 기존 정답지는 지우지 않는다
        path.write_text(json.dumps(old, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print(f"정답지 갱신: {', '.join(f'{k} {len(v)}문항' for k, v in key.items())}" + (f" / 건너뜀: {skipped}" if skipped else ""))
        return 0
    if not path.exists():
        raise SystemExit("ci/answer_key.json이 없습니다. 먼저 ci-key --update")
    diff = ci.compare_key(json.loads(path.read_text(encoding="utf-8")), key)
    bad = {k: v for k, v in diff.items() if any(v.values())}
    lines = ["### kfin-eval 정답지 점검 — " + ("실패" if bad else "통과"), ""]
    for name, d in diff.items():
        n_all = len(key.get(name, {}))
        lines.append(f"- {name}: {n_all}문항, 정답이 바뀐 문항 {len(d['changed'])}, 없어진 문항 {len(d['missing'])}, 새 문항 {len(d['new'])}")
        if d["changed"]:
            lines.append(f"  - 바뀐 문항: {', '.join(d['changed'][:20])}{' …' if len(d['changed']) > 20 else ''}")
    if skipped:
        lines.append(f"- 건너뜀(비교 안 함): {', '.join(skipped)}")
    if bad:
        lines += ["", "엔진이 바뀌어 정답이 달라졌다. 의도한 변경이면 `python -m kfin_eval ci-key --update`로 갱신하고, "
                  "이 문항으로 예전에 돌린 실행(real3 등)은 같은 문항의 결과가 아님을 기록한다."]
    text = "\n".join(lines)
    print(text)
    ci.write_summary(text)
    return 1 if bad else 0


def cmd_ci_smoke(p, a):
    """고정 30문항 소규모 eval. 기준선(real2)보다 오답이 tolerance 넘게 늘거나 모든 모델이 함께 틀리면 1."""
    from . import ci
    names = expand(a.models)
    res, items, responses = ci.run_smoke(p.root, names, a.tolerance, out_dir=a.out)
    spec = ci.load_smoke(p.root)
    text = ci.smoke_markdown(res, len(items), [n.split(":", 1)[-1] for n in names], a.tolerance, spec["source"])
    if len(names) >= 2 and not a.no_guard:
        try:
            g = ci.guard_on_smoke(items, responses)
            rec = g["any_recall"]
            text += (f"\n\n가드(Collatio G1) 점검: 검토로 넘긴 비율 {g['review_rate']:.0%}, "
                     f"모델 하나라도 틀린 문항 {g['n_any_wrong']}개"
                     + ("" if rec != rec else f", 그중 가드가 넘긴 비율 {rec:.0%}"))
        except SystemExit as e:
            text += f"\n\n가드 점검 건너뜀: {e}"
    print(text)
    ci.write_summary(text)
    return 0 if res["ok"] else 1


def cmd_verify_log(p, a):
    bad = store.verify_log(p.log)
    print("로그 정상" if not bad else f"변조 의심 줄: {bad}")
    return 1 if bad else 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="kfin_eval", description="한국 금융 실무 평가 세트 파이프라인")
    ap.add_argument("--root", default=".", help="프로젝트 폴더(기본: 현재 폴더)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("validate", help="문항 형식·출처·중복 검사")
    r = sub.add_parser("review", help="검수 판정 기록")
    r.add_argument("--item", required=True)
    r.add_argument("--reviewer", required=True)
    r.add_argument("--verdict", required=True, choices=["approve", "reject"])
    r.add_argument("--note", default="")
    sub.add_parser("status", help="문항별 검수 상태")
    r = sub.add_parser("run", help="모델에 문항 풀리기")
    r.add_argument("--models", required=True, help="쉼표 구분. 예: claude-fable-5-2,mock-perfect")
    r.add_argument("--include-draft", action="store_true", help="미승인 문항도 포함(시험용)")
    r.add_argument("--run-id")
    r.add_argument("--authors", help="이 생성기·작성자의 문항만. 예: gen-els,gen-shocklens")
    r = sub.add_parser("grade", help="응답 채점")
    r.add_argument("--run-id", required=True)
    r.add_argument("--judge", help="서술형 LLM 채점자 모델(생략 시 키워드 채점)")
    r = sub.add_parser("report", help="점수표 생성")
    r.add_argument("--run-id", required=True)
    r = sub.add_parser("failures", help="채점 결과에서 틀린 응답을 실패 사례로 수집")
    r.add_argument("--run-id", required=True)
    r.add_argument("--threshold", type=float, default=1.0, help="이 점수 미만을 실패로 본다(0~1, 기본 1.0)")
    r = sub.add_parser("annotate", help="실패 사례에 오류 유형 붙이기")
    r.add_argument("--failure", required=True)
    r.add_argument("--annotator", required=True)
    r.add_argument("--type", required=True, choices=sorted(F.ERROR_TYPES))
    r.add_argument("--note", default="")
    sub.add_parser("failure-report", help="오류 유형·문항 변별력 보고서")
    r = sub.add_parser("env-run", help="업무 환경에서 에이전트 실행·판정")
    r.add_argument("--scenario", required=True)
    r.add_argument("--agents", required=True, help="쉼표 구분. 예: mock-good,mock-bad,claude-fable-5-2")
    r.add_argument("--run-id")
    r = sub.add_parser("gen", help="엔진으로 문항 생성(정답을 코드가 계산)")
    r.add_argument("--source", required=True, help="dart, disclosure, shocklens, els 또는 plugins/ 폴더의 생성기 이름")
    r.add_argument("--file", help="dart 전용: 실제 공시 숫자 CSV")
    r.add_argument("--n", type=int, default=20)
    r.add_argument("--seed", type=int, default=1)
    r = sub.add_parser("guard-check", help="Collatio 가드가 틀린 다수결을 잡는지 점검")
    r.add_argument("--run-id", required=True)
    r.add_argument("--threshold", type=float, help="일치 기준(생략 시 Collatio 설정값)")
    r = sub.add_parser("pipeline", help="검사부터 점수표·가드 점검까지 한 번에")
    r.add_argument("--models", required=True, help="예: eg:all 또는 eg:claude-haiku,eg:gpt-luna")
    r.add_argument("--run-id")
    r.add_argument("--authors", help="이 생성기·작성자의 문항만. 예: gen-els,gen-shocklens")
    r.add_argument("--include-draft", action="store_true")
    r.add_argument("--judge")
    r = sub.add_parser("probe-make", help="오답을 심은 검토 묶음 만들기")
    r.add_argument("--reviewer", required=True)
    r.add_argument("--n", type=int, default=20)
    r.add_argument("--wrong-rate", type=float, default=0.3, help="묶음에서 심은 오답의 비율(기본 0.3)")
    r.add_argument("--seed", type=int, default=1)
    r = sub.add_parser("probe-score", help="검토자가 채운 묶음 채점")
    r.add_argument("--batch", required=True, help="묶음 이름. 예: kim-s1")
    r.add_argument("--file", help="채운 CSV 경로(생략 시 data/probes/<묶음>.csv)")
    r = sub.add_parser("score", help="기여 점수 계산")
    r.add_argument("--run-id", help="이 실행만 반영(생략 시 전체)")
    r.add_argument("--real-only", action="store_true", help="mock 모델 결과 제외")
    r = sub.add_parser("calibrate", help="난도 단별 정답률: 어느 단을 늘리고 뺄지")
    r.add_argument("--run-id", required=True)
    r = sub.add_parser("publish", help="공개·비공개 세트 분리, 해시 목록과 카나리 생성")
    r.add_argument("--private-rate", type=float, default=0.7, help="비공개로 둘 비율(기본 0.7)")
    r.add_argument("--seed", type=int, default=1)
    sub.add_parser("probe-report", help="심은 오답 비율별·검토자별 포착률, d′, 판단 기준")
    r = sub.add_parser("irt", help="라쉬(1PL) 모형으로 문항 난도와 모델 실력 추정")
    r.add_argument("--run-id", required=True)
    sub.add_parser("verify-log", help="출처 추적 로그 변조 검사")
    r = sub.add_parser("ci-key", help="CI: 엔진 생성기 정답지가 고정본과 같은지 점검")
    r.add_argument("--update", action="store_true", help="정답지를 지금 엔진 기준으로 갱신")
    r = sub.add_parser("ci-smoke", help="CI: 고정 30문항 소규모 eval, 기준선(real2)과 비교")
    r.add_argument("--models", required=True, help="예: eg:claude-haiku,eg:claude-sonnet,eg:gpt-luna 또는 mock-perfect,mock-noisy")
    r.add_argument("--tolerance", type=int, default=2, help="모델별 허용 오답 증가 수(기본 2)")
    r.add_argument("--out", help="응답을 저장할 폴더(CI 산출물용)")
    r.add_argument("--no-guard", action="store_true", help="Collatio 가드 점검 생략")
    a = ap.parse_args(argv)
    return {"validate": cmd_validate, "review": cmd_review, "status": cmd_status, "run": cmd_run,
            "grade": cmd_grade, "report": cmd_report, "verify-log": cmd_verify_log,
            "ci-key": cmd_ci_key, "ci-smoke": cmd_ci_smoke, "failures": cmd_failures,
            "annotate": cmd_annotate, "probe-report": cmd_probe_report, "irt": cmd_irt, "calibrate": cmd_calibrate, "publish": cmd_publish, "probe-make": cmd_probe_make, "probe-score": cmd_probe_score, "score": cmd_score, "gen": cmd_gen, "guard-check": cmd_guard_check, "pipeline": cmd_pipeline, "failure-report": cmd_failure_report, "env-run": cmd_env_run}[a.cmd](Paths(a.root), a)


if __name__ == "__main__":
    raise SystemExit(main())
