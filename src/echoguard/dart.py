"""전자공시의 잠정실적 공시 원문에서 숫자를 읽는다.

사람이 표를 보고 옮기면 옮기는 과정에서 틀리고, AI에게 시키면 채점 대상이 입력을 만들게 된다.
거래소의 잠정실적 공시는 양식이 정해져 있으므로 코드가 표를 그대로 읽는다.

읽는 것: 매출액·영업이익·당기순이익의 당해 분기 실적, 전기 대비와 전년 동기 대비 증감율, 흑자·적자 전환 여부,
영업이익의 누계 실적과 그 증감율. 분기와 단위는 표의 '실적기간'과 '단위'에서 읽는다.

공시는 손실이 이어진 경우에도 증감율을 숫자로 적는다(전환 여부 칸은 비운다). 손실에서 손실로 간 경우의 증감율은
방향의 뜻이 모호하므로, 당기와 비교 시점의 금액이 둘 다 손실이면 '적자지속'으로 바꿔 적는다.

읽으면서 표 안의 숫자끼리 맞는지도 본다: 적힌 증감율이 금액에서 계산한 값과 같은지, 전환 여부가 금액의 부호와 맞는지.
"""

import re
from dataclasses import dataclass, field

from .disclosure import Change, Disclosure

TURNS = ("흑자전환", "적자전환")


@dataclass
class Parsed:
    disclosure: Disclosure | None
    notes: list[str] = field(default_factory=list)      # 알아 둘 것 (정정 공시, 자회사 공시, 별도 기준 등)
    problems: list[str] = field(default_factory=list)   # 표 안에서 어긋난 곳, 읽지 못한 곳


