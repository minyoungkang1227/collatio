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
        "H1_permutation": metrics.permutation_test(original, truth, strata, seed=seed),
        "H2_family_gap": metrics.family_gap(original, truth, families),
        "H3_co_flip": {k: metrics.co_flip(original, arr(k)) for k in ("paraphrase", "ai_style", "source_swap")},
    }

    # 가드는 평가용 뉴스에서만 채점한다
    ev = np.array([it.split == "eval" for it in items])
    ans = metrics.model_answers(original)[:, ev]
    probe = metrics.model_answers(arr("paraphrase"))[:, ev]
    verified = np.array([it.source_verified for it in items])[ev]
    thr = cfg["guard"]["agreement_alert"]
    report["H4_guard_eval"] = {
        "G1_agreement": guard.evaluate(guard.g1_agreement(ans, thr), ans, truth[ev]),
        "G2_agreement_source": guard.evaluate(guard.g2_agreement_source(ans, thr, verified), ans, truth[ev]),
        "G3_probe": guard.evaluate(guard.g3_probe(ans, probe, thr), ans, truth[ev]),
    }
    return report


def run(items, written, clients, cfg: dict, runs_path: Path) -> dict:
    items = assign_split(items, cfg["dataset"]["n_tune"], cfg["seed"])
    inputs = build_inputs(items, written)
    system = (ROOT / "prompts" / "institutional_system.txt").read_text(encoding="utf-8")
    records = run_panel(clients, inputs, system, cfg["panel"]["n_runs"], cfg["data_version"])
    store.save(records, runs_path)
    return analyze(store.load(runs_path), items, clients, cfg)  # 저장한 것을 다시 읽어 계산한다


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mock", action="store_true", help="모의 모델로 전체 흐름을 돌린다")
    args = parser.parse_args()
    if not args.mock:
        parser.error("실제 모델 클라이언트는 아직 없습니다. --mock으로 실행하세요.")
    from .mock import make_world

    cfg = yaml.safe_load((ROOT / "config" / "experiment.yaml").read_text(encoding="utf-8"))
    items, written, clients = make_world(seed=cfg["seed"])
    with tempfile.TemporaryDirectory() as tmp:
        report = run(items, written, clients, cfg, Path(tmp) / "runs.jsonl")
    print("※ 모의 데이터입니다. 아래 숫자는 실제 모델과 무관합니다.")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
