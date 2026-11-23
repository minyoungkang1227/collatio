"""검수 기록과 출처 추적 로그(해시 체인)."""
import datetime
import hashlib
import json
from pathlib import Path

from .schema import content_hash

MIN_APPROVALS = 2


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def read_jsonl(path):
    path = Path(path)
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def append_jsonl(path, row):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


# ---- 출처 추적 로그: 각 줄이 앞줄의 해시를 품어서 사후 수정이 드러난다 ----

def _entry_hash(entry):
    body = {k: v for k, v in entry.items() if k != "hash"}
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def log_event(path, event, **data):
    rows = read_jsonl(path)
    entry = {"ts": _now(), "event": event, "data": data, "prev": rows[-1]["hash"] if rows else ""}
    entry["hash"] = _entry_hash(entry)
    append_jsonl(path, entry)
    return entry


def verify_log(path):
    """문제가 있는 줄 번호 목록. 비어 있으면 정상."""
    bad, prev = [], ""
    for n, e in enumerate(read_jsonl(path), 1):
        if e.get("prev") != prev or e.get("hash") != _entry_hash(e):
            bad.append(n)
        prev = e.get("hash", "")
    return bad


# ---- 교차 검수 ----

def add_review(path, item, reviewer, verdict, note=""):
    if verdict not in ("approve", "reject"):
        raise ValueError("verdict는 approve 또는 reject")
    if reviewer == item.get("author"):
        raise ValueError("작성자는 자기 문항을 검수할 수 없음")
    row = {"ts": _now(), "item_id": item["id"], "item_hash": content_hash(item),
           "reviewer": reviewer, "verdict": verdict, "note": note}
    append_jsonl(path, row)
    return row


def review_status(items, reviews, untrusted=()):
    """{id: {status, approvals, rejects}}.

    현재 내용 해시에 대한 검수만 유효하다(문항을 고치면 다시 검수).
    검수자별 마지막 판정만 센다. 반려가 하나라도 있으면 rejected,
    승인이 MIN_APPROVALS명 이상이면 approved, 그 외 pending.
    untrusted에 든 검토자(심은 오답을 못 잡은 사람)의 판정은 세지 않는다.
    answer_source가 engine인 문항은 반려가 없으면 approved(by=code).
    """
    out = {}
    for it in items:
        h, latest = content_hash(it), {}
        for r in reviews:
            if r["item_id"] == it["id"] and r["item_hash"] == h and r["reviewer"] not in untrusted:
                latest[r["reviewer"]] = r["verdict"]
        ap = sum(v == "approve" for v in latest.values())
        rj = sum(v == "reject" for v in latest.values())
        status = "rejected" if rj else "approved" if ap >= MIN_APPROVALS else "pending"
        by = "review"
        # 정답을 엔진이 계산한 문항은 사람 승인 없이 쓴다. 보증하는 것은 정답의 계산이지 문항의 표현이 아니다.
        if status == "pending" and it.get("answer_source") == "engine":
            status, by = "approved", "code"
        out[it["id"]] = {"status": status, "approvals": ap, "rejects": rj, "by": by}
    return out
