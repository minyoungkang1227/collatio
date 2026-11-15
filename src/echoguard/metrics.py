"""측정 엔진. LLM을 쓰지 않는 순수 계산이다.

입력 배열의 모양은 모두 (모델 수, 뉴스 수, 반복 수)이고 값은 순서형 정수다.
"""

import krippendorff
import numpy as np


def model_answers(runs: np.ndarray) -> np.ndarray:
    """반복을 모델별 대표 답 하나로 줄인다. 모양 (모델, 뉴스).

    중앙값을 쓰되 짝수 반복에서 .5가 나오면 아래쪽 값으로 내린다.
    """
    return np.floor(np.median(runs, axis=2)).astype(int)


def intra_model_dispersion(runs: np.ndarray) -> np.ndarray:
    """① 모델 내 분산: 같은 모델이 같은 뉴스에 얼마나 흔들리는지. 모델별 평균 표준편차."""
    return runs.std(axis=2).mean(axis=1)


def inter_model_agreement(runs: np.ndarray) -> float:
    """② 모델 간 일치도: 대표 답에 대한 순서형 Krippendorff α. 1이면 완전 일치."""
    answers = model_answers(runs)
    if np.unique(answers).size == 1:
        return 1.0  # 값이 하나뿐이면 α가 정의되지 않으므로 완전 일치로 둔다
    return float(
        krippendorff.alpha(
            reliability_data=answers.astype(float),
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
