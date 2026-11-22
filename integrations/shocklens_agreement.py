"""ShockLens의 사건 해석을 여러 모델에 시켜 보고, 모델들이 같은 사건에서 함께 틀리는지 잰다.

ShockLens는 뉴스를 읽어 사건을 구조화하는 단계(Event Analyst)와 그 결과를 검증하는 단계에 같은 회사 모델을 쓴다.
해석하는 모델이 틀릴 때 다른 모델도 같이 틀린다면, 모델을 바꿔 검증해도 걸러지지 않는다. 이 스크립트가 그 겹침을 잰다.

실행 (ShockLens 폴더 안에서. 두 저장소가 나란히 있다고 가정한다):

    cd C:\\Users\\admin\\shocklens
    python ..\\collatio\\integrations\\shocklens_agreement.py --mock      # 호출 없이 흐름만 확인
    python ..\\collatio\\integrations\\shocklens_agreement.py             # 실제 호출 (API 키와 비용 필요)

입력   ShockLens 사건 라이브러리(data/library/events.yaml)의 제목 + 설명을 뉴스로 본다
정답   같은 파일에 사람이 붙인 라벨
모델   collatio/config/experiment.yaml의 패널 중 --only로 고른 것 (기본: OpenAI·Anthropic 네 모델)
지시문 ShockLens의 Event Analyst 지시문과 가드레일을 그대로 쓴다. 모든 모델에 같은 방식(글로 JSON 받기)으로 묻는다
결과   collatio/data/runs/shocklens/agreement.jsonl 에 쌓이고, 멈춰도 다시 실행하면 이어서 한다

ShockLens 저장소는 고치지 않는다. 이 파일은 ShockLens의 모듈을 읽어 쓰기만 한다.
"""

import argparse
import copy
import json
import os
import random
import sys
import time
from pathlib import Path

import numpy as np
import yaml

ECHO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ECHO / "src"))
sys.path.insert(0, os.getcwd())

from collatio import metrics  # noqa: E402

FIELDS = ["instrument", "direction", "initiator", "target", "sectors", "severity_level"]
CORE = ["instrument", "direction", "initiator"]  # 충격 계산의 경로를 정하는 세 필드
DEFAULT_ONLY = "gpt-sol,gpt-luna,claude-sonnet,claude-haiku"


class PanelLLM:
    """ShockLens의 event_analyst가 기대하는 모양(enabled, model, complete_json, derive)을 갖춘 모델 연결부."""

    enabled = True

    def __init__(self, name: str, provider: str, model_id: str):
        self.name, self.provider, self.model = name, provider, model_id
        self.calls, self.last_meta, self._sdk = 0, {}, None

    def derive(self, small: bool = False) -> "PanelLLM":
        return self  # 다른 모델을 섞지 않는다. 모델 하나의 판단만 본다

    def _text(self, system: str, user: str, max_tokens: int) -> str:
        if self._sdk is None:
            if self.provider == "anthropic":
                import anthropic

                self._sdk = anthropic.Anthropic()
            else:
                import openai

                self._sdk = openai.OpenAI()
        for attempt in range(4):
            try:
                if self.provider == "anthropic":
                    r = self._sdk.messages.create(
                        model=self.model, max_tokens=max(max_tokens, 4000), system=system,
                        messages=[{"role": "user", "content": user}],
                    )
                    return "".join(b.text for b in r.content if getattr(b, "type", "") == "text")
                r = self._sdk.responses.create(model=self.model, instructions=system, input=user)
                return r.output_text
            except Exception:
                if attempt == 3:
                    raise
                time.sleep(2 ** (attempt + 1))
        return ""

    def complete_json(self, system, user, max_tokens=2000, retries=1, schema=None, name="emit"):
        from agents.llm import extract_json

        self.calls += 1
        msg = user + "\n\nJSON 객체 하나만 출력하세요."
        for attempt in range(retries + 1):
            try:
                return extract_json(self._text(system, msg, max_tokens) or "")
            except (ValueError, json.JSONDecodeError) as e:
                if attempt == retries:
                    raise
                msg = f"{user}\n\n[이전 응답이 올바른 JSON이 아니었습니다: {e}] JSON 객체 하나만 출력하세요."
        return None


