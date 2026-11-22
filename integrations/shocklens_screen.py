"""뉴스를 ShockLens로 해석하고, 그 해석을 Collatio 필터로 거른다.

    뉴스 → ShockLens의 Event Analyst (모델 여러 개가 각자 해석) → Collatio 판정 (통과 / 검토 / 범위 밖)

ShockLens는 뉴스 한 건을 '사건'으로 구조화한다(수단, 방향, 발동국, 대상국, 강도). 이 해석이 틀리면 뒤의 손실 계산이 전부 틀린다.
여기서는 같은 뉴스를 여러 모델에 따로 해석시키고, 해석이 갈리거나 근거가 없으면 사람에게 넘긴다.

실행 (ShockLens 폴더 안에서. 두 저장소가 나란히 있다고 가정한다):

    cd C:\\Users\\admin\\shocklens
    python ..\\collatio\\integrations\\shocklens_screen.py --mock --file 뉴스.txt     # 호출 없이 흐름만 확인
    python ..\\collatio\\integrations\\shocklens_screen.py --today                    # 오늘 헤드라인에서 정책 토픽을 골라 판정
    python ..\\collatio\\integrations\\shocklens_screen.py --file 뉴스.txt            # 직접 고른 뉴스를 판정

--today   ShockLens의 RSS 피드(config/daily_watch.yaml)에서 헤드라인을 모아 규칙으로 토픽을 묶고, 지역마다 정책 토픽 상위 N개를 쓴다
--file    뉴스 본문을 '---' 한 줄로 구분해 적은 글 파일

실제 호출에는 API 키(환경변수 ANTHROPIC_API_KEY, OPENAI_API_KEY)와 비용이 든다. 뉴스 1건 × 모델 4개 × 2회 = 8회 호출이다.
잠정실적 공시는 ShockLens의 범위 밖이다(정책 사건만 다룬다). 공시는 `python -m collatio.filter --numbers`로 판정한다.

정답이 없는 뉴스이므로 여기서 재는 것은 '맞았는가'가 아니라 '믿고 넘겨도 되는 모양인가'다.
ShockLens 저장소는 고치지 않는다.
"""

import argparse
import datetime as dt
import json
import random
import re
import sys
from collections import Counter
from pathlib import Path

import yaml

ECHO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ECHO / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path.cwd()))

from collatio import audit  # noqa: E402
from collatio.filter import Check, Verdict, show  # noqa: E402
from shocklens_agreement import DEFAULT_ONLY, PanelLLM  # noqa: E402

CORE = ["instrument", "direction", "initiator"]  # 충격 계산의 경로를 정하는 세 필드
SHORT = 300  # 본문이 이보다 짧으면 헤드라인만 본 것으로 친다


class MockLLM(PanelLLM):
    """호출 없이 흐름을 확인하는 가짜 모델. ShockLens의 키워드 규칙으로 답하고, 모델마다 가끔 수단을 바꿔 답한다."""

    def __init__(self, name, provider, seed):
        super().__init__(name, provider, f"mock-{name}")
        self._seed = seed

    def complete_json(self, system, user, max_tokens=2000, retries=1, schema=None, name="emit"):
        from agents import event_analyst

        self.calls += 1
        block = user.split("실제 입력", 1)[-1]
        sentences = [{"id": i, "text": t} for i, t in re.findall(r"\[(s\d+)\]\s*(.+)", block)]
        draft = event_analyst.rule_extract(sentences)
        if not draft.get("instrument"):
            return {"instrument": "none", "not_policy_reason": "정책 수단 단어가 없음 (모의)"}
        if random.Random(f"{self._seed}|{block[:80]}").random() < 0.25:
            draft["instrument"] = "tariff" if draft["instrument"] != "tariff" else "tech_export_control"
            draft["evidence"].pop("instrument", None)  # 근거 없이 다른 수단을 댄다
        return draft


def _mode(values: list):
    """가장 많이 나온 값. 동률이면 먼저 나온 것."""
    return Counter(values).most_common(1)[0][0] if values else None


