"""학습하는 가드(G5): 패널의 판단이 틀렸을 확률을 로지스틱 회귀로 추정한다.

규칙 가드(G1~G4)는 사람이 정한 기준 하나로 통과와 검토를 가른다. G5는 여러 신호를 한꺼번에 보고
가중치를 데이터에서 배운다. 신용평가의 스코어카드와 같은 구조다.

    P(다수결 답이 틀림) = 1 / (1 + exp(-(b0 + b1·x1 + ... + bk·xk)))

변수는 두 묶음이다.
  행동 변수: 패널이 답하는 모습에서만 나온다. 바깥 정보를 쓰지 않는다.
  출처 변수: 글에 붙은 표기와, 같은 내용을 실은 글·독립 출처의 수.
G5a는 행동 변수만, G5b는 둘 다 쓴다. 둘을 비교하면 '패널의 행동만 보고도 틀린 판단을 알아챌 수 있는가'에 답할 수 있다.
"""

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, roc_auc_score
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from . import guard, metrics

BEHAVIOR = ["disagreement", "intra_dispersion", "family_split", "intensity_spread", "failed_share"]
SOURCE = ["tag_unverified", "echo_count", "few_independent"]


def behavior_features(direction: np.ndarray, intensity: np.ndarray, families: list[str]) -> np.ndarray:
    """뉴스마다 행동 변수 다섯 개를 만든다. 입력은 (모델, 뉴스, 반복) 배열 둘, 출력은 (뉴스, 5).

    disagreement      1 - (다수결 답을 고른 모델의 비율). 패널이 갈릴수록 크다
    intra_dispersion  같은 모델이 반복마다 낸 방향 답의 표준편차를 모델 평균한 값
    family_split      같은 개발사 모델끼리 답이 다른 개발사의 비율
    intensity_spread  모델별 강도 답의 표준편차. 방향은 같아도 크기 판단이 갈리는 정도
    failed_share      형식 위반으로 실패한 호출의 비율
    """
    answers = metrics.model_answers(direction)
    _, shares = guard.majority(answers)
    spread = np.nanstd(np.where(np.isnan(direction).all(axis=2, keepdims=True), 0.0, direction), axis=2)
    fams = sorted({f for f in families if families.count(f) > 1})
    split = np.zeros(answers.shape[1])
    for f in fams:
        members = answers[[i for i, x in enumerate(families) if x == f]]
        split += (members != members[0]).any(axis=0)
    strength = metrics.model_answers(intensity).astype(float)
    strength[strength == metrics.FAILED] = np.nan
    with np.errstate(invalid="ignore"):
        intensity_spread = np.nan_to_num(np.nanstd(strength, axis=0))
    return np.column_stack([
        1 - shares,
        spread.mean(axis=0),
        split / len(fams) if fams else split,
        intensity_spread,
        np.isnan(direction).mean(axis=(0, 2)),
    ])


def source_features(tag_verified: np.ndarray, n_reports: np.ndarray, n_independent: np.ndarray, k: int) -> np.ndarray:
    """출처 변수 세 개. (뉴스, 3).

    tag_unverified   글에 붙은 출처 표기가 미확인이면 1
    echo_count       받아쓴 글의 수 = 같은 내용을 실은 글 수 - 독립 출처 수
    few_independent  독립 출처가 k곳 미만이면 1
    """
    return np.column_stack([
        (~tag_verified.astype(bool)).astype(float),
        np.maximum(n_reports - n_independent, 0).astype(float),
        (n_independent < k).astype(float),
    ])


def fit(X: np.ndarray, y: np.ndarray):
    """표준화한 뒤 L2 벌점 로지스틱 회귀를 맞춘다. 정답이 한 종류뿐이면 배울 수 없으므로 None."""
    if len(np.unique(y)) < 2:
        return None
    return make_pipeline(StandardScaler(), LogisticRegression(C=1.0, max_iter=1000)).fit(X, y)


def coefficients(model, names: list[str]) -> dict:
    """표준화된 변수 기준의 계수. 절댓값이 클수록 그 변수가 판정에 크게 작용한다."""
    return dict(zip(names, model[-1].coef_[0].round(3).tolist()))


def recall_at_review_rate(score: np.ndarray, y: np.ndarray, rate: float) -> float:
    """점수가 높은 순으로 전체의 rate만큼만 검토로 넘겼을 때, 틀린 판단 중 잡힌 비율."""
    if not y.any():
        return float("nan")
    n = int(round(rate * len(score)))
    flagged = np.zeros(len(score), dtype=bool)
    flagged[np.argsort(-score, kind="stable")[:n]] = True
    return float((flagged & y.astype(bool)).sum() / y.sum())


def evaluate(model, X: np.ndarray, y: np.ndarray, rate: float) -> dict:
    score = model.predict_proba(X)[:, 1]
    return {
        "auc": _auc(y, score),
        "brier": round(float(brier_score_loss(y, score)), 3),
        "recall_at_review_rate": round(recall_at_review_rate(score, y, rate), 3),
        "n": int(len(y)),
        "n_wrong": int(y.sum()),
    }


def grouped_cv_auc(X: np.ndarray, y: np.ndarray, groups: np.ndarray, folds: int = 5) -> float:
    """같은 뉴스에서 나온 줄은 같은 조각에 넣고 교차검증한다.

    한 뉴스의 원본과 변형이 학습과 검증에 나뉘어 들어가면 성능이 부풀려진다.
    """
    score = np.full(len(y), np.nan)
    for train, test in GroupKFold(n_splits=folds).split(X, y, groups):
        model = fit(X[train], y[train])
        if model is not None:
            score[test] = model.predict_proba(X[test])[:, 1]
    ok = ~np.isnan(score)
    return _auc(y[ok], score[ok])


def _auc(y: np.ndarray, score: np.ndarray) -> float:
    """정답이 한 종류뿐이면 AUC가 정의되지 않는다."""
    return round(float(roc_auc_score(y, score)), 3) if len(np.unique(y)) == 2 else float("nan")


def auc_ci(y: np.ndarray, score: np.ndarray, groups: np.ndarray, n_boot: int = 2000, seed: int = 0) -> tuple:
    """AUC의 95% 신뢰구간. 줄이 아니라 뉴스를 단위로 다시 뽑는다.

    한 뉴스의 원본과 변형은 서로 닮았으므로, 줄 단위로 뽑으면 구간이 실제보다 좁게 나온다.
    """
    rng = np.random.default_rng(seed)
    ids = np.unique(groups)
    rows = {g: np.flatnonzero(groups == g) for g in ids}
    values = []
    for _ in range(n_boot):
        idx = np.concatenate([rows[g] for g in rng.choice(ids, len(ids))])
        if len(np.unique(y[idx])) == 2:
            values.append(roc_auc_score(y[idx], score[idx]))
    if not values:
        return float("nan"), float("nan")
    lo, hi = np.quantile(values, [0.025, 0.975])
    return round(float(lo), 3), round(float(hi), 3)
