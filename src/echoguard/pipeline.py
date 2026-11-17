"""전체 흐름: 데이터 → 변형 → 패널 → 저장 → 측정 → 가드 → 보고.

    python -m echoguard.pipeline --mock

실제 모델 호출은 아직 없다. --mock은 모의 모델로 층과 층이 맞물리는지 보여 준다.
"""

import argparse
import json
import tempfile
from pathlib import Path

import numpy as np
import yaml

from . import guard, impact, learned_guard, metrics, store
from .dataset import NewsItem, assign_split
from .panel import ModelClient, run_panel
from .perturb import build_inputs

ROOT = Path(__file__).resolve().parents[2]
FIELD = "direction"  # 주 채점 대상. 정답은 direction_text


def analyze(records, items: list[NewsItem], clients: list[ModelClient], cfg: dict) -> dict:
    """저장된 기록에서 지표와 가드 성능을 계산한다."""
    models = [c.name for c in clients]
    families = [c.family for c in clients]
    tiers = [getattr(c, "tier", None) for c in clients]
    ids = [it.item_id for it in items]
    n_runs = cfg["panel"]["n_runs"]
    seed = cfg["seed"]
    truth = np.array([it.direction_text for it in items])
    strata = np.array([f"{it.difficulty}|{it.type}" for it in items])

    def arr(kind):
        return store.to_array(records, FIELD, kind, models, ids, n_runs)

    # 모델에 실제로 보낸 (뉴스, 변형)만 채점한다. 뒤집기 글을 만들지 않은 뉴스는 그 변형에서 빠진다.
    sent = {(r.item_id, r.perturbation) for r in records}

    def asked(kind):
        return np.array([(i, kind) in sent for i in ids])

    original = arr("original")
    lo, hi = metrics.bootstrap_ci(
        lambda idx: metrics.pairwise_error_correlation(original[:, idx, :], truth[idx]), len(items), seed=seed
    )
    def gap_ci(fn, labels):  # 가족 간 격차(H2)와 등급 간 격차(H7)의 뉴스 단위 부트스트랩 구간
        g = metrics.bootstrap_ci(lambda idx: fn(original[:, idx, :], truth[idx], labels)["gap"], len(items), seed=seed)
        return [round(g[0], 3), round(g[1], 3)]

    report = {
        "n_items": len(items),
        "models": models,
        "failed_call_rate": float(np.isnan(original).mean()),
        "accuracy": dict(zip(models, (1 - metrics.error_matrix(original, truth).mean(axis=1)).round(3).tolist())),
        "intra_model_dispersion": dict(zip(models, metrics.intra_model_dispersion(original).round(3).tolist())),
        "inter_model_agreement": round(metrics.inter_model_agreement(original), 3),
        "correlated_error": metrics.correlated_error(original, truth),
        "pairwise_error_correlation": {
            "value": round(metrics.pairwise_error_correlation(original, truth), 3),
            "ci95": [round(lo, 3), round(hi, 3)],
        },
        "error_consistency": round(metrics.error_consistency(original, truth), 3),
        "diversification": metrics.diversification(original, truth),
        "wrong_answer_agreement": {
            "value": round(metrics.wrong_answer_agreement(original, truth), 3),
            "random_baseline": metrics.WRONG_AGREEMENT_BASELINE,
        },
        "H1_permutation": metrics.permutation_test(original, truth, strata, seed=seed),
        "H2_family_gap": {**metrics.family_gap(original, truth, families), "gap_ci95": gap_ci(metrics.family_gap, families)},
        "H7_tier_gap": {**metrics.tier_gap(original, truth, tiers), "gap_ci95": gap_ci(metrics.tier_gap, tiers)},
        # 보내지 않은 변형은 계산하지 않는다. 답이 없는 것을 '답이 바뀌었다'로 세면 안 된다
        "H3_co_flip": {
            k: metrics.co_flip(original[:, asked(k), :], arr(k)[:, asked(k), :]) if asked(k).any() else "이 변형을 보내지 않음"
            for k in ("paraphrase", "ai_style", "source_swap")
        },
    }

    # 가드는 평가용 뉴스에서만 채점한다.
    # 정답은 '실제 사실'의 방향이다. 사실을 뒤집은 글(fact_flip)을 모델이 충실히 읽으면
    # 글에 대해서는 맞지만 실제 사실과는 어긋난다. 가드가 잡아야 하는 것은 이 둘 다다.
    ev = np.array([it.split == "eval" for it in items])
    world = truth[ev]
    verified = np.array([it.source_verified for it in items])[ev]
    independent = np.array([it.n_independent_sources for it in items])[ev]
    reports = np.array([it.n_reports for it in items])[ev]
    thr, k, fake_n = cfg["guard"]["agreement_alert"], cfg["guard"]["k_sources"], cfg["guard"]["fake_reports"]

    ans = metrics.model_answers(original)[:, ev]
    probe = metrics.model_answers(arr("paraphrase"))[:, ev]

    def basis(kind):  # (모델, 평가용 뉴스): 근거가 지침대로였던 반복의 비율
        return store.basis_share(records, kind, models, items)[:, ev]

    # 근거 검사 요약: 원문에서, 기준 지표의 값을 아는 뉴스만
    all_basis = store.basis_share(records, "original", models, items)
    known = ~np.isnan(all_basis).all(axis=0)
    cited = {}
    for r in records:
        if r.perturbation == "original" and r.model in models and r.output is not None and r.output.basis_metric:
            cited[r.output.basis_metric] = cited.get(r.output.basis_metric, 0) + 1
    report["basis"] = {
        "n_items_with_known_figure": int(known.sum()),
        "share_following_the_rule": {m: round(float(np.nanmean(all_basis[i, known])), 3) if known.any() else None for i, m in enumerate(models)},
        "metrics_cited_on_originals": dict(sorted(cited.items(), key=lambda kv: -kv[1])),
    }
    report["H4_guard_eval_original"] = {
        "G1_agreement": guard.evaluate(guard.g1_agreement(ans, thr), ans, world),
        "G2_agreement_source_tag": guard.evaluate(guard.g2_agreement_source(ans, thr, verified), ans, world),
        "G3_probe": guard.evaluate(guard.g3_probe(ans, probe, thr), ans, world)
        if asked("paraphrase")[ev].all()
        else "말 바꾸기 변형이 없는 뉴스가 있어 계산하지 않음",
        "G4a_count_reports": guard.evaluate(guard.g4_corroboration(ans, thr, reports, k), ans, world),
        "G4b_count_independent": guard.evaluate(guard.g4_corroboration(ans, thr, independent, k, verified), ans, world),
        "G6_basis_check": guard.evaluate(guard.g6_basis(ans, thr, basis("original")), ans, world),
    }

    # 조작된 입력까지 합친 평가. 입력마다 (출처 표기, 겉으로 보이는 글 수, 독립 출처 수)가 다르다.
    zero, one = np.zeros_like(independent), np.ones_like(reports)
    never = np.zeros_like(verified)
    kinds = {  # 입력 종류: (출처 표기, 겉으로 보이는 글 수, 독립 출처 수, 1차 출처가 실제로 확인되는가)
        "original": (verified, reports, independent, verified),
        "source_swap": (~verified, reports, independent, verified),         # 표기만 바뀌고 내용은 사실 그대로
        "fact_flip": (verified, one, zero, never),                          # 조작된 글 한 건
        "fake_corroboration": (verified, one * fake_n, zero, never),        # 조작된 글을 여러 건 보도처럼 꾸밈
    }
    per_kind = {name: metrics.model_answers(arr(name))[:, ev] for name in kinds}
    keep = {name: asked(name)[ev] for name in kinds}
    pooled_ans = np.concatenate([per_kind[n][:, keep[n]] for n in kinds], axis=1)
    pooled_world = np.concatenate([world[keep[n]] for n in kinds])
    tag, shown, indep, primary = (np.concatenate([kinds[n][i][keep[n]] for n in kinds]) for i in range(4))
    pooled_basis = np.concatenate([basis(n)[:, keep[n]] for n in kinds], axis=1)
    report["H4_guard_eval_with_manipulated_inputs"] = {
        "G1_agreement": guard.evaluate(guard.g1_agreement(pooled_ans, thr), pooled_ans, pooled_world),
        "G2_agreement_source_tag": guard.evaluate(
            guard.g2_agreement_source(pooled_ans, thr, tag), pooled_ans, pooled_world
        ),
        "G4a_count_reports": guard.evaluate(guard.g4_corroboration(pooled_ans, thr, shown, k), pooled_ans, pooled_world),
        "G4b_count_independent": guard.evaluate(
            guard.g4_corroboration(pooled_ans, thr, indep, k, primary), pooled_ans, pooled_world
        ),
        "G6_basis_check": guard.evaluate(guard.g6_basis(pooled_ans, thr, pooled_basis), pooled_ans, pooled_world),
    }

    # 금융 영향: 원문에 대한 판단으로만 계산한다. 조작된 글은 넣지 않는다
    ic = cfg.get("impact", {})
    args = dict(k=ic.get("period_news", 20), level=ic.get("es_level", 0.975), share=ic.get("concentrated_share", 0.6), seed=seed)
    answers = metrics.model_answers(original)
    strength = metrics.model_answers(store.to_array(records, "intensity", "original", models, ids, n_runs))
    strength = np.where(strength == metrics.FAILED, 0, strength) / 5
    report["impact"] = {
        "unit_position": impact.impact(answers, truth, strata, **args),
        "intensity_weighted": impact.impact(answers, truth, strata, size=strength, **args),
    }

    report["H6_learned_guard"] = _learned_guard(records, items, models, families, ids, n_runs, truth, cfg, sent)

    # H5: 꾸며 낸 여러 건 보도만 따로 떼어 본다
    kf = keep["fake_corroboration"]
    fake, fw = per_kind["fake_corroboration"][:, kf], world[kf]
    report["H5_fake_corroboration_only"] = {
        "n_items": int(kf.sum()),
        "G4a_count_reports": guard.evaluate(guard.g4_corroboration(fake, thr, (one * fake_n)[kf], k), fake, fw),
        "G4b_count_independent": guard.evaluate(guard.g4_corroboration(fake, thr, zero[kf], k, never[kf]), fake, fw),
    }
    return report