def screen_event(per_model: dict[str, list[dict]], text: str, n_outlets: int | None, threshold: float) -> tuple[Verdict, dict]:
    """모델별 ShockLens 해석(event_analyst.analyze의 결과들)을 판정한다. (판정, 모델별 대표 답)"""
    checks = []
    # G0: 입력 자체의 문제. ShockLens의 지시문 탐지 결과를 그대로 쓴다
    flags = next((o.get("injection_flags") for outs in per_model.values() for o in outs if o.get("injection_flags")), [])
    by_code = [f for f in flags if f.get("by") == "code"]
    problems = [f"지시문으로 의심되는 문장 {f['id']}: {f['text'][:40]}" for f in by_code]
    if len(text) < SHORT:
        problems.append(f"본문이 짧다({len(text)}자). 기사 본문 없이 헤드라인만 본 해석이다")
    checks.append(Check("G0 입력 점검", True, bool(problems), "; ".join(problems) or "지시문 의심 문장 없음, 본문 있음"))

    # 응답: 모델이 실제로 답했는가. 호출이 실패해 키워드 규칙으로 떨어진 답은 그 모델의 답이 아니다
    usable = {m: [o for o in outs if o["mode"] == "llm"] for m, outs in per_model.items()}
    silent = [m for m, outs in usable.items() if not outs]
    checks.append(Check("응답", True, bool(silent), f"답을 내지 못한 모델: {', '.join(silent)}" if silent else "모든 모델이 답함"))
    usable = {m: outs for m, outs in usable.items() if outs}
    if not usable:
        return Verdict("검토", None, 0.0, checks), {}

    # 정책 사건인가: ShockLens는 정책 사건만 다룬다. 이 판단부터 갈리면 뒤는 볼 필요가 없다
    policy = {m: _mode([not o.get("not_policy") for o in outs]) for m, outs in usable.items()}
    share = sum(policy.values()) / len(policy)
    if 0 < share < 1:
        said_no = [m for m, p in policy.items() if not p]
        checks.append(Check("정책 사건 여부", True, True, f"정책 사건이 아니라고 본 모델: {', '.join(said_no)}"))
        return Verdict("검토", None, max(share, 1 - share), checks), {m: {"policy": p} for m, p in policy.items()}
    if share == 0:
        checks.append(Check("정책 사건 여부", True, False, "모든 모델이 정책 사건이 아니라고 봄. ShockLens의 범위 밖"))
        # 입력에 문제가 있었다면 '범위 밖'이라는 결론도 믿을 수 없다
        return Verdict("검토" if problems else "범위 밖", None, 1.0, checks), {m: {"policy": False} for m in policy}
    checks.append(Check("정책 사건 여부", True, False, "모든 모델이 정책 사건으로 봄"))

    events = {m: [o["event"] for o in outs if o.get("event")] for m, outs in usable.items()}
    incomplete = [m for m, evs in events.items() if not evs]
    if incomplete:
        checks.append(Check("필수 필드", True, True, f"수단·발동국·대상국을 채우지 못한 모델: {', '.join(incomplete)}"))
    events = {m: evs for m, evs in events.items() if evs}
    if not events:
        return Verdict("검토", None, 0.0, checks), {}

    def field(ev: dict, name: str):
        v = ev.get(name)
        return tuple(sorted(v)) if isinstance(v, list) else v

    answers = {m: {k: _mode([field(e, k) for e in evs]) for k in CORE + ["target", "severity"]} for m, evs in events.items()}

    # G1: 핵심 세 필드에서 모델들의 답이 갈리는가
    worst, splits = 1.0, []
    for k in CORE:
        counts = Counter(a[k] for a in answers.values())
        top = counts.most_common(1)[0][1] / len(answers)
        worst = min(worst, top)
        if top < threshold:
            splits.append(f"{k}: " + ", ".join(f"{m}={a[k]}" for m, a in answers.items()))
    checks.append(Check("G1 답의 일치", True, bool(splits), "갈린 필드 → " + " / ".join(splits) if splits else f"수단·방향·발동국이 모두 일치 (가장 낮은 일치율 {worst:.0%}, 기준 {threshold:.0%})"))

    # G6: 근거 문장 없이 답한 핵심 필드가 있는가. ShockLens의 가드레일이 근거 없는 필드를 uncertain_fields에 적어 둔다
    bare = {}
    for m, evs in events.items():
        missing = [k for k in CORE if sum(k in (e.get("uncertain_fields") or []) or not (e.get("evidence") or {}).get(k) for e in evs) * 2 >= len(evs) and k != "direction"]
        if missing:
            bare[m] = missing
    checks.append(Check("G6 근거 대조", True, bool(bare), "근거 문장 없이 답함 → " + "; ".join(f"{m}: {', '.join(v)}" for m, v in bare.items()) if bare else "수단과 발동국에 모든 모델이 근거 문장을 댐"))

    # 강도는 한 등급 차이가 흔하므로 두 등급 이상 벌어질 때만 알린다. 판정에는 넣지 않고 적어만 둔다
    levels = [a["severity"] for a in answers.values() if a["severity"] is not None]
    if levels and max(levels) - min(levels) >= 2:
        checks.append(Check("강도 차이", True, False, "강도 등급이 두 단계 이상 벌어짐 → " + ", ".join(f"{m}={a['severity']}" for m, a in answers.items()) + " (참고용, 판정에 넣지 않음)"))

    # G4a: 몇 매체가 다뤘는가. 받아쓴 기사도 세므로 독립 확인이 아니다
    if n_outlets is None:
        checks.append(Check("G4a 보도 매체 수", False, False, "매체 수를 알 수 없어 검사하지 않음"))
    else:
        checks.append(Check("G4a 보도 매체 수", True, n_outlets < 2, f"이 토픽을 다룬 매체 {n_outlets}곳 (받아쓴 기사 포함, 독립 확인 아님)"))

    flagged = any(c.flagged for c in checks)
    return Verdict("검토" if flagged else "통과", None, worst, checks), {m: {k: (list(v) if isinstance(v, tuple) else v) for k, v in a.items()} for m, a in answers.items()}


