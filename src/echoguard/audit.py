"""판정 기록: 필터가 내린 판정과 사람의 검토 결과를 남긴다.

    python -m echoguard.audit summary data/audit/decisions.jsonl     # 기간 보고
    python -m echoguard.audit verify  data/audit/decisions.jsonl     # 기록이 고쳐지지 않았는지 확인
    python -m echoguard.audit review  data/audit/decisions.jsonl <판정 id> <검토자> <확정|반려> "메모"

필터는 걸러서 사람에게 넘긴다. 무엇을 왜 넘겼고 사람이 어떻게 결정했는지가 남지 않으면 나중에 따져 볼 수 없다.
한 줄에 한 건씩 뒤에 덧붙이기만 한다. 고치거나 지우지 않는다.

각 줄에는 바로 앞 줄의 해시가 들어간다. 중간의 한 줄을 고치면 그 뒤의 해시가 전부 어긋나므로 verify가 알아챈다.
이것은 실수나 단순한 수정에 대한 장치다. 파일 전체를 다시 쓸 수 있는 사람까지 막지는 못한다.

입력 글은 저장하지 않고 해시만 남긴다. 어떤 글이었는지는 원본과 대조해 확인한다.
"""

import hashlib
import json
import sys
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

GENESIS = "0" * 64


def _hash(body: dict) -> str:
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load(path: str | Path) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def _last_hash(path: str | Path) -> str:
    """마지막 줄의 해시. 기록이 길어져도 덧붙이는 비용이 늘지 않게 파일 끝만 읽는다."""
    p = Path(path)
    if not p.exists() or p.stat().st_size == 0:
        return GENESIS
    with open(p, "rb") as f:
        size, block = f.seek(0, 2), 4096
        while True:
            f.seek(max(size - block, 0))
            lines = [l for l in f.read().splitlines() if l.strip()]
            if len(lines) > 1 or block >= size:
                return json.loads(lines[-1].decode("utf-8"))["hash"] if lines else GENESIS
            block *= 4


def _append(path: str | Path, body: dict) -> dict:
    body = {**body, "at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "prev": _last_hash(path)}
    entry = {**body, "hash": _hash(body)}
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def record(path: str | Path, verdict, *, item_id: str, text: str, models: dict[str, str], settings: dict) -> dict:
    """판정 한 건을 남긴다.

    models    모델 이름 → 공급사가 알려 준 버전 표기
    settings  판정에 쓴 기준값과 지시문 해시 등. 같은 조건으로 다시 판정할 수 있게 한다
    """
    return _append(path, {
        "kind": "decision", "item_id": item_id, "input_hash": text_hash(text),
        "decision": verdict.decision, "direction": verdict.direction, "agreement": round(verdict.agreement, 3),
        "checks": [asdict(c) for c in verdict.checks], "models": models, "settings": settings,
    })


def review(path: str | Path, decision_hash: str, reviewer: str, outcome: str, note: str = "") -> dict:
    """검토로 넘어간 판정에 대한 사람의 결정을 남긴다. outcome은 '확정'(패널의 답을 그대로 씀) 또는 '반려'."""
    if outcome not in ("확정", "반려"):
        raise ValueError("outcome은 '확정' 또는 '반려'")
    targets = [e for e in load(path) if e["kind"] == "decision" and e["hash"].startswith(decision_hash)]
    if len(targets) != 1:
        raise ValueError(f"판정 id '{decision_hash}'에 해당하는 기록이 {len(targets)}건")
    return _append(path, {"kind": "review", "of": targets[0]["hash"], "reviewer": reviewer, "outcome": outcome, "note": note})


def verify(path: str | Path) -> list[str]:
    """기록의 사슬이 온전한지 본다. 어긋난 줄을 돌려준다. 비어 있으면 이상 없음."""
    broken, prev = [], GENESIS
    for n, entry in enumerate(load(path), start=1):
        body = {k: v for k, v in entry.items() if k != "hash"}
        if entry.get("prev") != prev:
            broken.append(f"{n}번째 줄: 앞 줄과 이어지지 않음")
        if _hash(body) != entry.get("hash"):
            broken.append(f"{n}번째 줄: 내용이 기록 당시와 다름")
        prev = entry.get("hash")
    return broken


def summary(path: str | Path) -> dict:
    """기간 보고에 쓸 요약: 판정 수, 검토 비율, 어느 검사에 걸렸는지, 사람이 아직 보지 않은 건, 쓰인 모델 버전."""
    entries = load(path)
    decisions = [e for e in entries if e["kind"] == "decision"]
    reviews = {e["of"]: e for e in entries if e["kind"] == "review"}
    sent = [e for e in decisions if e["decision"] == "검토"]
    flagged = Counter(c["guard"] for e in sent for c in e["checks"] if c["flagged"])
    skipped = Counter(c["guard"] for e in decisions for c in e["checks"] if not c["ran"])
    versions = sorted({f"{m}: {v}" for e in decisions for m, v in e["models"].items()})
    outcomes = Counter(reviews[e["hash"]]["outcome"] for e in sent if e["hash"] in reviews)
    return {
        "period": [decisions[0]["at"], decisions[-1]["at"]] if decisions else None,
        "n_decisions": len(decisions),
        "review_rate": round(len(sent) / len(decisions), 3) if decisions else None,
        "flagged_by": dict(flagged.most_common()),
        "checks_not_run": dict(skipped.most_common()),
        "human_reviews": {"done": sum(outcomes.values()), **outcomes, "pending": [e["hash"][:12] for e in sent if e["hash"] not in reviews]},
        "model_versions_seen": versions,
        "log_intact": not verify(path),
    }


if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) >= 2 and args[0] == "summary":
        print(json.dumps(summary(args[1]), ensure_ascii=False, indent=2))
    elif len(args) >= 2 and args[0] == "verify":
        problems = verify(args[1])
        print("\n".join(problems) if problems else "기록이 온전합니다.")
        sys.exit(1 if problems else 0)
    elif len(args) >= 5 and args[0] == "review":
        print(json.dumps(review(args[1], args[2], args[3], args[4], args[5] if len(args) > 5 else ""), ensure_ascii=False, indent=2))
    else:
        sys.exit(__doc__)
