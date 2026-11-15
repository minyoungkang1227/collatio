"""채운 엑셀 양식을 라벨 파일로 바꾸고 검사한다.

    python scripts/xlsx_to_labels.py 채운파일.xlsx

data/labels/news_labels.csv와 data/labels/perturbations.csv를 새로 쓴다.
형식이 틀린 줄이 있으면 어느 줄의 어느 칸인지 알려 주고 아무것도 쓰지 않는다.
"""

import csv
import sys
from collections import Counter
from pathlib import Path

from openpyxl import load_workbook
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from echoguard.dataset import NewsItem  # noqa: E402
from echoguard.labeling import rule_label  # noqa: E402

LABELS = ROOT / "data" / "labels" / "news_labels.csv"
WRITTEN = ROOT / "data" / "labels" / "perturbations.csv"
CSV_COLUMNS = LABELS.read_text(encoding="utf-8").splitlines()[0].split(",")
TARGETS = {
    "type": {"stock": 70, "macro": 30},
    "difficulty": {"clear": 80, "ambiguous": 20},
    "source_verified": {True: 70, False: 30},
}


def read_rows(path: Path) -> list[tuple[int, dict]]:
    ws = load_workbook(path, data_only=True)["라벨"]
    header = [c.value for c in ws[1]]
    rows = []
    for n, values in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        row = {k: (str(v).strip() if v is not None else "") for k, v in zip(header, values)}
        if not row.get("item_id") or row["item_id"].startswith("예시"):
            continue
        rows.append((n, row))
    return rows


def main(path: str, labeler: str = "minyoung") -> int:
    rows = read_rows(Path(path))
    if not rows:
        print("채운 행이 없습니다.")
        return 1
    items, flips, problems, differs, checked = [], [], [], [], 0
    for n, row in rows:
        data = {k: (row.get(k) or None) for k in CSV_COLUMNS}
        data["labeler"] = labeler
        try:
            pct = float(row["op_yoy_pct"]) if row.get("op_yoy_pct") else None
            ruled = rule_label(pct, row.get("op_turn") or None)
        except ValueError as e:
            problems.append(f"  {n}행 op_yoy_pct/op_turn: {e}")
            continue
        data["label_method"] = "rule" if ruled else "manual"
        if ruled:
            by_hand = (data.get("intensity_true"), data.get("direction_text"))
            if all(by_hand):
                checked += 1
                if (int(float(by_hand[0])), int(float(by_hand[1]))) != ruled:
                    differs.append(f"  {n}행: 직접 적은 값 강도 {by_hand[0]}, 방향 {by_hand[1]} / 규칙 값 강도 {ruled[0]}, 방향 {ruled[1]:+d}")
            data["intensity_true"], data["direction_text"] = ruled
        if data.get("date"):
            data["date"] = data["date"][:10]
        try:
            item = NewsItem.model_validate(data)
        except ValidationError as e:
            for err in e.errors():
                problems.append(f"  {n}행 {err['loc'][0]}: {err['msg']}")
            continue
        if item.n_reports < min(item.n_independent_sources, 5):
            problems.append(f"  {n}행: n_reports가 n_independent_sources보다 작습니다")
        if not row.get("fact_flip_text"):
            problems.append(f"  {n}행: fact_flip_text가 비어 있습니다")
        items.append(item)
        flips.append((item.item_id, row.get("fact_flip_text", "")))
    ids = [it.item_id for it in items]
    problems += [f"  item_id 중복: {i}" for i, c in Counter(ids).items() if c > 1]
    if problems:
        print(f"고칠 곳이 {len(problems)}군데 있습니다. 파일은 쓰지 않았습니다.")
        print("\n".join(problems[:40]))
        return 1

    with open(LABELS, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        w.writeheader()
        for it in items:
            d = it.model_dump()
            d["source_verified"] = int(d["source_verified"])
            w.writerow({k: ("" if d[k] is None else d[k]) for k in CSV_COLUMNS})
    with open(WRITTEN, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["item_id", "perturbation", "text"])
        w.writerows((i, "fact_flip", t) for i, t in flips)

    print(f"뉴스 {len(items)}건을 썼습니다.\n\n구성 (지금 / 100건일 때 목표)")
    for field, target in TARGETS.items():
        counts = Counter(getattr(it, field) for it in items)
        print(f"  {field}: " + ", ".join(f"{k} {counts.get(k, 0)}/{v}" for k, v in target.items()))
    direction = Counter(it.direction_text for it in items)
    print("  direction_text: " + ", ".join(f"{k:+d} {direction.get(k, 0)}" for k in (-1, 0, 1)) + "  (고르게)")
    methods = Counter(it.label_method for it in items)
    print(f"  라벨 방식: 규칙 {methods.get('rule', 0)}, 직접 {methods.get('manual', 0)}")
    if checked:
        print(f"\n직접 적은 값과 규칙 값 비교: {checked}건 중 {len(differs)}건이 다릅니다. 정답에는 규칙 값을 썼습니다.")
        print("\n".join(differs[:20]))
    print("\nperturbations.csv에는 실제 회사명이 든 조작 글이 들어 있습니다. 공개 리포에 올리지 마세요.")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    sys.exit(main(*sys.argv[1:3]))
