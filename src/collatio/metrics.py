"""측정 엔진. LLM을 쓰지 않는 순수 계산이다.

입력 배열의 모양은 모두 (모델 수, 뉴스 수, 반복 수)이고 값은 순서형 정수다.
"""

import krippendorff
import numpy as np


FAILED = -99  # 반복이 전부 실패한 칸의 대표 답. 어떤 정답과도 같지 않으므로 오답으로 센다


def model_answers(runs: np.ndarray) -> np.ndarray:
    """반복을 모델별 대표 답 하나로 줄인다. 모양 (모델, 뉴스).

    중앙값을 쓰되 짝수 반복에서 .5가 나오면 아래쪽 값으로 내린다.
    실패한 호출(NaN)은 빼고 계산하고, 전부 실패한 칸은 FAILED로 둔다.
    """
    runs = np.asarray(runs, dtype=float)
    all_failed = np.isnan(runs).all(axis=2)
    filled = np.where(all_failed[:, :, None], 0.0, runs)
    answers = np.floor(np.nanmedian(filled, axis=2)).astype(int)
    answers[all_failed] = FAILED
    return answers


def intra_model_dispersion(runs: np.ndarray) -> np.ndarray:
    """① 모델 내 분산: 같은 모델이 같은 뉴스에 얼마나 흔들리는지. 모델별 평균 표준편차."""
    runs = np.asarray(runs, dtype=float)
    all_failed = np.isnan(runs).all(axis=2)
    spread = np.nanstd(np.where(all_failed[:, :, None], 0.0, runs), axis=2)
    return np.nanmean(np.where(all_failed, np.nan, spread), axis=1)


def inter_model_agreement(runs: np.ndarray) -> float:
    """② 모델 간 일치도: 대표 답에 대한 순서형 Krippendorff α. 1이면 완전 일치."""
    answers = model_answers(runs).astype(float)
    answers[answers == FAILED] = np.nan  # 실패는 결측으로 처리
    if np.unique(answers[~np.isnan(answers)]).size <= 1:
        return 1.0  # 값이 하나뿐이면 α가 정의되지 않으므로 완전 일치로 둔다
    return float(
        krippendorff.alpha(
            reliability_data=answers,
            level_of_measurement="ordinal",
        )
    )


def error_matrix(runs: np.ndarray, truth: np.ndarray) -> np.ndarray:
    """모델별·뉴스별 오답 여부. 모양 (모델, 뉴스), 틀리면 True."""
    return model_answers(runs) != truth[None, :]


def correlated_error(runs: np.ndarray, truth: np.ndarray) -> dict:
    """③ 상관 오류: 일치했는데 틀린 정도.

    joint_error_rate   모든 모델이 함께 틀린 뉴스의 비율 (관측값)
    independent_rate   각 모델이 독립이라면 기대되는 비율 (모델별 오답률의 곱)
    excess             둘의 차이. 0보다 크면 오류가 독립이 아니라 함께 움직인다
    same_wrong_rate    모든 모델이 '같은' 오답을 낸 뉴스의 비율
    homogenization     관측값을 기대값으로 나눈 비율. 1이면 독립과 같고 1보다 크면 함께 틀린다
                       (Bommasani 외 2022의 개인 수준 균질화 지표와 같은 정의)
    """
    answers = model_answers(runs)
    wrong = answers != truth[None, :]
    all_wrong = wrong.all(axis=0)
    same_answer = (answers == answers[0]).all(axis=0)
    joint = float(all_wrong.mean())
    independent = float(np.prod(wrong.mean(axis=1)))
    return {
        "joint_error_rate": joint,
        "independent_rate": independent,
        "excess": joint - independent,
        "homogenization": joint / independent if independent > 0 else float("nan"),
        "same_wrong_rate": float((all_wrong & same_answer).mean()),
    }


def co_flip(original: np.ndarray, perturbed: np.ndarray) -> dict:
    """④ 동반 뒤집힘: 입력을 변형했을 때 모델들이 같은 방향으로 함께 바뀌는 정도.

    flip_rate      모델·뉴스 쌍 중 답이 바뀐 비율
    co_flip_rate   뉴스별로 '가장 많은 모델이 택한 변화 방향'의 모델 비율을 평균한 값.
                   답이 바뀐 모델이 하나라도 있는 뉴스만 센다. 1이면 전원이 같은 쪽으로 움직였다.
    """
    delta = np.sign(model_answers(perturbed) - model_answers(original))
    moved = delta != 0
    up = (delta > 0).mean(axis=0)
    down = (delta < 0).mean(axis=0)
    dominant = np.maximum(up, down)
    any_moved = moved.any(axis=0)
    return {
        "flip_rate": float(moved.mean()),
        "co_flip_rate": float(dominant[any_moved].mean()) if any_moved.any() else 0.0,
    }


