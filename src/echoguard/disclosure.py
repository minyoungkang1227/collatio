"""잠정실적 공시: 옮겨 적은 숫자에서 요약, 정답, 뒤집은 글을 만든다.

사람은 공시의 숫자만 옮긴다. 요약 문장과 사실을 뒤집은 글은 여기서 만들기 때문에
누가 돌려도 같은 글이 나오고, 뒤집은 글의 앞뒤가 어긋나지 않는다.

요약에는 공시의 숫자를 여러 개 넣는다(당해 분기와 누계, 전년 동기 대비와 전기 대비, 매출·영업이익·순이익).
이 숫자들은 자주 엇갈린다. 판단 기준은 지시문에 정해 둔 하나, 당해 분기 영업이익의 전년 동기 대비 변동이다.
"""

import re
from datetime import date as Date
from typing import Literal

from pydantic import BaseModel, field_validator

from .dataset import NewsItem
from .labeling import rule_label
from .schema import PRESCRIBED_METRIC

TURNS = ("흑자전환", "적자전환", "적자지속")
Change = float | Literal["흑자전환", "적자전환", "적자지속"]

PRESCRIBED = PRESCRIBED_METRIC


class Disclosure(BaseModel):
    item_id: str
    corp: str
    date: str               # 공시일 YYYY-MM-DD
    period: str             # 예: 2026년 3분기
    unit: Literal["백만원", "억원"]
    url: str
    revenue: float          # 당해 분기 금액. 손실은 음수
    revenue_yoy: Change     # 전년 동기 대비. 32% 감소면 -32
    revenue_qoq: Change     # 전기 대비
    op: float
    op_yoy: Change
    op_qoq: Change
    net: float
    net_yoy: Change
    cum_op: float | None = None      # 누계 영업이익. 1분기 공시처럼 누계가 따로 없으면 비운다
    cum_op_yoy: Change | None = None
    n_independent_sources: int = 1   # 공시 원문 자체를 1로 센다
    n_reports: int = 1

    @field_validator("revenue_yoy", "revenue_qoq", "op_yoy", "op_qoq", "net_yoy", "cum_op_yoy", mode="before")
    @classmethod
    def _change(cls, v):
        """'-32', '-32%', -32.0 은 숫자로, '흑자전환' 같은 말은 그대로 둔다."""
        if isinstance(v, str):
            s = v.strip().replace("%", "").replace(",", "")
            if s in TURNS:
                return s
            try:
                return float(s)
            except ValueError:
                return v  # 형식 검사에서 걸리게 둔다
        return v


def direction_of(change: Change | None) -> int | None:
    """변동이 가리키는 방향. 적자지속은 변동률의 뜻이 모호해 방향을 정하지 않는다."""
    if change is None or change == "적자지속":
        return None
    if isinstance(change, str):
        return 1 if change == "흑자전환" else -1
    return (change > 0) - (change < 0)


def conflicts(d: Disclosure) -> list[str]:
    """기준 지표(영업이익 전년 동기 대비)와 반대 방향을 가리키는 다른 지표의 이름들."""
    key = direction_of(d.op_yoy)
    others = {
        "영업이익_전기대비": d.op_qoq,
        "매출_전년동기대비": d.revenue_yoy,
        "매출_전기대비": d.revenue_qoq,
        "순이익_전년동기대비": d.net_yoy,
        "누계영업이익_전년동기대비": d.cum_op_yoy,
    }
    return [name for name, c in others.items() if (o := direction_of(c)) not in (None, 0) and key not in (None, 0) and o != key]


def _num(x: float) -> str:
    return f"{x:,.2f}".rstrip("0").rstrip(".")


def change_phrase(c: Change) -> str:
    if isinstance(c, str):
        return c
    if c == 0:
        return "변동 없음"
    return f"{_num(abs(c))}% {'증가' if c > 0 else '감소'}"


def _line(label_gain: str, label_loss: str, amount: float, unit: str, changes: list[tuple[str, Change]]) -> str:
    name = label_gain if amount >= 0 else label_loss
    detail = ", ".join(f"{basis} {change_phrase(c)}" for basis, c in changes)
    return f"{name}은 {_num(abs(amount))}{unit}({detail})이다."


def render(d: Disclosure) -> str:
    """모델에 넣을 요약. 문장의 순서와 꼴은 모든 공시에서 같다."""
    y, m, day = (int(x) for x in d.date.split("-"))
    Date(y, m, day)  # 날짜가 실제로 있는지 확인
    parts = [
        f"{y}년 {m}월 {day}일 공시된 {d.corp}의 {d.period} 잠정실적이다.",
        "당해 분기 " + _line("매출액", "매출액", d.revenue, d.unit, [("전년 동기 대비", d.revenue_yoy), ("전기 대비", d.revenue_qoq)]),
        "당해 분기 " + _line("영업이익", "영업손실", d.op, d.unit, [("전년 동기 대비", d.op_yoy), ("전기 대비", d.op_qoq)]),
        "당해 분기 " + _line("순이익", "순손실", d.net, d.unit, [("전년 동기 대비", d.net_yoy)]),
    ]
    if d.cum_op is not None and d.cum_op_yoy is not None:
        parts.append("누계 " + _line("영업이익", "영업손실", d.cum_op, d.unit, [("전년 동기 대비", d.cum_op_yoy)]))
    return " ".join(parts)


