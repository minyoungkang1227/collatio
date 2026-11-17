"""필터: 문서 한 건에 대한 패널의 답을 그 자리에서 통과 또는 검토로 판정한다.

    python -m echoguard.filter --mock                 # 모의 모델로 예시 세 건
    python -m echoguard.filter --numbers 공시.json     # 공시 숫자 한 건을 실제 모델에 묻고 판정 (API 키와 비용 필요)

pipeline은 실험이다. 정답을 알고 있는 뉴스 여러 건으로 가드가 얼마나 잘 잡는지 잰다.
이 모듈은 그 가드를 실제로 쓰는 창구다. 정답을 모르는 문서 한 건을 받아 판정과 이유를 돌려준다.
판정 규칙은 guard.py의 함수를 그대로 부른다. 실험에서 잰 것과 여기서 쓰는 것이 같아야 하기 때문이다.

답을 고치지 않는다. 걸러서 사람에게 넘길 뿐이다.
"""

import argparse
import json
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import yaml

from . import guard
from .disclosure import PRESCRIBED, Change, Disclosure, basis_ok, change_phrase, key_figure, render
from .panel import ModelClient, call_once
from .perturb import VERIFIED_TAG, PanelInput
from .schema import InstitutionalOutput

ROOT = Path(__file__).resolve().parents[2]


@dataclass
class Check:
    guard: str          # 어느 검사인가
    ran: bool           # 필요한 정보가 있어서 검사를 했는가
    flagged: bool       # 걸렸는가
    detail: str         # 사람이 읽을 한 줄


@dataclass
class Verdict:
    decision: str                   # "통과" 또는 "검토"
    direction: int | None           # 패널의 다수결 방향. 답이 하나도 없으면 None
    agreement: float                # 그 방향을 고른 모델의 비율
    checks: list[Check] = field(default_factory=list)

    @property
    def reasons(self) -> list[str]:
        return [c.detail for c in self.checks if c.flagged]


def _representative(outputs: list[InstitutionalOutput]) -> int:
    """한 모델이 여러 번 답한 방향 중 가장 많이 나온 것. 동률이면 작은 값."""
    counts = Counter(o.direction for o in outputs)
    top = max(counts.values())
    return min(d for d, c in counts.items() if c == top)


def screen(
    outputs: dict[str, list[InstitutionalOutput | None]],
    *,
    figure: Change | None = None,
    primary_verified: bool | None = None,
    n_independent: int | None = None,
    threshold: float = 0.8,
    k_sources: int = 2,
) -> Verdict:
    """패널의 답을 판정한다.

    outputs           모델 이름 → 그 모델의 반복 답들. 형식이 틀려 실패한 답은 None
    figure            글에 적힌 기준 지표의 값. 알면 근거 대조(G6)를 한다
    primary_verified  1차 출처(공시·정부 발표) 원문을 실제로 확인했는가. 글에 붙은 표기가 아니다
    n_independent     같은 사실을 따로 확인해 준 독립 출처 수

    출처 정보나 기준 값을 주지 않으면 그 검사는 하지 않고, 하지 않았다고 적는다.
    검사를 하지 않은 것은 통과가 아니다. 호출하는 쪽이 checks의 ran을 보고 판단한다.
    """
    valid = {m: [o for o in runs if o is not None] for m, runs in outputs.items()}
    silent = [m for m, runs in valid.items() if not runs]
    answered = {m: runs for m, runs in valid.items() if runs}
    checks = [Check("응답", True, bool(silent), f"답을 내지 못한 모델: {', '.join(silent)}" if silent else "모든 모델이 답함")]
    if not answered:
        return Verdict("검토", None, 0.0, checks)

    answers = np.array([[_representative(runs)] for runs in answered.values()])
    winner, share = (x[0] for x in guard.majority(answers))
    split = bool(guard.g1_agreement(answers, threshold)[0])
    checks.append(Check("G1 답의 일치", True, split, f"방향 {int(winner):+d}에 모델의 {share:.0%}가 동의 (기준 {threshold:.0%})"))

    if primary_verified is None and n_independent is None:
        checks.append(Check("G4b 출처 대조", False, False, "출처 정보를 받지 못해 검사하지 않음"))
    else:
        few = guard.g4_corroboration(
            answers, 0.0, np.array([n_independent or 0]), k_sources, np.array([bool(primary_verified)])
        )[0]
        detail = "1차 출처 확인됨" if primary_verified else f"1차 출처 미확인, 독립 출처 {n_independent or 0}곳 (기준 {k_sources}곳)"
        checks.append(Check("G4b 출처 대조", True, bool(few), detail))

    if figure is None:
        checks.append(Check("G6 근거 대조", False, False, "글의 기준 값을 받지 못해 검사하지 않음"))
    else:
        basis = np.array([[np.mean([basis_ok(o, figure) for o in runs])] for runs in answered.values()])
        off = [m for m, row in zip(answered, basis) if row[0] < 0.5]
        cited = {m: Counter((o.basis_metric or "없음", o.basis_value or "") for o in answered[m]).most_common(1)[0][0] for m in off}
        detail = (
            "지침과 다른 근거: " + "; ".join(f"{m} → {metric} {value}".strip() for m, (metric, value) in cited.items())
            if off
            else f"모든 모델의 근거가 지침대로임 ({PRESCRIBED} {change_phrase(figure)})"
        )
        checks.append(Check("G6 근거 대조", True, bool(guard.g6_basis(answers, 0.0, basis)[0]), detail))

    flagged = any(c.flagged for c in checks)
    return Verdict("검토" if flagged else "통과", int(winner), float(share), checks)