def pairwise_error_correlation(runs: np.ndarray, truth: np.ndarray) -> float:
    """③-b 모델 쌍별 오답 지표의 상관(phi)을 평균한 값.

    '전원이 함께 틀림'은 뉴스 100건에서 몇 건 안 나오므로 검정력이 낮다.
    이 값은 모든 모델 쌍을 쓰기 때문에 같은 표본에서 더 안정적이다.
    한 번도 안 틀리거나 전부 틀린 모델은 상관이 정의되지 않아 그 쌍을 뺀다.
    """
    wrong = error_matrix(runs, truth).astype(float)
    usable = wrong[wrong.std(axis=1) > 0]
    if len(usable) < 2:
        return float("nan")
    corr = np.corrcoef(usable)
    return float(corr[np.triu_indices(len(usable), k=1)].mean())


def permutation_test(
    runs: np.ndarray,
    truth: np.ndarray,
    strata: np.ndarray,
    n_perm: int = 2000,
    seed: int = 0,
) -> dict:
    """오류가 함께 움직이는 정도가 우연 수준을 넘는지 검정한다.

    귀무가설: 난이도 구간(strata)이 같으면 모델들의 오류는 서로 독립이다.
    각 모델의 오답 벡터를 구간 안에서만 따로 섞어 귀무 분포를 만든다.
    구간 안에서만 섞기 때문에 '어려운 뉴스라서 다 같이 틀림'은 귀무 분포에도 남는다.
    통계량은 모델 쌍별 오답 일치(둘 다 틀림)의 평균 건수다.
    """
    rng = np.random.default_rng(seed)
    wrong = error_matrix(runs, truth)
    n_models = wrong.shape[0]
    pairs = np.triu_indices(n_models, k=1)

    def stat(w: np.ndarray) -> float:
        both = w.astype(int) @ w.astype(int).T
        return float(both[pairs].mean())

    observed = stat(wrong)
    groups = [np.flatnonzero(strata == s) for s in np.unique(strata)]
    null = np.empty(n_perm)
    for i in range(n_perm):
        shuffled = wrong.copy()
        for m in range(n_models):
            for idx in groups:
                shuffled[m, idx] = wrong[m, rng.permutation(idx)]
        null[i] = stat(shuffled)
    return {
        "observed": observed,
        "null_mean": float(null.mean()),
        "p_value": float((1 + (null >= observed).sum()) / (1 + n_perm)),
    }


def bootstrap_ci(fn, n_items: int, n_boot: int = 2000, seed: int = 0, level: float = 0.95) -> tuple:
    """뉴스를 복원추출해 지표의 신뢰구간을 구한다.

    fn은 뉴스 인덱스 배열을 받아 지표 값 하나를 돌려주는 함수다.
    """
    rng = np.random.default_rng(seed)
    values = np.array([fn(rng.integers(0, n_items, n_items)) for _ in range(n_boot)])
    values = values[~np.isnan(values)]
    if len(values) == 0:  # 지표가 한 번도 정의되지 않음 (예: 틀린 판단이 없음)
        return float("nan"), float("nan")
    lo, hi = np.quantile(values, [(1 - level) / 2, (1 + level) / 2])
    return float(lo), float(hi)


def family_gap(runs: np.ndarray, truth: np.ndarray, families: list[str]) -> dict:
    """H2: 같은 개발사 모델 쌍의 오답 상관 평균에서 다른 개발사 쌍의 평균을 뺀 값.

    상관이 정의되지 않는 쌍(한쪽이 한 번도 안 틀림)은 뺀다.
    """
    wrong = error_matrix(runs, truth).astype(float)
    within, between = [], []
    for a in range(len(families)):
        for b in range(a + 1, len(families)):
            if wrong[a].std() == 0 or wrong[b].std() == 0:
                continue
            r = float(np.corrcoef(wrong[a], wrong[b])[0, 1])
            (within if families[a] == families[b] else between).append(r)
    w = float(np.mean(within)) if within else float("nan")
    b = float(np.mean(between)) if between else float("nan")
    return {"within": w, "between": b, "gap": w - b}