def _overlap(a: str, b: str) -> float:
    """두 제목이 얼마나 겹치는가. 두 글자 이상 낱말의 자카드 값."""
    ta, tb = (set(w for w in re.findall(r"[0-9A-Za-z가-힣]{2,}", s.lower())) for s in (a, b))
    return len(ta & tb) / len(ta | tb) if ta and tb else 0.0


def article_of(topic: dict, heads: list[dict], tries: int = 6) -> tuple[str, str | None, str]:
    """토픽의 기사 본문을 찾는다. (글, 본문을 가져온 주소 또는 None, 실패 사유)

    Google 뉴스의 주소는 원문으로 바로 이어지지 않는 경우가 많아 뒤로 미루고, 매체 주소를 먼저 시도한다.
    본문을 얻지 못하면 헤드라인 묶음을 돌려준다. 그 경우 모델을 부르지 않고 사람에게 넘긴다.
    """
    from tools.news import fetch_article

    by_id = {h["id"]: h for h in heads}
    hs = [by_id[i] for i in topic["headline_ids"] if i in by_id and by_id[i].get("url")]
    hs.sort(key=lambda h: "news.google.com" in h["url"])
    reasons = []
    for h in hs[:tries]:
        try:
            art = fetch_article(h["url"])
        except Exception as e:  # 주소 하나가 막혀도 다음 것을 본다
            reasons.append(f"{type(e).__name__}")
            continue
        if art.get("text") and len(art["text"]) >= SHORT:
            return f"{h['title']}.\n{art['text'][:6000]}", h["url"], ""
        reasons.append(str(art.get("error") or f"본문 {len(art.get('text') or '')}자")[:60])
    # 피드의 주소로 안 되면 헤드라인으로 검색해 같은 사건을 다룬 매체 기사를 찾는다 (ShockLens의 검색 도구, GDELT 우선)
    from tools.news import search_news

    found = search_news(topic["title"], max_results=8)
    if found.get("error") and not found["results"]:
        reasons.append(f"검색 실패({found['error'][:40]})")
    for r in found["results"]:
        if "news.google.com" in r["url"] or _overlap(topic["title"], r["title"]) < 0.2:
            continue  # 제목이 충분히 겹치지 않으면 다른 사건일 수 있다
        try:
            art = fetch_article(r["url"])
        except Exception as e:
            reasons.append(type(e).__name__)
            continue
        if art.get("text") and len(art["text"]) >= SHORT:
            return f"{r['title']}.\n{art['text'][:6000]}", r["url"], ""
        reasons.append(str(art.get("error") or "본문 짧음")[:40])
    titles = [by_id[i]["title"] for i in topic["headline_ids"] if i in by_id][:8]
    return "\n".join(f"{t}." for t in titles), None, "; ".join(reasons) or "주소 없음"