def ask(clients: list[ModelClient], text: str, system: str, n_runs: int, item_id: str = "live") -> dict:
    """문서 한 건을 패널에 묻는다. screen에 넣을 모양으로 돌려준다."""
    inp = PanelInput(item_id=item_id, perturbation="original", text=text)
    return {c.name: [call_once(c, system, inp, run, "live").output for run in range(n_runs)] for c in clients}


def screen_disclosure(d: Disclosure, clients: list[ModelClient], system: str, n_runs: int, **kw) -> Verdict:
    """공시 숫자 한 건을 요약으로 만들어 패널에 묻고 판정한다. 공시 원문에서 옮긴 숫자이므로 1차 출처는 확인된 것으로 본다."""
    outputs = ask(clients, f"{VERIFIED_TAG}\n{render(d)}", system, n_runs, d.item_id)
    return screen(outputs, figure=key_figure(d), primary_verified=True, n_independent=d.n_independent_sources, **kw)


def show(title: str, v: Verdict) -> str:
    lines = [f"[{v.decision}] {title}", f"  패널의 답: 방향 {v.direction:+d}" if v.direction is not None else "  패널의 답: 없음"]
    for c in v.checks:
        mark = "걸림" if c.flagged else ("이상 없음" if c.ran else "검사 안 함")
        lines.append(f"  {c.guard}: {mark}. {c.detail}")
    return "\n".join(lines)


def _demo() -> None:
    def out(direction, metric=PRESCRIBED, value="32% 감소"):
        return InstitutionalOutput(intensity=4, direction=direction, basis_metric=metric, basis_value=value)

    models = ["모델A", "모델B", "모델C", "모델D"]
    cases = [
        ("정상: 네 모델이 지침대로 읽음", {m: [out(-1)] * 3 for m in models}, dict(figure=-32.0, primary_verified=True)),
        (
            "함께 잘못 읽음: 답은 전부 같은데 다른 숫자를 봄",
            {m: [out(1, "영업이익_전기대비", "18.5% 증가")] * 3 for m in models},
            dict(figure=-32.0, primary_verified=True),
        ),
        (
            "출처 없는 글: 지침대로 읽었지만 확인해 준 곳이 없음",
            {m: [out(-1)] * 3 for m in models},
            dict(figure=-32.0, primary_verified=False, n_independent=0),
        ),
    ]
    print("※ 지어낸 답으로 판정 과정만 보여 줍니다. 실제 모델과 무관합니다.\n")
    for title, outputs, info in cases:
        print(show(title, screen(outputs, **info)), end="\n\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--mock", action="store_true", help="지어낸 답 세 건으로 판정 과정을 보여 준다")
    mode.add_argument("--numbers", help="공시 숫자가 든 JSON 파일. 실제 모델을 호출한다 (API 키와 비용 필요)")
    parser.add_argument("--only", help="패널 중 일부 모델만 쓴다. 설정 파일의 name을 쉼표로")
    parser.add_argument("--json", action="store_true", help="판정을 JSON으로 출력한다")
    args = parser.parse_args()
    if args.mock:
        return _demo()

    from .clients import build_clients

    cfg = yaml.safe_load((ROOT / "config" / "experiment.yaml").read_text(encoding="utf-8"))
    models = cfg["panel"]["models"]
    if args.only:
        models = [m for m in models if m["name"] in args.only.split(",")]
    d = Disclosure.model_validate_json(Path(args.numbers).read_text(encoding="utf-8"))
    system = (ROOT / "prompts" / "institutional_system.txt").read_text(encoding="utf-8")
    v = screen_disclosure(
        d, build_clients(models), system, cfg["panel"]["n_runs"],
        threshold=cfg["guard"]["agreement_alert"], k_sources=cfg["guard"]["k_sources"],
    )
    if args.json:
        print(json.dumps({**asdict(v), "reasons": v.reasons}, ensure_ascii=False, indent=2))
    else:
        print(show(f"{d.corp} {d.period}", v))


if __name__ == "__main__":
    main()