def flipped(d: Disclosure) -> Disclosure | None:
    """기준 지표 하나만 반대로 바꾼 공시. 앞뒤가 맞게 뒤집을 수 없으면 None.

    뒤집는 것은 당해 분기 영업이익의 전년 동기 대비 변동률의 부호뿐이다. 금액과 다른 숫자는 그대로다.
    전년 동기 금액은 글에 없으므로 부호를 바꿔도 글 안에서 모순이 생기지 않는다.
    뒤집지 않는 경우:
      흑자전환·적자전환   금액의 부호까지 바꿔야 하는데, 그러면 전기 대비·누계 숫자와 어긋난다
      100% 넘는 증가      100% 넘는 감소는 불가능한 숫자다
      변동 없음           뒤집을 방향이 없다
    """
    c = d.op_yoy
    if isinstance(c, str) or c == 0 or c > 100:
        return None
    return d.model_copy(update={"op_yoy": -c})


def key_figure(d: Disclosure) -> Change:
    """글에 적힌 기준 지표의 값. 근거 검사 가드가 모델이 댄 값과 대조한다."""
    return d.op_yoy


def matches(basis_value: str | None, figure: Change) -> bool:
    """모델이 근거로 댄 값이 글에 적힌 기준 지표의 값과 같은가.

    '-51.3%', '51.3% 감소', '51.3 감소' 를 같은 값으로 본다. 전환은 말이 들어 있으면 맞은 것으로 본다.
    """
    if not basis_value:
        return False
    if isinstance(figure, str):
        return figure in basis_value.replace(" ", "")
    found = re.search(r"-?\d[\d,]*\.?\d*", basis_value)
    if not found:
        return False
    number = float(found.group().replace(",", ""))
    negative = number < 0 or "감소" in basis_value or "하락" in basis_value or "줄" in basis_value
    value = -abs(number) if negative else abs(number)
    return abs(value - figure) < 0.05


def to_news_item(d: Disclosure, labeler: str) -> NewsItem:
    """공시 한 건을 라벨 파일의 한 줄로 바꾼다. 정답과 난이도는 숫자에서 정해진다."""
    if d.op_yoy == "적자지속":
        raise ValueError(f"{d.item_id}: 영업이익이 적자지속인 공시는 기준 지표의 방향이 정해지지 않아 쓰지 않습니다")
    turn = d.op_yoy if isinstance(d.op_yoy, str) else None
    pct = None if turn else float(d.op_yoy)
    intensity, direction = rule_label(pct, turn)
    against = conflicts(d)
    basis = f"당해 분기 영업이익 전년 동기 대비 {change_phrase(d.op_yoy)}."
    basis += f" 반대 방향 지표: {', '.join(against)}." if against else " 반대 방향 지표 없음."
    return NewsItem(
        item_id=d.item_id, date=d.date, type="stock", source="전자공시", url=d.url,
        title=f"{d.corp}, {d.period} 영업(잠정)실적 공시", summary=render(d),
        intensity_true=intensity, direction_text=direction,
        difficulty="ambiguous" if against else "clear", label_basis=basis,
        source_verified=True, n_independent_sources=d.n_independent_sources, n_reports=d.n_reports,
        labeler=labeler, label_method="rule", op_yoy_pct=pct, op_turn=turn or "없음",
    )


def figure_in_text(item: NewsItem, perturbation: str) -> Change | None:
    """그 입력의 글에 적힌 기준 지표의 값. 숫자에서 만든 공시가 아니면 None이다.

    사실을 뒤집은 글과 그것을 여러 건 보도로 꾸민 글에는 뒤집힌 값이 적혀 있다.
    """
    if item.label_method != "rule":
        return None
    if item.op_turn in ("흑자전환", "적자전환"):
        return item.op_turn
    if item.op_yoy_pct is None:
        return None
    flipped_text = perturbation in ("fact_flip", "fake_corroboration")
    return -item.op_yoy_pct if flipped_text else item.op_yoy_pct


def basis_ok(output, figure: Change) -> bool:
    """모델의 근거가 지침대로인가: 정해진 지표를 댔고, 값이 글과 같고, 방향 답이 그 값과 어긋나지 않는다."""
    if output.basis_metric != PRESCRIBED or not matches(output.basis_value, figure):
        return False
    return output.direction == direction_of(figure)