def wrong_answer_agreement(runs: np.ndarray, truth: np.ndarray) -> float:
    """두 모델이 같은 뉴스에서 둘 다 틀렸을 때, 같은 오답을 고른 비율. 모든 모델 쌍을 합쳐 계산한다.

    선행연구가 일반 벤치마크에서 보고한 값과 직접 비교하기 위한 지표다.
    둘 다 틀린 경우가 한 번도 없으면 NaN.
    """
    answers = model_answers(runs)
    wrong = answers != truth[None, :]
    both, same = 0, 0
    for a in range(len(answers)):
        for b in range(a + 1, len(answers)):
            mask = wrong[a] & wrong[b]
            both += int(mask.sum())
            same += int((answers[a][mask] == answers[b][mask]).sum())
    return same / both if both else float("nan")


# 방향은 -1/0/1 세 가지라 틀린 답은 두 가지다. 두 모델이 무작위로 틀린다면 같은 오답일 확률은 1/2이다.
# Kim 외(2025)의 Helm 자료는 보기 4개(틀린 답 3개)라 기준선이 1/3이고 관측값이 0.60이었다.
WRONG_AGREEMENT_BASELINE = 0.5


def tier_gap(runs: np.ndarray, truth: np.ndarray, tiers: list[str | None]) -> dict:
    """H7: 큰 모델끼리의 오답 상관 평균에서 작은 모델끼리의 평균을 뺀 값.

    Ross 외(2026)는 모델 성능이 높을수록 판단 오차의 상관이 커진다고 보고했다.
    패널이 회사마다 큰 모델 하나, 작은 모델 하나라서 두 묶음 모두 '다른 회사' 쌍만으로 이루어진다.
    등급이 없는 모델과, 상관이 정의되지 않는 쌍(한쪽이 한 번도 안 틀림)은 뺀다.
    """
    wrong = error_matrix(runs, truth).astype(float)
    pairs = {"large": [], "small": []}
    for a in range(len(tiers)):
        for b in range(a + 1, len(tiers)):
            if tiers[a] != tiers[b] or tiers[a] not in pairs:
                continue
            if wrong[a].std() == 0 or wrong[b].std() == 0:
                continue
            pairs[tiers[a]].append(float(np.corrcoef(wrong[a], wrong[b])[0, 1]))
    large = float(np.mean(pairs["large"])) if pairs["large"] else float("nan")
    small = float(np.mean(pairs["small"])) if pairs["small"] else float("nan")
    return {"large": large, "small": small, "gap": large - small}


def diversification(runs: np.ndarray, truth: np.ndarray) -> dict:
    """모델을 여러 개 써서 얻는 분산 효과가 오답 상관 때문에 얼마나 줄어드는가.

    오답 지표의 분산이 sigma2로 같고 쌍별 상관이 rho로 같다고 놓으면,
    모델 n개 평균의 분산은 sigma2 * (1 + (n-1) * rho) / n 이다. 신용 포트폴리오의 부도 상관과 같은 식이다.
      effective_models         n / (1 + (n-1) * rho). 상관된 모델 n개가 독립인 모델 몇 개와 같은가
      variance_floor           rho * sigma2. 모델을 아무리 늘려도 내려가지 않는 하한 (Ross 외 2026)
      floor_share_of_single    하한 / 단일 모델 분산 = rho
    두 가정(같은 분산, 같은 상관)은 근사다. 모델별 오답률이 크게 다르면 값이 어긋난다.
    """
    wrong = error_matrix(runs, truth).astype(float)
    n = len(wrong)
    rho = pairwise_error_correlation(runs, truth)
    sigma2 = float(np.mean(wrong.mean(axis=1) * (1 - wrong.mean(axis=1))))
    if np.isnan(rho):
        nan = float("nan")
        return {"n_models": n, "mean_error_correlation": nan, "effective_models": nan,
                "single_model_variance": sigma2, "panel_variance": nan, "variance_floor": nan}
    return {
        "n_models": n,
        "mean_error_correlation": rho,
        "effective_models": n / (1 + (n - 1) * rho) if 1 + (n - 1) * rho > 0 else float("nan"),
        "single_model_variance": sigma2,
        "panel_variance": sigma2 * (1 + (n - 1) * rho) / n,
        "variance_floor": rho * sigma2,
    }


