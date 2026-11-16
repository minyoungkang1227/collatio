import numpy as np
import pytest

from echoguard import impact
from echoguard.metrics import FAILED


def test_pnl_is_position_times_truth():
    direction = np.array([[1, -1, 0, FAILED, 1]])
    truth = np.array([1, 1, 1, -1, 0])
    # 맞음 +1, 반대 -1, 관망 0, 전부 실패 0, 중립 뉴스 0
    assert impact.model_pnl(direction, truth).tolist() == [[1, -1, 0, 0, 0]]
    size = np.array([[0.8, 0.4, 1, 1, 1]])
    assert impact.model_pnl(direction, truth, size)[0].tolist() == pytest.approx([0.8, -0.4, 0, 0, 0])


def test_expected_shortfall_hand_value():
    pnl = np.array([-10.0, -6.0, 0, 1, 2, 3, 4, 5, 6, 7])
    assert impact.expected_shortfall(pnl, level=0.8) == pytest.approx(8.0)  # 가장 나쁜 두 건의 평균


def _world(overlap: bool, n: int = 200):
    """두 모델이 각각 뉴스의 20%에서 틀린다. overlap이면 같은 뉴스에서, 아니면 다른 뉴스에서 틀린다."""
    truth = np.ones(n, dtype=int)
    a = np.ones(n, dtype=int)
    b = np.ones(n, dtype=int)
    a[: n // 5] = -1
    if overlap:
        b[: n // 5] = -1
    else:
        b[n // 5 : 2 * n // 5] = -1
    return np.stack([a, b]), truth, np.zeros(n, dtype=int)


def test_overlapping_errors_make_the_tail_fatter():
    together = impact.impact(*_world(True), k=10, n_draws=4000, n_shuffle=30)
    apart = impact.impact(*_world(False), k=10, n_draws=4000, n_shuffle=30)
    assert together["even"]["es"] > apart["even"]["es"]
    assert together["even"]["all_lose_share"] == pytest.approx(0.2)
    assert apart["even"]["all_lose_share"] == 0.0
    assert together["even"]["per_news_std"] > apart["even"]["per_news_std"]
    # 손익이 양수 쪽이라 ES가 0 이하일 수 있다. 그때는 배수 대신 차이를 본다
    assert together["es_difference"] > 0 > apart["es_difference"]
    assert together["volatility_ratio"] > 1 > apart["volatility_ratio"]


def test_identical_models_behave_like_one_model():
    out = impact.impact(*_world(True), k=10, n_draws=20000, n_shuffle=5)
    assert out["even"]["es"] == pytest.approx(out["single_model"]["es_mean"], abs=0.3)
