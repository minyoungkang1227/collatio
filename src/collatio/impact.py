"""금융 영향: 모델들이 함께 틀리는 것이 손실의 꼬리를 얼마나 키우는가.

가상의 금융회사들이 각자 모델 하나의 방향 판단대로 포지션을 잡는다고 놓는다.
  포지션   모델의 방향 답 (+1 매수, -1 매도, 0 관망). 전부 실패한 칸은 0
  손익     포지션 × 실제 방향. 맞으면 +1, 반대면 -1, 관망했거나 중립 뉴스면 0
  체계 손익 회사들의 손익을 모델 점유율로 가중평균한 값. 뉴스마다 -1에서 1 사이

비교 기준은 '독립인 세계'다. 각 모델의 손익을 난이도 구간 안에서만 따로 섞는다.
모델별 손익 분포는 그대로이고, 어느 뉴스에서 손실을 봤는지만 서로 무관해진다. H1의 순열검정과 같은 방식이다.

판단이 곧 매매로 이어진다는 것, 손익의 크기가 1이라는 것, 회사별 모델 점유율은 모두 가정이다.
가격 충격과 연쇄 매도는 넣지 않는다. 결과는 원화가 아니라 독립일 때에 대한 배수로 읽는다.
"""

import numpy as np

from .metrics import FAILED


def model_pnl(direction: np.ndarray, truth: np.ndarray, size: np.ndarray | None = None) -> np.ndarray:
    """모델별·뉴스별 손익. 모양 (모델, 뉴스). size를 주면 포지션 크기로 곱한다(강도 비례 민감도 분석)."""
    position = np.where(direction == FAILED, 0, direction).astype(float)
    if size is not None:
        position = position * size
    return position * truth[None, :]


def expected_shortfall(pnl: np.ndarray, level: float = 0.975) -> float:
    """손익 분포에서 가장 나쁜 (1 - level) 구간의 평균 손실. 손실이 클수록 큰 양수다."""
    losses = -np.asarray(pnl, dtype=float)
    cutoff = np.quantile(losses, level)
    return float(losses[losses >= cutoff].mean())


def period_es(per_item: np.ndarray, k: int, n_draws: int, rng: np.random.Generator, level: float) -> float:
    """뉴스 k건이 한 기간에 나온다고 보고, 뉴스를 복원추출해 기간 손익의 ES를 구한다."""
    idx = rng.integers(0, len(per_item), size=(n_draws, k))
    return expected_shortfall(per_item[idx].sum(axis=1), level)


def shuffle_within_strata(pnl: np.ndarray, strata: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """독립인 세계: 모델마다 손익을 같은 구간 안에서 따로 섞는다."""
    out = pnl.copy()
    for idx in (np.flatnonzero(strata == s) for s in np.unique(strata)):
        for m in range(len(pnl)):
            out[m, idx] = pnl[m, rng.permutation(idx)]
    return out


def _even(n: int) -> np.ndarray:
    return np.full(n, 1 / n)


def _concentrated(n: int, lead: int, share: float) -> np.ndarray:
    w = np.full(n, (1 - share) / (n - 1))
    w[lead] = share
    return w


def impact(
    direction: np.ndarray,
    truth: np.ndarray,
    strata: np.ndarray,
    size: np.ndarray | None = None,
    k: int = 20,
    level: float = 0.975,
    share: float = 0.6,
    n_draws: int = 20000,
    n_shuffle: int = 200,
    seed: int = 0,
) -> dict:
    """집중도 시나리오별 기간 ES와, 모델들이 독립이었다면 나왔을 ES.

    even              회사들이 모델에 고르게 나뉜다
    concentrated      회사의 share(기본 60%)가 한 모델을 쓴다. 어느 모델이 그 자리에 오느냐에 따라 평균·최소·최대
    single_model      모든 회사가 같은 모델을 쓴다. 마찬가지로 모델별 평균·최소·최대
    if_independent    고르게 나뉜 경우를 독립인 세계에서 다시 계산한 값의 평균
    es_difference     even의 ES − if_independent의 ES. 0보다 크면 함께 틀려서 꼬리가 나빠진 것이다
    es_ratio          두 ES의 비. 독립인 세계의 ES가 0 이하(가장 나쁜 기간에도 이익)면 정의되지 않아 NaN이다
    volatility_ratio  뉴스 한 건의 체계 손익 표준편차가 독립일 때의 몇 배인가. 항상 정의되므로 주 지표로 쓴다

    ES는 손실을 양수로 적는다. 음수면 가장 나쁜 기간에도 이익이라는 뜻이다.
    """
    rng = np.random.default_rng(seed)
    pnl = model_pnl(direction, truth, size)
    n = len(pnl)

    def es(weights: np.ndarray, table: np.ndarray = pnl, draws: int = n_draws) -> float:
        return period_es(weights @ table, k, draws, rng, level)

    even = es(_even(n))
    conc = [es(_concentrated(n, m, share)) for m in range(n)]
    single = [es(np.eye(n)[m]) for m in range(n)]
    indep, indep_std = [], []
    for _ in range(n_shuffle):
        shuffled = shuffle_within_strata(pnl, strata, rng)
        indep.append(es(_even(n), shuffled, max(n_draws // 4, 1000)))
        indep_std.append(float((_even(n) @ shuffled).std()))
    base, base_std = float(np.mean(indep)), float(np.mean(indep_std))
    per_item = _even(n) @ pnl
    return {
        "period_news": k,
        "es_level": level,
        "even": {"es": even, "all_lose_share": float((pnl < 0).all(axis=0).mean()), "per_news_std": float(per_item.std())},
        "if_independent": {
            "es": base,
            "es_p05_p95": [float(np.quantile(indep, 0.05)), float(np.quantile(indep, 0.95))],
            "per_news_std": base_std,
        },
        "es_difference": even - base,
        "es_ratio": even / base if base > 0 else float("nan"),
        "volatility_ratio": float(per_item.std()) / base_std if base_std > 0 else float("nan"),
        f"concentrated_{int(share * 100)}": {"es_mean": float(np.mean(conc)), "es_min": float(min(conc)), "es_max": float(max(conc))},
        "single_model": {"es_mean": float(np.mean(single)), "es_min": float(min(single)), "es_max": float(max(single))},
    }