def error_consistency(runs: np.ndarray, truth: np.ndarray) -> float:
    """정확도를 보정한 일치도(Geirhos 외 2020의 error consistency). 모든 모델 쌍의 평균.

    두 모델이 같은 뉴스에서 '둘 다 맞거나 둘 다 틀린' 비율에서, 각자의 정확도만으로 우연히 그렇게 될 비율을 뺀다.
        kappa = (관측 일치 - 기대 일치) / (1 - 기대 일치)
        기대 일치 = acc_a * acc_b + (1 - acc_a) * (1 - acc_b)
    0이면 정확도가 같은 독립인 두 모델 수준이고, 1이면 틀리는 뉴스가 완전히 같다.
    Goel 외(2025)의 CAPA는 여기에 답의 확률 분포를 더한 것이다. 우리는 확률을 받지 않으므로 이 값을 쓴다.
    쌍별 오답 상관(phi)과 같은 것을 재지만 선행연구와 같은 단위로 비교하려고 함께 보고한다.
    기대 일치가 1인 쌍(둘 다 한 번도 안 틀림, 또는 둘 다 전부 틀림)은 정의되지 않아 뺀다.
    """
    wrong = error_matrix(runs, truth)
    acc = 1 - wrong.mean(axis=1)
    values = []
    for a in range(len(wrong)):
        for b in range(a + 1, len(wrong)):
            expected = acc[a] * acc[b] + (1 - acc[a]) * (1 - acc[b])
            if expected >= 1:
                continue
            observed = float((wrong[a] == wrong[b]).mean())
            values.append((observed - expected) / (1 - expected))
    return float(np.mean(values)) if values else float("nan")


def _plurality_correct(answers: np.ndarray, truth: np.ndarray) -> np.ndarray:
    """뉴스별로 패널의 다수결이 정답인가. 가장 많이 나온 답이 하나뿐이고 그것이 정답일 때만 True. 동률은 틀린 것으로 센다."""
    out = np.zeros(answers.shape[1], dtype=bool)
    for j, column in enumerate(answers.T):
        values, counts = np.unique(column[~np.isnan(column)], return_counts=True)
        if len(values) and (counts == counts.max()).sum() == 1:
            out[j] = values[counts.argmax()] == truth[j]
    return out


def panel_value(runs: np.ndarray, truth: np.ndarray, strata: np.ndarray, n_shuffle: int = 500, seed: int = 0) -> dict:
    """모델을 여러 개 쓰는 것이 값어치가 있는가. 두 가지를 본다.

    1. 패널의 다수결이 가장 잘하는 모델 하나보다 나은가.
       가장 잘하는 모델은 결과를 보고 고르므로 이 비교는 모델 하나 쪽에 유리하다. 그런데도 패널이 낫지 않으면
       여러 모델을 쓰는 까닭이 정확도는 아니라는 뜻이다(가드에는 여전히 여러 모델이 필요하다).
    2. 모델들의 오답이 서로 독립이었다면 다수결이 얼마나 맞았을까(콩도르세 귀무 모형).
       각 모델의 답을 같은 층·같은 정답의 뉴스들 사이에서 모델마다 따로 섞는다. 모델별 정확도와 난이도별 정확도는
       그대로 두고, 같은 뉴스에서 함께 틀리는 것만 없앤다. 실제 정확도가 이보다 낮은 만큼이 함께 틀려서 잃은 것이다.

    "Nine Judges, Two Effective Votes"(arXiv:2605.29800)의 방법을 따랐다. 사전에 정한 가설이 아니므로 탐색용으로 보고한다.
    """
    answers = model_answers(runs)
    correct = answers == truth[None, :]
    by_model = correct.mean(axis=1)
    best = int(by_model.argmax())
    panel = _plurality_correct(answers, truth)
    ties = np.array([
        (lambda c: len(c) > 0 and (c == c.max()).sum() > 1)(np.unique(col[~np.isnan(col)], return_counts=True)[1]) for col in answers.T
    ])
    rng = np.random.default_rng(seed)
    groups = [np.flatnonzero((strata == s) & (truth == t)) for s in np.unique(strata) for t in np.unique(truth)]
    groups = [g for g in groups if len(g) > 1]
    null = []
    for _ in range(n_shuffle):
        shuffled = answers.copy()
        for idx in groups:
            for m in range(len(answers)):
                shuffled[m, idx] = answers[m, rng.permutation(idx)]
        null.append(_plurality_correct(shuffled, truth).mean())
    independent = float(np.mean(null))
    lo, hi = bootstrap_ci(lambda i: float(panel[i].mean() - correct[best, i].mean()), len(truth), seed=seed)
    return {
        "accuracy_by_model": [round(float(a), 3) for a in by_model],
        "best_single_model": best,
        "best_single_accuracy": round(float(by_model[best]), 3),
        "panel_majority_accuracy": round(float(panel.mean()), 3),
        "panel_minus_best": round(float(panel.mean() - by_model[best]), 3),
        "panel_minus_best_ci95": [round(lo, 3), round(hi, 3)],
        "tie_share": round(float(ties.mean()), 3),
        "accuracy_if_independent": round(independent, 3),
        "lost_to_shared_errors": round(independent - float(panel.mean()), 3),
    }
