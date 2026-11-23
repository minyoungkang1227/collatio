"""실패 사례 수집·분류. 틀린 응답을 모으고, 전문가가 오류 유형을 붙인다."""
import hashlib
from collections import defaultdict
from pathlib import Path

from . import store

ERROR_TYPES = {
    "calc": "계산 오류",
    "concept": "개념·원리 오류",
    "outdated": "개정 전 규정 적용",
    "fabricated": "없는 근거를 지어냄",
    "omission": "핵심 사항 누락",
    "format": "형식 오류(답은 맞음)",
    "grader": "채점 오류(실제로는 정답)",
    "item": "문항 자체의 오류",
}


def failure_id(run_id, model, item_id):
    return hashlib.sha256(f"{run_id}|{model}|{item_id}".encode()).hexdigest()[:10]


def collect(run_dir, run_id, items, dataset_path, threshold=1.0):
    """채점 결과에서 score < threshold 인 응답을 실패 사례 파일에 누적. 새로 추가된 건수 반환."""
    responses = {(r["model"], r["item_id"]): r["response"]
                 for r in store.read_jsonl(Path(run_dir) / "responses.jsonl")}
    have = {f["id"] for f in store.read_jsonl(dataset_path)}
    added = 0
    for g in store.read_jsonl(Path(run_dir) / "grades.jsonl"):
        if g["score"] >= threshold:
            continue
        fid = failure_id(run_id, g["model"], g["item_id"])
        if fid in have:
            continue
        it = items.get(g["item_id"], {})
        ans = it.get("answer", {})
        store.append_jsonl(dataset_path, {
            "id": fid, "run_id": run_id, "model": g["model"], "item_id": g["item_id"],
            "domain": g["domain"], "answer_type": g["answer_type"], "score": g["score"],
            "question": it.get("question", ""), "reference": ans.get("reference", ans.get("value")),
            "response": responses.get((g["model"], g["item_id"]), ""), "grade_detail": g["detail"],
        })
        added += 1
    return added


def annotate(path, failures, fid, annotator, error_type, note=""):
    if error_type not in ERROR_TYPES:
        raise ValueError(f"error_type은 {sorted(ERROR_TYPES)} 중 하나")
    if fid not in {f["id"] for f in failures}:
        raise ValueError(f"실패 사례 없음: {fid}")
    row = {"failure_id": fid, "annotator": annotator, "error_type": error_type, "note": note}
    store.append_jsonl(path, row)
    return row


def latest_annotations(annotations):
    """{failure_id: {annotator: error_type}} — 분류자별 마지막 판정만."""
    out = defaultdict(dict)
    for a in annotations:
        out[a["failure_id"]][a["annotator"]] = a["error_type"]
    return out


def report(failures, annotations, all_grades):
    ann = latest_annotations(annotations)
    lines = ["# 실패 사례 보고서", "", f"누적 실패 사례 {len(failures)}건, 분류 완료 {sum(f['id'] in ann for f in failures)}건.", ""]

    # 1) 모델 × 오류 유형
    table = defaultdict(lambda: defaultdict(int))
    for f in failures:
        types = set(ann.get(f["id"], {}).values()) or {"미분류"}
        for t in types:
            table[f["model"]][t] += 1
    cols = [t for t in list(ERROR_TYPES) + ["미분류"] if any(table[m][t] for m in table)]
    if cols:
        lines += ["## 모델별 오류 유형", "", "| 모델 | " + " | ".join(ERROR_TYPES.get(c, c) for c in cols) + " |",
                  "|---|" + "---|" * len(cols)]
        for m in sorted(table):
            lines.append(f"| {m} | " + " | ".join(str(table[m][c]) for c in cols) + " |")
        lines.append("")

    # 2) 문항 변별력: 모든 실행의 채점 결과에서 문항별 평균
    by_item = defaultdict(list)
    for g in all_grades:
        by_item[g["item_id"]].append(g["score"])
    hard = sorted(i for i, s in by_item.items() if len(s) >= 2 and max(s) == 0)
    easy = sorted(i for i, s in by_item.items() if len(s) >= 2 and min(s) == 1)
    lines += ["## 문항 점검", "",
              f"- 모든 모델이 0점: {', '.join(hard) or '없음'} → 진짜 어려운 문항이거나 문항·정답 오류. 먼저 원문 대조.",
              f"- 모든 모델이 만점: {', '.join(easy) or '없음'} → 변별력 없음. 난도를 올리거나 교체.", ""]

    # 3) 채점·문항 오류로 분류된 건: 파이프라인 자체를 고쳐야 하는 신호
    fix = [f for f in failures if set(ann.get(f["id"], {}).values()) & {"grader", "item"}]
    if fix:
        lines += ["## 파이프라인 수정 필요", ""]
        lines += [f"- {f['id']} ({f['item_id']}, {f['model']}): {', '.join(ERROR_TYPES[t] for t in set(ann[f['id']].values()))}" for f in fix]
        lines.append("")
    return "\n".join(lines) + "\n"
