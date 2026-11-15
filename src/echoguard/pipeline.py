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

from . import guard, metrics, store
from .dataset import NewsItem, assign_split
from .panel import ModelClient, run_panel
from .perturb import build_inputs

ROOT = Path(__file__).resolve().parents[2]
FIELD = "direction"  # 주 채점 대상. 정답은 direction_text


def analyze(records, items: list[NewsItem], clients: list[ModelClient], cfg: dict) -> dict:
    """저장된 기록에서 지표와 가드 성능을 계산한다."""
    models = [c.name for c in clients]
    families = [c.family for c in clients]
    ids = [it.item_id for it in items]
    n_runs = cfg["panel"]["n_runs"]
    seed = cfg["seed"]
    truth = np.array([it.direction_text for it in items])
    strata = np.array([f"{it.difficulty}|{it.type}" for it in items])

    def arr(kind):
        return store.to_array(records, FIELD, kind, models, ids, n_runs)

    original = arr("original")
    lo, hi = metrics.bootstrap_ci(
        lambda idx: metrics.pairwise_error_correlation(original[:, idx, :], truth[idx]), len(items), seed=seed
    )
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
        "wrong_answer_agreement": round(metrics.wrong_answer_agreement(original, truth), 3),
        "H1_permutation": metrics.permutation_test(original, truth, strata, seed=seed),
        "H2_family_gap": metrics.family_gap(original, truth, families),
        "H3_co_flip": {k: metrics.co_flip(original, arr(k)) for k in ("paraphrase", "ai_style", "source_swap")},
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
    report["H4_guard_eval_original"] = {
        "G1_agreement": guard.evaluate(guard.g1_agreement(ans, thr), ans, world),
        "G2_agreement_source_tag": guard.evaluate(guard.g2_agreement_source(ans, thr, verified), ans, world),
        "G3_probe": guard.evaluate(guard.g3_probe(ans, probe, thr), ans, world),
        "G4a_count_reports": guard.evaluate(guard.g4_corroboration(ans, thr, reports, k), ans, world),
        "G4b_count_independent": guard.evaluate(guard.g4_corroboration(ans, thr, independent, k), ans, world),
    }

    # 조작된 입력까지 합친 평가. 입력마다 (출처 표기, 겉으로 보이는 글 수, 독립 출처 수)가 다르다.
    zero, one = np.zeros_like(independent), np.ones_like(reports)
    kinds = {
        "original": (verified, reports, independent),
        "source_swap": (~verified, reports, independent),            # 표기만 바뀌고 내용은 사실 그대로
        "fact_flip": (verified, one, zero),                          # 조작된 글 한 건
        "fake_corroboration": (verified, one * fake_n, zero),        # 조작된 글을 여러 건 보도처럼 꾸밈
    }
    per_kind = {name: metrics.model_answers(arr(name))[:, ev] for name in kinds}
    pooled_ans = np.concatenate(list(per_kind.values()), axis=1)
    pooled_world = np.tile(world, len(kinds))
    tag, shown, indep = (np.concatenate([v[i] for v in kinds.values()]) for i in range(3))
    report["H4_guard_eval_with_manipulated_inputs"] = {
        "G1_agreement": guard.evaluate(guard.g1_agreement(pooled_ans, thr), pooled_ans, pooled_world),
        "G2_agreement_source_tag": guard.evaluate(
            guard.g2_agreement_source(pooled_ans, thr, tag), pooled_ans, pooled_world
        ),
        "G4a_count_reports": guard.evaluate(guard.g4_corroboration(pooled_ans, thr, shown, k), pooled_ans, pooled_world),
        "G4b_count_independent": guard.evaluate(
            guard.g4_corroboration(pooled_ans, thr, indep, k), pooled_ans, pooled_world
        ),
    }

    # H5: 꾸며 낸 여러 건 보도만 따로 떼어 본다
    fake = per_kind["fake_corroboration"]
    report["H5_fake_corroboration_only"] = {
        "G4a_count_reports": guard.evaluate(guard.g4_corroboration(fake, thr, one * fake_n, k), fake, world),
        "G4b_count_independent": guard.evaluate(guard.g4_corroboration(fake, thr, zero, k), fake, world),
    }
    return report


def run(items, written, clients, cfg: dict, runs_path: Path) -> dict:
    """호출하고, 저장하고, 저장한 것을 다시 읽어 분석한다.

    runs_path에 이미 기록이 있으면 그만큼은 건너뛰고 이어서 한다.
    호출 도중 오류(잔액 부족, 하루 한도 등)가 나면 그때까지의 기록은 파일에 남는다.
    """
    items = assign_split(items, cfg["dataset"]["n_tune"], cfg["seed"])
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
        report = run(items, written, build_clients(cfg["panel"]["models"]), cfg, runs_path)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