def _cells(row: str) -> list[str]:
    cells = re.findall(r"<T[DHEU][^>]*>(.*?)</T[DHEU]>", row, flags=re.S | re.I)
    return [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", c).replace("&nbsp;", " ")).strip() for c in cells]


def rows_of(xml: str) -> list[list[str]]:
    return [c for c in (_cells(r) for r in re.findall(r"<TR[^>]*>(.*?)</TR>", xml, flags=re.S | re.I)) if c]


def _number(text: str) -> float | None:
    s = text.replace(",", "").replace("%", "").strip()
    if s in ("", "-"):
        return None
    if re.fullmatch(r"\(\d+(\.\d+)?\)", s):  # (123) 은 음수 표기
        s = "-" + s[1:-1]
    try:
        return float(s)
    except ValueError:
        return None


def _change(current: float, base: float | None, pct: str, turn: str, label: str, problems: list[str]) -> Change | None:
    """증감을 정한다. 전환 여부가 적혀 있으면 그것을, 둘 다 손실이면 적자지속을, 아니면 적힌 증감율을 쓴다."""
    stated, word = _number(pct), turn.strip()
    if base is None:
        if word in TURNS:
            return word
        return stated
    expected = "흑자전환" if current >= 0 > base else "적자전환" if current < 0 <= base else None
    if word in TURNS:
        if word != expected:
            problems.append(f"{label}: 전환 여부가 '{word}'인데 금액은 {base:,.0f} → {current:,.0f}이다")
        return word
    if expected:
        problems.append(f"{label}: 금액은 {base:,.0f} → {current:,.0f}로 {expected}인데 전환 여부가 비어 있다")
        return expected
    if current < 0 and base < 0:
        return "적자지속"
    if stated is None:
        if base != 0:
            problems.append(f"{label}: 증감율이 비어 있다")
        return None
    if base != 0:
        computed = (current - base) / abs(base) * 100
        # 금액은 단위로 반올림되어 있다(±0.5). 그 오차가 증감율에 얼마나 번지는지를 허용 폭으로 쓴다
        slack = 0.15 + 55 * (abs(current) / base**2 + 1 / abs(base))
        if abs(computed - stated) > slack:
            problems.append(f"{label}: 적힌 증감율 {stated:g}%가 금액에서 계산한 {computed:.2f}%와 다르다")
    return stated


def parse(xml: str, rcept_no: str, item_id: str, company: str = "") -> Parsed:
    """공시 원문 한 건을 읽는다. company는 공시를 낸 회사 이름(후보 목록의 것)."""
    notes, problems = [], []
    rows = rows_of(xml)
    flat = [" ".join(r) for r in rows]

    if any(r and r[0] == "정정일자" for r in rows):
        notes.append("정정 공시다. 정정 후의 표를 읽었다")
    sub = next((r[1] for r in rows if len(r) >= 3 and r[0].startswith("자회사인")), None)
    corp = f"{sub}({company}의 자회사)" if sub else company
    if sub:
        notes.append(f"자회사 {sub}의 실적을 지주사가 공시한 것이다")
    section = next((t for t in flat if re.search(r"1\.\s*(연결)?실적내용", t)), "")
    if section and "연결" not in section:
        notes.append("연결이 아닌 별도 기준 실적이다")

    unit = next((m.group(1) for t in flat if (m := re.search(r"단위\s*:\s*(백만원|억원|천원|원)\b", t))), None)
    if unit not in ("백만원", "억원"):
        return Parsed(None, notes, problems + [f"단위를 읽지 못했거나 다루지 않는 단위다: {unit}"])

    spans = {r[0]: (r[1], r[3]) for r in rows if len(r) == 4 and r[2] == "~" and re.fullmatch(r"\d{4}-\d{2}-\d{2}", r[1])}
    if "당기실적" not in spans:
        return Parsed(None, notes, problems + ["실적기간 표를 찾지 못했다"])
    start, end = spans["당기실적"]
    cum_start = spans.get("당기누계실적", (start, end))[0]
    months = (int(end[:4]) - int(cum_start[:4])) * 12 + int(end[5:7]) - int(cum_start[5:7]) + 1
    if months % 3 or not 3 <= months <= 12 or (int(end[5:7]) - int(start[5:7])) % 12 != 2:
        return Parsed(None, notes, problems + [f"분기 실적이 아니다: 당기 {start}~{end}, 누계 시작 {cum_start}"])
    quarter = months // 3
    period = f"{cum_start[:4]}년 {quarter}분기"

    def table(name: str) -> tuple[list[str] | None, list[str] | None]:
        """항목의 당해실적 줄과 그 바로 아래 누계실적 줄."""
        for i, r in enumerate(rows):
            if len(r) >= 9 and r[0] == name and r[1] == "당해실적":
                nxt = rows[i + 1] if i + 1 < len(rows) and rows[i + 1][0] == "누계실적" else None
                return r, nxt
        return None, None

    def read(name: str) -> dict | None:
        cur, cum = table(name)
        if cur is None or _number(cur[2]) is None:
            return None
        amount = _number(cur[2])
        out = {
            "amount": amount,
            "qoq": _change(amount, _number(cur[3]), cur[4], cur[5], f"{name} 전기 대비", problems),
            "yoy": _change(amount, _number(cur[6]), cur[7], cur[8], f"{name} 전년 동기 대비", problems),
            "cum": None, "cum_yoy": None,
        }
        if cum is not None and len(cum) >= 8 and _number(cum[1]) is not None:
            out["cum"] = _number(cum[1])
            out["cum_yoy"] = _change(out["cum"], _number(cum[5]), cum[6], cum[7], f"{name} 누계 전년 동기 대비", problems)
        return out

    revenue, op, net = read("매출액"), read("영업이익"), read("당기순이익")
    for name, value in (("매출액", revenue), ("영업이익", op)):
        if value is None:
            return Parsed(None, notes, problems + [f"{name}의 당해실적을 읽지 못했다"])
        for key, label in (("qoq", "전기 대비"), ("yoy", "전년 동기 대비")):
            if value[key] is None:
                return Parsed(None, notes, problems + [f"{name}의 {label} 증감을 읽지 못했다"])
    if net is None or net["yoy"] is None:
        notes.append("당기순이익이 적혀 있지 않다")
        net = None
    data = dict(
        item_id=item_id, corp=corp, date=f"{rcept_no[:4]}-{rcept_no[4:6]}-{rcept_no[6:8]}", period=period, unit=unit,
        url=f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}",
        revenue=revenue["amount"], revenue_yoy=revenue["yoy"], revenue_qoq=revenue["qoq"],
        op=op["amount"], op_yoy=op["yoy"], op_qoq=op["qoq"],
    )
    if net:
        data.update(net=net["amount"], net_yoy=net["yoy"])
    if quarter > 1 and op["cum"] is not None and op["cum_yoy"] is not None:
        data.update(cum_op=op["cum"], cum_op_yoy=op["cum_yoy"])
    try:
        return Parsed(Disclosure(**data), notes, problems)
    except ValueError as e:
        return Parsed(None, notes, problems + [f"읽은 값이 형식에 맞지 않는다: {str(e)[:120]}"])
