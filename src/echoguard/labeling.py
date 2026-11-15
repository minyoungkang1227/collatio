"""규칙 라벨: 잠정실적 공시는 적힌 숫자에서 강도와 방향을 계산한다.

사람이 눈으로 점수를 매기면 틀릴 수 있고, 틀린 정답은 "여러 모델이 함께 틀렸다"는 가짜 신호를 만든다.
숫자가 있는 공시는 숫자만 옮겨 적고 판정은 이 규칙이 한다. 기준은 prompts/institutional_system.txt의 강도표와 같다.
"""

TURNS = ("없음", "적자전환", "흑자전환", "적자지속")


def rule_label(op_yoy_pct: float | None, op_turn: str | None) -> tuple[int, int] | None:
    """(강도, 방향)을 돌려준다. 규칙으로 정할 수 없으면 None이고 그 건은 사람이 붙인다.

    op_yoy_pct: 영업이익의 전년 동기 대비 변동률(%). 32% 감소면 -32.
    op_turn: 적자전환이면 (4, -1), 흑자전환이면 (4, 1). 적자지속은 변동률의 뜻이 모호해 규칙을 쓰지 않는다.
    """
    turn = op_turn or "없음"
    if turn not in TURNS:
        raise ValueError(f"op_turn은 {TURNS} 중 하나여야 합니다: {op_turn}")
    if turn == "적자전환":
        return 4, -1
    if turn == "흑자전환":
        return 4, 1
    if turn == "적자지속" or op_yoy_pct is None:
        return None
    size = abs(op_yoy_pct)
    intensity = 4 if size >= 30 else 3 if size >= 10 else 2
    direction = (op_yoy_pct > 0) - (op_yoy_pct < 0)
    return intensity, direction
