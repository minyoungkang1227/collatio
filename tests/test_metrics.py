"""손으로 계산할 수 있는 작은 예로 측정 엔진을 확인한다."""

import numpy as np
import pytest

from echoguard import metrics


def stack(answers, n_runs=3):
    """(모델, 뉴스) 답을 반복 축으로 복제해 (모델, 뉴스, 반복)으로 만든다."""
    return np.repeat(np.array(answers)[:, :, None], n_runs, axis=2)


def test_intra_dispersion_zero_when_runs_identical():
    runs = stack([[1, 2, 3], [3, 3, 3]])
    assert metrics.intra_model_dispersion(runs) == pytest.approx([0.0, 0.0])


def test_intra_dispersion_hand_value():
    # 모델 하나, 뉴스 하나, 반복 [1, 3] → 표준편차 1
    runs = np.array([[[1, 3]]])
    assert metrics.intra_model_dispersion(runs) == pytest.approx([1.0])


def test_agreement_perfect_and_degenerate():
    assert metrics.inter_model_agreement(stack([[1, 3, 5], [1, 3, 5]])) == pytest.approx(1.0)
    assert metrics.inter_model_agreement(stack([[2, 2, 2], [2, 2, 2]])) == 1.0


def test_agreement_drops_when_models_disagree():
    agree = metrics.inter_model_agreement(stack([[1, 2, 4, 5], [1, 2, 4, 5], [1, 3, 4, 5]]))
    clash = metrics.inter_model_agreement(stack([[1, 2, 4, 5], [5, 4, 2, 1], [3, 3, 3, 3]]))
    assert clash < agree < 1.0


def test_correlated_error_hand_value():
    truth = np.array([1, 1, 1, 1])
    # 두 모델 모두 뉴스 0, 1에서 틀림. 뉴스 0은 같은 오답(5), 뉴스 1은 다른 오답(4, 5)
    runs = stack([[5, 4, 1, 1], [5, 5, 1, 1]])
    out = metrics.correlated_error(runs, truth)
    assert out["joint_error_rate"] == pytest.approx(0.5)
    assert out["independent_rate"] == pytest.approx(0.25)  # 0.5 × 0.5
    assert out["excess"] == pytest.approx(0.25)
    assert out["same_wrong_rate"] == pytest.approx(0.25)


def test_correlated_error_zero_excess_when_errors_do_not_overlap():
    truth = np.array([1, 1, 1, 1])
    runs = stack([[5, 5, 1, 1], [1, 1, 5, 5]])
    out = metrics.correlated_error(runs, truth)
    assert out["joint_error_rate"] == 0.0
    assert out["excess"] == pytest.approx(-0.25)


def test_co_flip_hand_value():
    original = stack([[3, 3], [3, 3], [3, 3], [3, 3]])
    # 뉴스 0: 4개 모델 전부 위로. 뉴스 1: 2개 위, 1개 아래, 1개 그대로 → 우세 방향 비율 0.5
    perturbed = stack([[4, 4], [5, 4], [4, 2], [4, 3]])
    out = metrics.co_flip(original, perturbed)
    assert out["flip_rate"] == pytest.approx(7 / 8)
    assert out["co_flip_rate"] == pytest.approx((1.0 + 0.5) / 2)


def test_co_flip_no_movement():
    runs = stack([[2, 3], [4, 1]])
    assert metrics.co_flip(runs, runs) == {"flip_rate": 0.0, "co_flip_rate": 0.0}


def test_pairwise_error_correlation_extremes():
    truth = np.array([1, 1, 1, 1])
    same = stack([[5, 5, 1, 1], [5, 5, 1, 1]])
    opposite = stack([[5, 5, 1, 1], [1, 1, 5, 5]])
    assert metrics.pairwise_error_correlation(same, truth) == pytest.approx(1.0)
    assert metrics.pairwise_error_correlation(opposite, truth) == pytest.approx(-1.0)


def test_pairwise_error_correlation_undefined_when_a_model_never_errs():
    truth = np.array([1, 1, 1, 1])
    runs = stack([[1, 1, 1, 1], [5, 1, 1, 1]])
    assert np.isnan(metrics.pairwise_error_correlation(runs, truth))


def test_permutation_detects_shared_errors():
    rng = np.random.default_rng(1)
    truth = np.ones(200, dtype=int)
    shared = rng.random(200) < 0.3                      # 세 모델이 같은 뉴스에서 틀림
    runs = stack([np.where(shared, 5, 1)] * 3)
    out = metrics.permutation_test(runs, truth, strata=np.zeros(200), n_perm=500)
    assert out["observed"] > out["null_mean"]
    assert out["p_value"] < 0.01


def test_permutation_does_not_blame_difficulty():
    # 어려운 구간에서는 누구나 자주 틀리지만 모델끼리는 독립인 경우 → 유의하면 안 된다
    rng = np.random.default_rng(2)
    truth = np.ones(400, dtype=int)
    strata = np.repeat([0, 1], 200)
    p_wrong = np.where(strata == 1, 0.6, 0.05)
    runs = stack([np.where(rng.random(400) < p_wrong, 5, 1) for _ in range(4)])
    stratified = metrics.permutation_test(runs, truth, strata, n_perm=500)
    pooled = metrics.permutation_test(runs, truth, np.zeros(400), n_perm=500)
    assert stratified["p_value"] > 0.05
    assert pooled["p_value"] < 0.05     # 구간을 무시하면 난이도를 상관 오류로 착각한다


def test_bootstrap_ci_contains_point_estimate():
    values = np.arange(100) % 2
    lo, hi = metrics.bootstrap_ci(lambda idx: values[idx].mean(), n_items=100, n_boot=500)
    assert lo < 0.5 < hi
