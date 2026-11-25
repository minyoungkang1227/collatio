"""단위 환산 점검(G7): 답에 적힌 환산 전 값을 코드로 다시 환산해 최종 답과 맞춰 본다.

kfin_eval에서 가장 많이 나온 오답은 계산은 맞게 해 놓고 단위를 옮기다 자릿수를 틀린 것이었다
(백만원 → 억원에서 100이 아니라 10으로 나눔 등). 모델은 풀이에 환산 전 값을 대개 적어 둔다.
환산은 코드가 틀리지 않는 일이므로, 그 값을 코드로 환산해 최종 답과 비교한다.

정답을 몰라도 된다. 필요한 것은 물음이 요구한 단위와 모델의 풀이뿐이다.

판정
  어긋남    풀이에 적힌 다른 단위의 값을 환산하면 최종 답과 10의 거듭제곱만큼 차이 난다 → 검토
  일치      풀이에 적힌 다른 단위의 값을 환산하면 최종 답과 같다
  검사 안 함  풀이에 환산 전 값이 없거나, 다루지 않는 단위다

환산 전 값을 적지 않고 한 줄 계산식으로 답하는 모델도 있다("3,954,733 ÷ 1.326 ÷ 1,000 = 2.98245").
그런 경우는 적힌 계산식을 코드로 다시 계산해 적힌 결과와 맞춰 본다(recompute).

잡지 못하는 것: 풀이를 적지 않고 답만 낸 경우, 식을 잘못 세운 경우(식대로 계산하면 맞게 나온다).
"""

import ast
import math
import operator
import re
from dataclasses import dataclass

# 단위 → (종류, 기준 단위로 바꾸는 배수). 같은 종류끼리만 환산한다
KOREAN = {"": 1.0, "천": 1e3, "만": 1e4, "십만": 1e5, "백만": 1e6, "천만": 1e7, "억": 1e8, "십억": 1e9, "백억": 1e10, "천억": 1e11, "조": 1e12}
SI = {"": 1.0, "k": 1e3, "M": 1e6, "G": 1e9, "T": 1e12}
UNITS: dict[str, tuple[str, float]] = {}
for prefix, factor in KOREAN.items():
    for base in ("원", "명", "개", "건"):
        UNITS[prefix + base] = (base, factor)
for prefix, factor in SI.items():
    UNITS[prefix + "Wh"] = ("Wh", factor)
UNITS.update({"mg": ("g", 1e-3), "g": ("g", 1.0), "kg": ("g", 1e3), "t": ("g", 1e6), "톤": ("g", 1e6)})

_UNIT_RE = "|".join(sorted((re.escape(u) for u in UNITS), key=len, reverse=True))
# 숫자, 그 뒤에 (공백·괄호·수식 기호를 건너) 단위. '천 명'처럼 띄어 쓴 것도 읽는다
_MENTION = re.compile(
    # 숫자와 단위 사이는 같은 줄의 공백·괄호까지만 건넌다. 줄을 넘기면 "최종답: 2468.0 (빈 줄) 원금"을 2468원으로 읽는다
    r"(?<![\d.])(-?\d[\d,]*(?:\.\d+)?)(?:[ \t]*(?:\\ldots|…|\.\.\.))?[ \t()~≈약]*"
    # 한글 단위 뒤에는 조사가 바로 붙는다("백만원이며"). 다만 다른 낱말의 첫 글자인 경우는 뺀다(3개월, 원금, 건물, 명령)
    r"((?:십만|백만|천만|십억|백억|천억|천|만|억|조)?[ ]?(?:원(?![금가인칙래천화])|명(?![령목의세])|개(?![월선인발년별동])|건(?![물설전강수]))"
    # 로마자 단위는 뒤에 로마자가 이어지면 단위가 아니다("the")
    r"|톤|(?:[kMGT]?Wh|mg|kg|g|t)(?![A-Za-z]))"
)


@dataclass
class UnitCheck:
    status: str            # "어긋남" | "일치" | "검사 안 함"
    detail: str

    @property
    def flagged(self) -> bool:
        return self.status == "어긋남"


def _clean(text: str) -> str:
    """수식 표기를 걷어 낸다: 3{,}048.16 \\text{ (백만원)} → 3,048.16 (백만원)"""
    text = text.replace("{,}", ",").replace("\\,", "").replace("$", " ")
    text = re.sub(r"\\(?:text|mathrm|textbf)\s*\{([^{}]*)\}", r"\1", text)
    return text.replace("\\(", " ").replace("\\)", " ").replace("**", "")


def unit_of(name: str) -> tuple[str, float] | None:
    return UNITS.get(name.replace(" ", ""))


