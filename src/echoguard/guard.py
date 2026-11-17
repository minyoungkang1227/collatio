"""가드층: 패널의 답을 그대로 내보낼지 사람 검토로 넘길지 정한다.

입력은 모델별 대표 답 (모델, 뉴스) 배열이다. True는 '검토로 넘김'이다.
"""

import numpy as np


def majority(answers: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """뉴스별 다수결 답과 그 답을 고른 모델의 비율. 동률이면 작은 값을 택한다."""
    winners, shares = [], []
    for column in answers.T:
        values, counts = np.unique(column, return_counts=True)
        winners.append(values[counts.argmax()])
        shares.append(counts.max() / len(column))
    return np.array(winners), np.array(shares)


def g1_agreement(answers: np.ndarray, threshold: float) -> np.ndarray:
    """G1: 모델들이 갈리면 검토."""
    return majority(answers)[1] < threshold


def g2_agreement_source(answers: np.ndarray, threshold: float, source_verified: np.ndarray) -> np.ndarray:
    """G2: G1에 더해, 일치하더라도 출처가 확인되지 않았으면 검토."""
    return g1_agreement(answers, threshold) | ~source_verified.astype(bool)


def g3_probe(answers: np.ndarray, probe_answers: np.ndarray, threshold: float) -> np.ndarray:
    """G3: G1에 더해, 문체만 바꿔 다시 물었을 때 다수결 답이 바뀌면 검토."""
    return g1_agreement(answers, threshold) | (majority(answers)[0] != majority(probe_answers)[0])


def g4_corroboration(
    answers: np.ndarray, threshold: float, n_sources: np.ndarray, k: int = 2, primary: np.ndarray | None = None
) -> np.ndarray:
    """G4: G1에 더해, 같은 내용을 확인해 준 출처가 k곳 미만이면 검토.

    primary를 주면 1차 출처(공시·정부 발표)가 실제로 확인된 뉴스는 출처 수와 상관없이 통과시킨다.
    공시 원문 하나로 확인되는 정상 뉴스에 경보가 울리지 않게 하려는 것이다. G4b에만 쓴다.

    G2는 글에 붙은 출처 표기를 믿는다. G4는 표기를 보지 않고 내용이 다른 곳에서도 확인되는지를 본다.
    무엇을 세느냐로 둘로 갈린다.
      G4a: n_sources에 글의 수(n_reports)를 넣는다. 받아쓴 글도 하나로 센다.
      G4b: n_sources에 독립 출처의 수(n_independent_sources)를 넣는다.
    """
    few = n_sources < k
    if primary is not None:
        few = few & ~primary.astype(bool)
    return g1_agreement(answers, threshold) | few


def g6_basis(answers: np.ndarray, threshold: float, basis_share: np.ndarray, min_models: float = 1.0) -> np.ndarray:
    """G6: G1에 더해, 근거가 지침과 어긋난 모델이 있으면 검토.

    basis_share는 (모델, 뉴스) 배열이고 각 칸은 그 모델의 반복 중 근거가 지침대로였던 비율이다.
    반복의 절반 이상이 지침대로면 그 모델은 통과로 본다. 통과한 모델의 비율이 min_models에 못 미치면 검토로 넘긴다.
    답이 전부 같아도, 엉뚱한 숫자를 근거로 댔거나 근거와 답이 어긋나면 잡힌다.
    기준 지표의 값을 알 수 없는 뉴스(NaN)에는 이 검사를 적용하지 않고 G1만 본다.
    """
    known = ~np.isnan(basis_share).all(axis=0)
    passed = np.nan_to_num(basis_share, nan=0.0) >= 0.5
    fails = known & (passed.mean(axis=0) < min_models)
    return g1_agreement(answers, threshold) | fails


def evaluate(flagged: np.ndarray, answers: np.ndarray, truth: np.ndarray) -> dict:
    """가드 성능. 잡아야 할 것은 '다수결 답이 틀린 뉴스'다."""
    wrong = majority(answers)[0] != truth
    caught = flagged & wrong
    return {
        "recall": float(caught.sum() / wrong.sum()) if wrong.any() else float("nan"),
        "precision": float(caught.sum() / flagged.sum()) if flagged.any() else float("nan"),
        "review_rate": float(flagged.mean()),
        "n_wrong": int(wrong.sum()),
    }