def todays_news(regions: list[str], top: int, include_all: bool) -> list[dict]:
    """ShockLens의 피드에서 헤드라인을 모으고, 규칙으로 토픽을 묶어 지역마다 상위 top개를 고른다. LLM을 쓰지 않는다."""
    from agents import daily_watch

    cfg = daily_watch.load_cfg()
    picked = []
    for code in regions:
        region = cfg["regions"].get(code)
        if not region:
            print(f"  {code}: 설정에 없는 지역")
            continue
        heads, errors = daily_watch.collect(region, cfg.get("max_headlines_per_feed", 40))
        for e in errors:
            print(f"  {code} 피드 실패: {e}")
        topics = daily_watch.cluster_rule(heads, 30, cfg.get("cluster_threshold", 0.35))
        if not include_all:
            topics = [t for t in topics if t["policy_event"]]
        for t in topics[:top]:
            text, url, why = article_of(t, heads)
            picked.append({"id": f"{code}-{len(picked) + 1}", "title": t["title"], "text": text, "url": url,
                           "n_outlets": t["n_outlets"], "source_mode": "article" if url else "headlines", "fetch_note": why})
        print(f"  {code}: 헤드라인 {len(heads)}건, 고른 토픽 {min(top, len(topics))}건")
    return picked


def file_news(path: str) -> list[dict]:
    blocks = [b.strip() for b in re.split(r"(?m)^\s*---\s*$", Path(path).read_text(encoding="utf-8")) if b.strip()]
    return [{"id": f"f{i + 1}", "title": b.splitlines()[0][:60], "text": b, "url": None, "n_outlets": None, "source_mode": "file", "fetch_note": ""} for i, b in enumerate(blocks)]