def _learned_guard(records, items, models, families, ids, n_runs, truth, cfg, sent) -> dict:
    """학습하는 가드. 설정용 뉴스로 맞추고 평가용 뉴스로 채점한다."""
    k, fake_n, rate = cfg["guard"]["k_sources"], cfg["guard"]["fake_reports"], cfg["guard"]["review_rate"]
    verified = np.array([it.source_verified for it in items])
    reports = np.array([it.n_reports for it in items])
    independent = np.array([it.n_independent_sources for it in items])
    zero, one = np.zeros_like(independent), np.ones_like(reports)
    enough = np.where(verified, np.maximum(independent, k), independent)  # 1차 출처가 확인되면 출처 부족으로 보지 않는다
    kinds = {  # 입력 종류: (출처 표기, 겉으로 보이는 글 수, 독립 출처 수, 조작된 글인가)
        "original": (verified, reports, enough, False),
        "source_swap": (~verified, reports, enough, False),
        "fact_flip": (verified, one, zero, True),
        "fake_corroboration": (verified, one * fake_n, zero, True),
    }
    Xb, Xs, y, fabricated, group, tune, kept = [], [], [], [], [], [], []
    for name, (tag, shown, indep, fake) in kinds.items():
        direction = store.to_array(records, "direction", name, models, ids, n_runs)
        intensity = store.to_array(records, "intensity", name, models, ids, n_runs)
        Xb.append(learned_guard.behavior_features(direction, intensity, families))
        Xs.append(learned_guard.source_features(tag, shown, indep, k))
        y.append(guard.majority(metrics.model_answers(direction))[0] != truth)
        fabricated.append(np.full(len(items), fake))
        group.append(np.arange(len(items)))
        tune.append(np.array([it.split == "tune" for it in items]))
        kept.append(np.array([(i, name) in sent for i in ids]))
    kept = np.concatenate(kept)  # 보내지 않은 (뉴스, 변형)은 학습과 채점에서 뺀다
    Xb, Xs, y, fabricated, group, tune = (np.concatenate(v)[kept] for v in (Xb, Xs, y, fabricated, group, tune))
    y = y.astype(int)
    variants = {
        "G5a_behavior_only": (Xb, learned_guard.BEHAVIOR),
        "G5b_behavior_and_source": (np.hstack([Xb, Xs]), learned_guard.BEHAVIOR + learned_guard.SOURCE),
    }
    out = {"review_rate": rate, "n_tune_rows": int(tune.sum()), "n_tune_wrong": int(y[tune].sum())}
    for name, (X, names) in variants.items():
        model = learned_guard.fit(X[tune], y[tune])
        if model is None:
            out[name] = "설정용 자료에 틀린 판단이 없거나 전부 틀려서 학습할 수 없음"
            continue
        ev = ~tune
        score = model.predict_proba(X[ev])[:, 1]
        genuine = ev & ~fabricated
        out[name] = {
            "coefficients": learned_guard.coefficients(model, names),
            "cv_auc_tune": learned_guard.grouped_cv_auc(X[tune], y[tune], group[tune]),
            "eval_all_inputs": learned_guard.evaluate(model, X[ev], y[ev], rate),
            # 오독: 사실인 글만 놓고, 패널이 잘못 읽은 것을 가려내는가
            "eval_misreading_auc": learned_guard._auc(y[genuine], model.predict_proba(X[genuine])[:, 1]),
            # 오신: 점수만 보고 조작된 글을 사실인 글과 구분하는가
            "eval_fabrication_auc": learned_guard._auc(fabricated[ev].astype(int), score),
            "eval_fabrication_auc_ci95": learned_guard.auc_ci(
                fabricated[ev].astype(int), score, group[ev], seed=cfg["seed"]
            ),
        }
    return out


