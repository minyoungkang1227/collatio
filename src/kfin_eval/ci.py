"""CI에서 돌리는 작은 점검 두 가지 — 'eval을 CI처럼'.

kfin_eval은 같은 저장소의 collatio 패키지와, 별도 저장소인 ShockLens의 엔진을 불러 쓴다(bridges.py).
그쪽이 바뀌면 이쪽 결과도 바뀔 수 있어서 아래 두 점검을 GitHub Actions에서 돌린다
(이 저장소의 tests.yml·eval-live.yml, ShockLens의 kfin-eval.yml).

1) 정답지 점검 (ci-key) — API 키 필요 없음, 몇 초
   엔진이 정답을 계산하는 생성기(ShockLens 충격·역스트레스, ELS, 단위 환산)로 문항을 고정 시드로 다시 만들고,
   문항별 정답의 해시를 ci/answer_key.json과 비교한다. ShockLens 엔진(engine/risk.py, reverse.py)이 바뀌어
   정답이 달라진 문항이 있으면 실패한다. 의도한 변경이면 `ci-key --update`로 정답지를 갱신하고, 그 문항으로
   예전에 돌린 실행 결과는 더 이상 같은 문항의 결과가 아니라는 점을 기록에 남긴다.
   - 수치 정답은 유효숫자 5자리로 반올림한 뒤 해시한다. 허용오차(±0.5~1%)보다 훨씬 작은 부동소수점 차이로
     실패하지 않게 하기 위해서다.
   - 이 생성기들은 공개 코드와 시드만 있으면 누구나 같은 문항을 만들 수 있다. 해시는 정답지를 감추려는 것이
     아니라 비교를 짧게 하려는 것이다.

2) 소규모 eval (ci-smoke) — 실제 모델 호출, API 키 필요
   공개 문항(dist/public.jsonl) 중 고정한 30문항을 Collatio 패널 모델(eg:이름)로 풀게 하고, real2 같은 문항의
   결과(ci/smoke.json의 baseline)와 비교한다. Collatio의 모델 목록(config/experiment.yaml)이나 호출 코드
   (clients.py)가 바뀌었을 때 성능이 떨어졌는지 본다.
   - 30문항은 real2에서 오답이 나온 유형(6단 전년 동기 역산, 4단 숨은 지시문)을 많이 넣고 나머지 유형을 조금씩 섞었다.
   - 실패 기준(실행 전에 정함): 모델 하나의 오답이 기준선보다 tolerance(기본 2)개 넘게 늘거나,
     모든 모델이 같이 틀린 문항이 하나라도 있으면 실패. 두 번째는 가드(일치도 검사)가 못 잡는 경우라 따로 막는다.
   - 문항마다 한 번만 묻는다. 기준선 자체도 한 번 실행한 값이라, 오답 1~2개 차이는 우연일 수 있다(그래서 tolerance).
   - mock-* 모델을 넘기면 API 없이 흐름만 점검한다(가드 점검까지 Collatio 코드를 실제로 부른다).
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path

from . import gen as GEN
from . import grade as G

KEY_GENERATORS = (("shocklens", 40, 1), ("els", 40, 1), ("units", 40, 1))   # real3에 쓴 것과 같은 시드·개수


def _round_sig(x, sig=5):
    if isinstance(x, bool) or not isinstance(x, (int, float)) or x == 0 or not math.isfinite(x):
        return x
    return round(x, sig - 1 - int(math.floor(math.log10(abs(x)))))


def _canon(answer):
    return {k: _round_sig(v) for k, v in sorted(answer.items())}


def answer_hash(item):
    blob = json.dumps({"id": item["id"], "answer": _canon(item["answer"])}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def build_key(root) -> tuple[dict, list[str]]:
    """{생성기: {문항 id: 해시}}와 건너뛴 생성기 목록(필요한 저장소가 없을 때)."""
    gens = {**GEN.GENERATORS, **GEN.load_plugins(root)}
    key, skipped = {}, []
    for name, n, seed in KEY_GENERATORS:
        if name not in gens:
            skipped.append(f"{name}(생성기 없음)")
            continue
        try:
            items = gens[name](n, seed)
        except (SystemExit, ImportError) as e:      # ShockLens 저장소가 없으면 shocklens 생성기는 못 돈다
            skipped.append(f"{name}({e})")
            continue
        key[name] = {it["id"]: answer_hash(it) for it in items}
    return key, skipped


def compare_key(old: dict, new: dict) -> dict:
    out = {}
    for name in sorted(set(old) | set(new)):
        o, n = old.get(name, {}), new.get(name, {})
        if name not in new:
            continue                                  # 이번에 못 돈 생성기는 비교하지 않는다(건너뜀으로 따로 보고)
        out[name] = {"changed": sorted(i for i in set(o) & set(n) if o[i] != n[i]),
                     "missing": sorted(set(o) - set(n)), "new": sorted(set(n) - set(o))}
    return out


# ----------------------------------------------------------------------------- 소규모 eval

def load_smoke(root) -> dict:
    return json.loads((Path(root) / "ci" / "smoke.json").read_text(encoding="utf-8"))


def smoke_items(root, ids):
    pub = {}
    for line in (Path(root) / "dist" / "public.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            it = json.loads(line)
            pub[it["id"]] = it
    missing = [i for i in ids if i not in pub]
    if missing:
        raise SystemExit(f"smoke 문항이 dist/public.jsonl에 없음: {missing}")
    return [pub[i] for i in ids]


def judge_smoke(scores: dict, baseline: dict, ids: list, tolerance: int) -> dict:
    """scores/baseline: {모델: {문항: 0|1}}. 판정과 표를 만든다. 순수 함수라 테스트한다."""
    rows, fails = [], []
    for m in sorted(scores):
        now = scores[m]
        wrong_now = sorted(i for i in ids if now.get(i, 0) < 1)
        base = baseline.get(m)
        if base is None:
            rows.append(dict(model=m, wrong=len(wrong_now), base=None, new_wrong=wrong_now, fixed=[]))
            continue
        wrong_base = {i for i in ids if base.get(i, 1) < 1}
        new_wrong = [i for i in wrong_now if i not in wrong_base]
        fixed = sorted(wrong_base - set(wrong_now))
        rows.append(dict(model=m, wrong=len(wrong_now), base=len(wrong_base), new_wrong=new_wrong, fixed=fixed))
        if len(wrong_now) - len(wrong_base) > tolerance:
            fails.append(f"{m}: 오답 {len(wrong_base)} → {len(wrong_now)}개 (허용 +{tolerance})")
    joint = [i for i in ids if len(scores) >= 2 and all(scores[m].get(i, 0) < 1 for m in scores)]
    if joint:
        fails.append(f"모든 모델이 함께 틀린 문항 {len(joint)}개: {', '.join(joint)} (일치도 가드로 못 잡는 경우)")
    return {"rows": rows, "joint": joint, "fails": fails, "ok": not fails}


def smoke_markdown(res: dict, n_items: int, models: list[str], tolerance: int, source: str) -> str:
    lines = [f"### kfin-eval 소규모 eval — {'통과' if res['ok'] else '실패'}", "",
             f"문항 {n_items}개(dist/public.jsonl 고정), 모델 {', '.join(models)}, 기준선 {source}, 허용 오답 증가 +{tolerance}.", "",
             "| 모델 | 오답(이번) | 오답(기준선) | 새로 틀린 문항 | 새로 맞힌 문항 |", "|---|---|---|---|---|"]
    for r in res["rows"]:
        base = "기준선 없음" if r["base"] is None else str(r["base"])
        lines.append(f"| {r['model']} | {r['wrong']} | {base} | {', '.join(r['new_wrong']) or '-'} | {', '.join(r['fixed']) or '-'} |")
    lines += ["", f"모든 모델이 함께 틀린 문항: {', '.join(res['joint']) or '없음'}"]
    if res["fails"]:
        lines += ["", "**실패 사유**", *[f"- {f}" for f in res["fails"]]]
    lines += ["", "문항마다 한 번만 물었다. 오답 1~2개 차이는 우연일 수 있다. 실제 시장·업무 성과가 아니다."]
    return "\n".join(lines)


def run_smoke(root, model_names: list[str], tolerance: int = 2, out_dir=None) -> tuple[dict, list, dict]:
    """모델에 smoke 문항을 풀리고 채점한다. 반환: (판정, 문항, 응답 {모델: {문항: 응답}})."""
    from .models import get_model
    spec = load_smoke(root)
    items = smoke_items(root, spec["items"])
    scores, responses = {}, {}
    for name in model_names:
        model = get_model(name)
        label = name.split(":", 1)[-1]               # eg:claude-haiku → claude-haiku (기준선 이름과 맞춘다)
        scores[label], responses[label] = {}, {}
        for it in items:
            resp = model.answer(it)
            s, _ = G.grade(it, resp)
            scores[label][it["id"]] = s
            responses[label][it["id"]] = resp
    res = judge_smoke(scores, spec["baseline"], spec["items"], tolerance)
    if out_dir:
        d = Path(out_dir)
        d.mkdir(parents=True, exist_ok=True)
        with open(d / "smoke_responses.jsonl", "w", encoding="utf-8") as f:
            for m, rs in responses.items():
                for iid, r in rs.items():
                    f.write(json.dumps({"model": m, "item_id": iid, "score": scores[m][iid], "response": r},
                                       ensure_ascii=False) + "\n")
    return res, items, responses


def guard_on_smoke(items, responses):
    """smoke 응답 위에서 Collatio 가드(G1)를 실제로 부른다. Collatio 가드 함수의 형태가 바뀌면 여기서 깨진다."""
    from . import guardlink as GL
    rows = [{"model": m, "item_id": i, "response": r} for m, rs in responses.items() for i, r in rs.items()]
    return GL.check({it["id"]: it for it in items}, rows)["summary"]


def write_summary(text: str):
    """GitHub Actions 작업 요약 칸에도 쓴다(로컬에서는 환경변수가 없어 건너뜀)."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(text + "\n\n")
