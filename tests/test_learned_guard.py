"""학습하는 가드: 변수 계산은 손계산과 대조하고, 학습은 답을 아는 자료로 확인한다."""

from pathlib import Path

import numpy as np
import pytest
import yaml

from collatio import learned_guard as lg
from collatio import pipeline
from collatio.mock import make_world

ROOT = Path(__file__).resolve().parents[1]


def stack(answers, n_runs=2):
    return np.repeat(np.array(answers, dtype=float)[:, :, None], n_runs, axis=2)


def test_behavior_features_hand_values():
    families = ["A", "A", "B", "B"]
    # 뉴스 0: 전원 +1.  뉴스 1: A사는 둘 다 -1, B사는 -1과 +1로 갈림
    direction = stack([[1, -1], [1, -1], [1, -1], [1, 1]])
    direction[0, 0] = [1, -1]                 # 첫 모델은 뉴스 0에서 반복마다 답이 다르다 (표준편차 1)
    intensity = stack([[3, 2], [3, 4], [3, 2], [3, 4]])
    X = lg.behavior_features(direction, intensity, families)
    assert X[:, 0] == pytest.approx([0.25, 0.25])    # 뉴스 0은 첫 모델의 중앙값이 0이 되어 3/4만 일치
    assert X[:, 1] == pytest.approx([0.25, 0.0])     # 네 모델 중 하나만 표준편차 1
    assert X[:, 2] == pytest.approx([0.5, 0.5])      # 뉴스 0은 A사가, 뉴스 1은 B사가 갈림
    assert X[:, 3] == pytest.approx([0.0, 1.0])      # 강도 [2,4,2,4]의 표준편차
    assert X[:, 4] == pytest.approx([0.0, 0.0])


def test_failed_calls_show_up_as_a_feature():
    direction = stack([[1], [1]])
    direction[0, 0, 0] = np.nan
    X = lg.behavior_features(direction, stack([[3], [3]]), ["A", "B"])
    assert X[0, 4] == pytest.approx(0.25)            # 호출 4번 중 1번 실패


def test_source_features_hand_values():
    X = lg.source_features(np.array([True, False]), np.array([5, 3]), np.array([2, 0]), k=2)
    assert X.tolist() == [[0.0, 3.0, 0.0], [1.0, 3.0, 1.0]]


def test_fit_learns_a_known_rule_and_refuses_one_class():
    rng = np.random.default_rng(0)
    X = rng.normal(size=(400, 3))
    y = (X[:, 0] + 0.2 * rng.normal(size=400) > 0).astype(int)       # 첫 변수만 정답과 관련 있다
    model = lg.fit(X[:300], y[:300])
    coef = lg.coefficients(model, ["a", "b", "c"])
    assert coef["a"] > 3 * max(abs(coef["b"]), abs(coef["c"]))
    assert lg.evaluate(model, X[300:], y[300:], 0.5)["auc"] > 0.95
    assert lg.fit(X, np.zeros(400, dtype=int)) is None


def test_recall_at_review_rate_hand_value():
    score = np.array([0.9, 0.8, 0.3, 0.2, 0.1])
    y = np.array([1, 0, 1, 0, 0])
    assert lg.recall_at_review_rate(score, y, 0.4) == pytest.approx(0.5)   # 위 2건만 검토 → 틀린 2건 중 1건
    assert lg.recall_at_review_rate(score, y, 0.6) == pytest.approx(1.0)


def test_grouped_bootstrap_interval_brackets_the_estimate():
    rng = np.random.default_rng(1)
    y = rng.integers(0, 2, 200)
    score = y * 0.3 + rng.random(200)
    lo, hi = lg.auc_ci(y, score, np.repeat(np.arange(50), 4), n_boot=300)
    assert lo < lg._auc(y, score) < hi


def test_behavior_alone_cannot_tell_fabricated_news_but_sources_can():
    """모의 모델은 조작된 글도 충실히 읽고 한목소리로 답한다. 그래서 행동만 보면 사실인 글과 구분되지 않는다."""
    cfg = yaml.safe_load((ROOT / "config" / "experiment.yaml").read_text(encoding="utf-8"))
    items, written, clients = make_world(seed=1)
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        h6 = pipeline.run(items, written, clients, cfg, Path(tmp) / "runs.jsonl")["H6_learned_guard"]
    a, b = h6["G5a_behavior_only"], h6["G5b_behavior_and_source"]
    assert a["eval_fabrication_auc"] < 0.65
    assert b["eval_fabrication_auc"] > 0.85
    assert set(a["coefficients"]) == set(lg.BEHAVIOR)


def test_rank_auc_matches_sklearn_including_ties():
    import numpy as np
    from sklearn.metrics import roc_auc_score

    from collatio.learned_guard import rank_auc

    rng = np.random.default_rng(0)
    for _ in range(20):
        y = rng.integers(0, 2, 60)
        s = rng.integers(0, 6, 60) / 5  # 동점이 많이 생기게
        if len(np.unique(y)) == 2:
            assert abs(rank_auc(y, s) - roc_auc_score(y, s)) < 1e-12
    assert np.isnan(rank_auc(np.ones(5), np.arange(5)))
