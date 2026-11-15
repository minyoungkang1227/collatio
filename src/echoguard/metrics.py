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