def mentions(text: str) -> list[tuple[float, str]]:
    """글에 '숫자 + 단위'로 적힌 것들. (값, 단위)"""
    out = []
    for number, unit in _MENTION.findall(_clean(text)):
        try:
            out.append((float(number.replace(",", "")), unit.replace(" ", "")))
        except ValueError:
            continue
    return out


def _shift(a: float, b: float, tol: float) -> int | None:
    """a가 b의 10^k배(k≠0)이면 k. 유효숫자가 같고 자릿수만 다른 경우다."""
    if a == 0 or b == 0 or (a > 0) != (b > 0):
        return None
    k = round(math.log10(abs(a) / abs(b)))
    if k != 0 and abs(abs(a) / (abs(b) * 10**k) - 1) <= tol:
        return k
    return None


def check(response: str, target_unit: str, final: float, tol: float = 0.01) -> UnitCheck:
    """풀이(response)에 적힌 환산 전 값이 최종 답(final, target_unit 단위)과 맞는지 본다."""
    target = unit_of(target_unit)
    if target is None:
        return UnitCheck("검사 안 함", f"다루지 않는 단위: {target_unit}")
    kind, to_base = target
    others = []
    for value, unit in mentions(response):
        info = unit_of(unit)
        if info and info[0] == kind and info[1] != to_base:
            others.append((value, unit, value * info[1] / to_base))
    if not others:
        return UnitCheck("검사 안 함", "풀이에 환산 전 값(다른 단위로 적은 값)이 없음")
    for value, unit, converted in others:
        if abs(converted - final) <= tol * abs(final) + 1e-12:
            return UnitCheck("일치", f"{value:,.10g}{unit} = {converted:,.6g}{target_unit}")
    for value, unit, converted in reversed(others):   # 최종 답에 가까운 쪽부터
        k = _shift(final, converted, tol)
        if k is not None:
            return UnitCheck(
                "어긋남",
                f"풀이의 {value:,.10g}{unit}은 {converted:,.6g}{target_unit}인데 최종 답은 {final:,.6g}{target_unit} (10의 {k:+d}제곱 차이)",
            )
    return UnitCheck("검사 안 함", "환산 전 값으로 볼 만한 것이 풀이에 없음")


_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}
_EQUATION = re.compile(r"(?<![\w.,])([\d(][\d.\s()+\-*/]*[\d)])\s*(?:=|≈)\s*(-?\d+(?:\.\d+)?)")


def _value(node) -> float:
    """사칙연산과 괄호, 숫자만으로 된 식의 값. 그 밖의 것이 있으면 ValueError."""
    if isinstance(node, ast.Expression):
        return _value(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return float(node.value)
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_value(node.left), _value(node.right))
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -_value(node.operand)
    raise ValueError("사칙연산이 아님")


def equations(text: str) -> list[tuple[str, float, float]]:
    """글에 적힌 '계산식 = 결과'들. (식, 코드로 계산한 값, 글에 적힌 결과)

    모델의 출력을 실행하지 않는다. 숫자와 사칙연산, 괄호만 남긴 식을 구문 나무로 읽어 직접 계산한다.
    """
    t = _clean(text)
    for old, new in (("\\div", "/"), ("÷", "/"), ("\\times", "*"), ("\\cdot", "*"), ("×", "*"), ("·", "*"), ("−", "-"), ("\\approx", "≈")):
        t = t.replace(old, new)
    t = re.sub(r"(?<=\d),(?=\d{3})", "", t)
    out = []
    for m in _EQUATION.finditer(t):
        expr, stated = m.group(1), m.group(2)
        if not re.search(r"[+\-*/]", expr.strip()[1:]) or len(expr) > 200:
            continue
        # 식의 앞부분이 잘린 경우는 버린다: "2,000만원 × (1 + 0.078 × 3) = 2,468" 에서 괄호 안만 읽히면 안 된다
        if re.search(r"[+\-*/]\s*$", t[: m.start(1)]):
            continue
        try:
            got = _value(ast.parse(expr.strip(), mode="eval"))
        except (SyntaxError, ValueError, ZeroDivisionError, RecursionError):
            continue
        out.append((" ".join(expr.split()), got, float(stated)))
    return out


def recompute(response: str, tol: float = 0.01) -> UnitCheck:
    """풀이에 적힌 계산식을 다시 계산한다. 적힌 결과와 자릿수가 어긋난 식이 있으면 '어긋남'."""
    found = equations(response)
    if not found:
        return UnitCheck("검사 안 함", "풀이에 다시 계산할 식이 없음")
    for expr, got, stated in found:
        k = _shift(stated, got, tol)
        if k is not None:
            return UnitCheck("어긋남", f"{expr} 는 {got:,.6g}인데 풀이에는 {stated:,.6g}로 적힘 (10의 {k:+d}제곱 차이)")
    return UnitCheck("일치", f"식 {len(found)}개에서 자릿수가 어긋난 곳 없음")