class MockLLM(PanelLLM):
    """호출 없이 흐름을 확인하는 가짜 모델. 정답을 베끼되 일부 사건에서 일부러 틀린다.

    shared에 든 사건은 모든 모델이 같이 틀리고, 그 밖에는 모델마다 따로 조금씩 틀린다.
    """

    def __init__(self, name, provider, events, shared, seed):
        super().__init__(name, provider, f"mock-{name}")
        self._by_title = {e["title"]: e for e in events}
        self._shared, self._rng = shared, random.Random(seed)

    def complete_json(self, system, user, max_tokens=2000, retries=1, schema=None, name="emit"):
        self.calls += 1
        ev = next((e for t, e in self._by_title.items() if t[:20] in user), None)
        if ev is None:
            raise ValueError("모의 모델이 사건을 찾지 못했습니다")
        out = {k: copy.deepcopy(ev.get(k)) for k in ("title", "instrument", "direction", "initiator", "target", "sectors", "stage", "channels")}
        out["direction"] = out["direction"] or "escalate"
        out["severity_components"] = ev.get("severity_components") or {k: 3 for k in ("scope", "immediacy", "substitut", "escalation", "parties", "surprise")}
        out["evidence"] = {}
        if ev["id"] in self._shared or self._rng.random() < 0.1:
            out["instrument"] = "domestic_regulation" if out["instrument"] != "domestic_regulation" else "tariff"
        return out


def news_of(ev: dict) -> str:
    return f"{ev['title']}. {' '.join(str(ev.get('description', '')).split())}"


def score(pred: dict, truth: dict, sev, weights) -> dict:
    """필드별로 맞으면 True. 강도 라벨이 없는 사건은 강도 등급을 None으로 둔다."""
    a, b = set(pred.get("sectors") or []), set(truth.get("sectors") or [])
    out = {
        "instrument": pred.get("instrument") == truth["instrument"],
        "direction": pred.get("direction", "escalate") == truth.get("direction", "escalate"),
        "initiator": pred.get("initiator") == truth["initiator"],
        "target": bool(set(pred.get("target") or []) & set(truth.get("target") or [])) or not truth.get("target"),
        "sectors": (len(a & b) / len(a | b) >= 0.5) if (a or b) else True,  # 자카드 0.5 이상이면 맞은 것으로 본다
        "severity_level": None,
    }
    if truth.get("severity") is not None or truth.get("severity_components"):
        t = sev.score(truth.get("severity_components"), weights, truth.get("severity", 3))
        out["severity_level"] = sev.level(pred.get("severity_points", 50.0)) == sev.level(t)
    return out


def collect(clients, events, sev_cfg, runs: int, path: Path) -> None:
    """모델 × 사건 × 반복을 돌며 한 건씩 저장한다. 이미 있는 것은 건너뛴다."""
    from agents import event_analyst
    from engine import severity as sev

    done = set()
    if path.exists():
        done = {(r["model"], r["event"], r["run"]) for r in map(json.loads, path.read_text(encoding="utf-8").splitlines()) if r}
    path.parent.mkdir(parents=True, exist_ok=True)
    weights = sev_cfg.get("component_weights")
    with open(path, "a", encoding="utf-8") as f:
        for c in clients:
            for ev in events:
                for run in range(runs):
                    if (c.name, ev["id"], run) in done:
                        continue
                    out = event_analyst.analyze(news_of(ev), c, None, sev_cfg)
                    row = {"model": c.name, "family": c.provider, "event": ev["id"], "run": run, "mode": out["mode"],
                           "complete": bool(out["event_complete"]), "llm_error": out.get("llm_error")}
                    # 모델 호출이 실패해 규칙 경로로 떨어진 답은 그 모델의 답이 아니다. 채점하지 않는다
                    if out["mode"] == "llm" and out["event_complete"]:
                        row["correct"] = score(out["event"], ev, sev, weights)
                        row["pred"] = {k: out["event"].get(k) for k in ("instrument", "direction", "initiator", "target", "sectors", "severity_points")}
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
                    f.flush()
            print(f"  {c.name}: 호출 {c.calls}회")


