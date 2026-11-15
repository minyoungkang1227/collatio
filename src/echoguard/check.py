"""시험 호출: 패널 모델을 각각 몇 번씩만 불러 연결, 형식, 토큰 수를 확인한다.

    python -m echoguard.check            # 모델마다 3회
    python -m echoguard.check --runs 1

본 실험 전에 반드시 돌린다. 여기서 나온 호출당 토큰 수로 전체 비용을 다시 계산한다.
출력에는 API 키가 들어가지 않는다.
"""

import argparse
from pathlib import Path

import yaml

from .clients import build_clients, cost_usd
from .panel import call_once
from .perturb import PanelInput

ROOT = Path(__file__).resolve().parents[2]

# 지어낸 예문이다. 실제 회사나 사건이 아니다.
SAMPLE = PanelInput(
    item_id="sample",
    perturbation="original",
    text="[출처: 금융감독원 전자공시·정부 발표]\n"
    "가나전자는 3분기 영업이익이 전년 동기 대비 32% 감소한 1,150억 원이라고 공시했다. "
    "회사는 주력 제품의 판매 단가 하락을 원인으로 들었다.",
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--runs", type=int, default=3)
    args = parser.parse_args()

    cfg = yaml.safe_load((ROOT / "config" / "experiment.yaml").read_text(encoding="utf-8"))
    models = cfg["panel"]["models"]
    system = (ROOT / "prompts" / "institutional_system.txt").read_text(encoding="utf-8")
    calls_per_model = cfg["dataset"]["n_items"] * len(cfg["perturbations"]) * cfg["panel"]["n_runs"]

    print(f"{'모델':<16}{'응답':<34}{'입력':>7}{'출력':>7}{'본 실험 예상':>14}")
    total = 0.0
    for model, client in zip(models, build_clients(models)):
        try:
            records = [call_once(client, system, SAMPLE, run, "check") for run in range(args.runs)]
        except Exception as e:  # 키가 없거나 모델 이름이 틀린 경우 등
            print(f"{model['name']:<16}실패: {type(e).__name__}: {str(e)[:70]}")
            continue
        tin = sum(r.input_tokens for r in records) / len(records)
        tout = sum(r.output_tokens for r in records) / len(records)
        answers = ", ".join(
            f"{r.output.intensity}/{r.output.direction:+d}" if r.output else "형식위반" for r in records
        )
        full = cost_usd(model, int(tin * calls_per_model), int(tout * calls_per_model))
        total += full
        print(f"{model['name']:<16}{answers:<34}{tin:>7.0f}{tout:>7.0f}{'$' + format(full, '.2f'):>14}")
        bad = [r.raw for r in records if r.output is None]
        if bad:
            print(f"    형식 위반 응답 예: {bad[0][:120]!r}")
    print(f"\n응답 칸은 강도/방향이다. 기관 트랙 {calls_per_model:,}회 기준 예상 합계: ${total:.2f}")
    print("(일괄 처리 할인과 개인 트랙은 반영하지 않았다)")


if __name__ == "__main__":
    main()
