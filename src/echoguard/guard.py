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


def g4_corroboration(answers: np.ndarray, threshold: float, n_independent_sources: np.ndarray, k: int = 2) -> np.ndarray:
    """G4: G1에 더해, 같은 사실을 따로 확인해 준 출처가 k곳 미만이면 검토.

    G2는 글에 붙은 출처 표기를 믿는다. G4는 표기를 보지 않고 내용이 다른 곳에서도 확인되는지를 본다.
    """
    return g1_agreement(answers, threshold) | (n_independent_sources < k)


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