def analyze(path: Path, names: list[str], families: list[str], events: list[dict]) -> dict:
    rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    ids = [e["id"] for e in events]
    n_runs = max(r["run"] for r in rows) + 1
    report = {"n_events": len(ids), "models": names, "n_runs": n_runs,
              "unusable_share": round(float(np.mean(["correct" not in r for r in rows if r["model"] in names])), 3)}

    def table(fields: list[str]) -> np.ndarray:
        """(모델, 사건, 반복) 배열. 고른 필드가 전부 맞으면 1, 하나라도 틀리면 0, 답이 없으면 NaN."""
        arr = np.full((len(names), len(ids), n_runs), np.nan)
        for r in rows:
            if r["model"] in names and r["event"] in ids and "correct" in r:
                vals = [r["correct"][k] for k in fields]
                if any(v is None for v in vals):
                    continue
                arr[names.index(r["model"]), ids.index(r["event"]), r["run"]] = float(all(vals))
        return arr

    for label, fields in [("core(수단·방향·발동국)", CORE)] + [(k, [k]) for k in FIELDS]:
        arr = table(fields)
        keep = ~np.isnan(arr).all(axis=(0, 2))  # 어느 모델도 채점되지 않은 사건(강도 라벨 없음 등)은 뺀다
        arr, truth = arr[:, keep, :], np.ones(int(keep.sum()), dtype=int)
        if truth.size == 0:
            continue
        wrong = metrics.error_matrix(arr, truth)
        lo, hi = metrics.bootstrap_ci(lambda i: metrics.pairwise_error_correlation(arr[:, i, :], truth[i]), truth.size)
        gap = metrics.family_gap(arr, truth, families)
        report[label] = {
            "n_events": int(truth.size),
            "accuracy": {n: round(float(1 - wrong[m].mean()), 3) for m, n in enumerate(names)},
            "all_wrong_share": round(float(wrong.all(axis=0).mean()), 3),
            "pairwise_error_correlation": round(metrics.pairwise_error_correlation(arr, truth), 3),
            "ci95": [round(lo, 3), round(hi, 3)],
            "error_consistency": round(metrics.error_consistency(arr, truth), 3),
            "effective_models": round(metrics.diversification(arr, truth)["effective_models"], 2),
            "same_vendor_minus_cross_vendor": {k: round(v, 3) for k, v in gap.items()},
        }
        # ShockLens의 구성: 해석은 큰 Claude, 검증은 작은 Claude. 해석이 틀렸을 때 검증 쪽도 틀리는가
        if "claude-sonnet" in names and "claude-haiku" in names:
            s, h = wrong[names.index("claude-sonnet")], wrong[names.index("claude-haiku")]
            report[label]["writer_checker_claude"] = {
                "checker_error_rate": round(float(h.mean()), 3),
                "checker_error_rate_when_writer_wrong": round(float(h[s].mean()), 3) if s.any() else None,
                "n_writer_wrong": int(s.sum()),
            }
    return report


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mock", action="store_true", help="호출 없이 가짜 모델로 흐름만 확인한다")
    ap.add_argument("--only", default=DEFAULT_ONLY, help="쓸 모델 이름을 쉼표로 (collatio 설정의 name)")
    ap.add_argument("--runs", type=int, default=3, help="모델당 사건당 반복 횟수")
    ap.add_argument("--clean-only", action="store_true", help="겹침 사건이 없는(clean) 사건만 쓴다")
    a = ap.parse_args()

    try:
        from pipeline import config as sl_config
    except ImportError:
        sys.exit("ShockLens 폴더 안에서 실행하세요 (agents, engine, pipeline 폴더가 보여야 합니다).")
    events = yaml.safe_load((sl_config.DATA_DIR / "library" / "events.yaml").read_text(encoding="utf-8"))["events"]
    if a.clean_only:
        events = [e for e in events if e.get("clean") is True]
    events = sorted(events, key=lambda e: str(e["date"]))
    sev_cfg = copy.deepcopy(sl_config.load_yaml("thresholds.yaml").get("severity", {}))
    sev_cfg.setdefault("self_consistency", {})["n"] = 1  # 강도를 여러 번 물어 다른 모델과 섞는 기능을 끈다

    panel = yaml.safe_load((ECHO / "config" / "experiment.yaml").read_text(encoding="utf-8"))["panel"]["models"]
    chosen = [m for m in panel if m["name"] in a.only.split(",") and m["provider"] in ("openai", "anthropic")]
    if not chosen:
        sys.exit("고른 모델이 없습니다. --only의 이름을 확인하세요.")
    if a.mock:
        shared = {e["id"] for e in events[::5]}
        clients = [MockLLM(m["name"], m["provider"], events, shared, i) for i, m in enumerate(chosen)]
        path = ECHO / "data" / "runs" / "shocklens" / "agreement_mock.jsonl"
        path.unlink(missing_ok=True)
        print("※ 모의 실행입니다. 아래 숫자는 실제 모델과 무관합니다.")
    else:
        clients = [PanelLLM(m["name"], m["provider"], m["model_id"]) for m in chosen]
        path = ECHO / "data" / "runs" / "shocklens" / "agreement.jsonl"
    print(f"사건 {len(events)}건 × 모델 {len(clients)}개 × {a.runs}회. 응답은 {path}에 쌓입니다.")
    collect(clients, events, sev_cfg, a.runs, path)
    report = analyze(path, [c.name for c in clients], [c.provider for c in clients], events)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