def out_path(base: Path, date: str) -> Path:
    path, n = base / f"screen_{date}.jsonl", 2
    while path.exists():  # 덮어쓰지 않는다
        path, n = base / f"screen_{date}_v{n}.jsonl", n + 1
    return path


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--today", action="store_true", help="오늘 헤드라인에서 정책 토픽을 골라 쓴다")
    src.add_argument("--file", help="뉴스 본문을 '---'로 구분해 적은 글 파일")
    ap.add_argument("--mock", action="store_true", help="호출 없이 가짜 모델로 흐름만 확인한다")
    ap.add_argument("--regions", default="KR,US", help="--today에서 볼 지역")
    ap.add_argument("--top", type=int, default=2, help="--today에서 지역마다 고를 토픽 수")
    ap.add_argument("--all", action="store_true", help="--today에서 정책 토픽이 아닌 것도 포함한다")
    ap.add_argument("--only", default=DEFAULT_ONLY, help="쓸 모델 이름을 쉼표로 (collatio 설정의 name)")
    ap.add_argument("--runs", type=int, default=2, help="모델당 뉴스당 반복 횟수")
    a = ap.parse_args()

    try:
        from agents import event_analyst
        from pipeline import config as sl_config
    except ImportError:
        sys.exit("ShockLens 폴더 안에서 실행하세요 (agents, engine, pipeline 폴더가 보여야 합니다).")

    cfg = yaml.safe_load((ECHO / "config" / "experiment.yaml").read_text(encoding="utf-8"))
    chosen = [m for m in cfg["panel"]["models"] if m["name"] in a.only.split(",") and m["provider"] in ("openai", "anthropic")]
    if not chosen:
        sys.exit("고른 모델이 없습니다. --only의 이름을 확인하세요.")
    if a.mock:
        clients = [MockLLM(m["name"], m["provider"], i) for i, m in enumerate(chosen)]
        print("※ 모의 실행입니다. 모델의 답은 키워드 규칙으로 지어낸 것이고 실제 모델과 무관합니다.")
    else:
        clients = [PanelLLM(m["name"], m["provider"], m["model_id"]) for m in chosen]
    sev_cfg = dict(sl_config.load_yaml("thresholds.yaml").get("severity", {}))
    sev_cfg["self_consistency"] = {**(sev_cfg.get("self_consistency") or {}), "n": 1}  # 강도를 다른 모델과 섞어 채점하는 기능을 끈다

    news = todays_news(a.regions.split(","), a.top, a.all) if a.today else file_news(a.file)
    if not news:
        sys.exit("판정할 뉴스가 없습니다.")
    ready = sum(len(n["text"]) >= SHORT for n in news)
    print(f"뉴스 {len(news)}건 중 본문이 있는 것 {ready}건 × 모델 {len(clients)}개 × {a.runs}회 = 호출 {ready * len(clients) * a.runs}회\n")

    today = dt.date.today().isoformat()
    base = ECHO / "data" / "runs" / "shocklens"
    base.mkdir(parents=True, exist_ok=True)
    result_path = out_path(base, today + ("_mock" if a.mock else ""))
    log = ECHO / "data" / "audit" / ("shocklens_mock.jsonl" if a.mock else "shocklens_decisions.jsonl")
    threshold, tally = cfg["guard"]["agreement_alert"], Counter()
    with open(result_path, "w", encoding="utf-8") as f:
        for item in news:
            if len(item["text"]) < SHORT:  # 본문이 없으면 모델을 부르지 않는다. 헤드라인만 보고 한 해석은 판정할 가치가 없다
                why = f" 본문을 가져오지 못함: {item['fetch_note']}" if item.get("fetch_note") else ""
                verdict = Verdict("검토", None, 0.0, [Check("G0 입력 점검", True, True, f"본문이 짧다({len(item['text'])}자). 모델을 부르지 않음.{why}")])
                tally[verdict.decision] += 1
                print(show(f"{item['id']} {item['title']}", verdict).replace("  패널의 답: 없음\n", ""), end="\n\n")
                entry = audit.record(log, verdict, item_id=item["id"], text=item["text"], models={}, settings={"source": item["source_mode"]})
                f.write(json.dumps({"id": item["id"], "title": item["title"], "url": None, "decision": "검토", "reasons": verdict.reasons, "answers": {}, "audit": entry["hash"][:12]}, ensure_ascii=False) + "\n")
                continue
            per_model = {c.name: [event_analyst.analyze(item["text"], c, None, sev_cfg) for _ in range(a.runs)] for c in clients}
            for outs in per_model.values():  # 저장할 수 있는 모양으로
                for o in outs:
                    if o.get("event") and not isinstance(o["event"], dict):
                        o["event"] = o["event"].model_dump()
            verdict, answers = screen_event(per_model, item["text"], item["n_outlets"], threshold)
            tally[verdict.decision] += 1
            print(show(f"{item['id']} {item['title']}", verdict).replace("  패널의 답: 없음\n", ""))
            if item["url"]:
                print(f"  읽은 기사: {item['url']}")
            for m, ans in answers.items():
                print(f"    {m}: {json.dumps(ans, ensure_ascii=False)}")
            print()
            entry = audit.record(log, verdict, item_id=item["id"], text=item["text"], models={c.name: c.model for c in clients},
                                 settings={"threshold": threshold, "runs": a.runs, "source": item["source_mode"], "url": item["url"]})
            f.write(json.dumps({"id": item["id"], "title": item["title"], "url": item["url"], "n_outlets": item["n_outlets"],
                                "decision": verdict.decision, "reasons": verdict.reasons, "answers": answers, "audit": entry["hash"][:12]}, ensure_ascii=False) + "\n")
    print(f"결과: 통과 {tally['통과']}건, 검토 {tally['검토']}건, 범위 밖 {tally['범위 밖']}건")
    print(f"저장: {result_path}\n판정 기록: {log}")


if __name__ == "__main__":
    main()