def run(items, written, clients, cfg: dict, runs_path: Path) -> dict:
    """호출하고, 저장하고, 저장한 것을 다시 읽어 분석한다.

    runs_path에 이미 기록이 있으면 그만큼은 건너뛰고 이어서 한다.
    호출 도중 오류(잔액 부족, 하루 한도 등)가 나면 그때까지의 기록은 파일에 남는다.
    """
    # 건수가 계획(100건)보다 적은 시범 실행에서는 같은 비율(6:4)로 나눈다
    n_tune = min(cfg["dataset"]["n_tune"], round(len(items) * 0.6))
    items = assign_split(items, n_tune, cfg["seed"])
    inputs = build_inputs(items, written, cfg["guard"]["fake_reports"])
    system = (ROOT / "prompts" / "institutional_system.txt").read_text(encoding="utf-8")
    done = {store.key(r) for r in store.load(runs_path)} if Path(runs_path).exists() else set()
    run_panel(
        clients, inputs, system, cfg["panel"]["n_runs"], cfg["data_version"],
        done=done, sink=lambda record: store.save([record], runs_path),
    )
    return analyze(store.load(runs_path), items, clients, cfg)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--mock", action="store_true", help="모의 모델로 전체 흐름을 돌린다")
    mode.add_argument("--run", action="store_true", help="라벨 파일의 뉴스로 실제 모델을 호출한다 (API 키와 비용 필요)")
    parser.add_argument("--only", help="패널 중 일부 모델만 쓴다. 설정 파일의 name을 쉼표로 (예: gpt-sol,claude-sonnet)")
    args = parser.parse_args()
    cfg = yaml.safe_load((ROOT / "config" / "experiment.yaml").read_text(encoding="utf-8"))

    if args.mock:
        from .mock import make_world

        items, written, clients = make_world(seed=cfg["seed"])
        with tempfile.TemporaryDirectory() as tmp:
            report = run(items, written, clients, cfg, Path(tmp) / "runs.jsonl")
        print("※ 모의 데이터입니다. 아래 숫자는 실제 모델과 무관합니다.")
    else:
        from .clients import build_clients
        from .dataset import load_labels, load_written

        items = load_labels(ROOT / cfg["dataset"]["labels_file"])
        if not items:
            parser.error("라벨 파일이 비어 있습니다. docs/labeling_guide.md를 보고 뉴스를 먼저 채우세요.")
        early = [it.item_id for it in items if it.date < cfg["dataset"]["news_from"]]
        if early:
            parser.error(f"기준일({cfg['dataset']['news_from']}) 이전 뉴스가 있습니다: {early[:5]}")
        written = load_written(ROOT / "data" / "labels" / "perturbations.csv")
        runs_path = ROOT / "data" / "runs" / cfg["data_version"] / "institutional.jsonl"
        print(f"뉴스 {len(items)}건, 응답은 {runs_path}에 쌓입니다. 멈춰도 다시 실행하면 이어서 합니다.")
        models = cfg["panel"]["models"]
        if args.only:
            wanted = args.only.split(",")
            unknown = [n for n in wanted if n not in {m["name"] for m in models}]
            if unknown:
                parser.error(f"설정 파일에 없는 모델입니다: {unknown}")
            models = [m for m in models if m["name"] in wanted]
            print(f"※ 패널 일부({len(models)}개)만 씁니다. 사전에 정한 패널과 다르므로 이 결과는 탐색용입니다.")
        report = run(items, written, build_clients(models), cfg, runs_path)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
