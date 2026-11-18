"""내려받은 공시 원문에서 숫자를 읽어 라벨 파일을 만든다.

    python scripts/fetch_disclosures.py 10      # 먼저 원문을 받는다
    python scripts/dart_to_labels.py 10         # 후보 목록 위에서부터 10건을 읽는다

사람도 AI도 숫자를 옮기지 않는다. 코드가 표를 읽고, 요약·정답·난이도·변형 글을 만든다.
data/labels/news_labels.csv, perturbations.csv, disclosures.csv를 새로 쓴다.

뉴스 번호는 후보 목록의 순서다(d001이 첫 줄). 빠진 공시가 있어도 번호는 당겨지지 않는다.
빠지는 경우: 영업이익이 적자지속(방향을 정할 수 없음), 표를 읽지 못함, 표 안의 숫자가 서로 어긋남.
"""

import csv
import re
import sys
from collections import Counter
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from echoguard import dart  # noqa: E402
from echoguard.disclosure import Disclosure, conflicts, flipped, injected, quality, render, render_alt, to_news_item  # noqa: E402

CANDIDATES = ROOT / "data" / "candidates" / "disclosures.csv"
RAW = ROOT / "data" / "raw" / "dart"
LABELS = ROOT / "data" / "labels" / "news_labels.csv"
WRITTEN = ROOT / "data" / "labels" / "perturbations.csv"
NUMBERS = ROOT / "data" / "labels" / "disclosures.csv"


def main(n: int = 10, labeler: str = "code") -> int:
    cfg = yaml.safe_load((ROOT / "config" / "experiment.yaml").read_text(encoding="utf-8"))
    news_from = cfg["dataset"]["news_from"]
    with open(CANDIDATES, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))[:n]
    columns = LABELS.read_text(encoding="utf-8").splitlines()[0].split(",")
    items, written, kept, left_out, remarks = [], [], [], [], []
    for i, row in enumerate(rows, start=1):
        item_id, name = f"d{i:03d}", row["corp_name"]
        found = re.search(r"rcpNo=(\d{14})", row["url"])
        path = RAW / found.group(1) / f"{found.group(1)}.xml" if found else None
        if path is None or not path.exists():
            left_out.append(f"  {item_id} {name}: 원문이 없음. python scripts/fetch_disclosures.py {n} 를 먼저 실행")
            continue
        parsed = dart.parse(path.read_text(encoding="utf-8", errors="replace"), found.group(1), item_id, name)
        d = parsed.disclosure
        wrong = parsed.problems + (quality(d, news_from, typed=False) if d else [])
        if d is None or wrong:
            left_out.append(f"  {item_id} {name}: " + "; ".join(wrong))
            continue
        try:
            item = to_news_item(d, labeler)
        except ValueError:
            left_out.append(f"  {item_id} {name}: 영업이익이 적자지속이라 방향을 정할 수 없음")
            continue
        remarks += [f"  {item_id} {name}: {note}" for note in parsed.notes]
        items.append(item)
        kept.append(d)
        written.append((item_id, "paraphrase", render_alt(d)))
        if injected(d):
            written.append((item_id, "injection", injected(d)))
        f2 = flipped(d)
        if f2 is not None:
            written.append((item_id, "fact_flip", render(f2)))

    if not items:
        print("쓸 수 있는 공시가 없습니다.\n" + "\n".join(left_out))
        return 1
    with open(LABELS, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns)
        w.writeheader()
        for it in items:
            row = it.model_dump()
            row["source_verified"] = int(row["source_verified"])
            w.writerow({k: ("" if row[k] is None else row[k]) for k in columns})
    with open(WRITTEN, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["item_id", "perturbation", "text"])
        w.writerows(written)
    with open(NUMBERS, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(Disclosure.model_fields))
        w.writeheader()
        for d in kept:
            w.writerow({k: ("" if v is None else v) for k, v in d.model_dump().items()})

    kinds = Counter(k for _, k, _ in written)
    mixed = sum(bool(conflicts(d)) for d in kept)
    direction = Counter(it.direction_text for it in items)
    n_inputs = 2 * len(items) + sum(kinds.values()) + kinds["fact_flip"]  # 원문, 출처 바꿈, 써 둔 변형, 꾸민 보도
    print(f"공시 {len(rows)}건 중 {len(items)}건을 썼습니다.")
    print(f"  방향: 긍정 {direction[1]}, 부정 {direction[-1]}")
    print(f"  기준 지표와 반대 방향 숫자가 섞인 공시: {mixed}건")
    print(f"  변형: 말 바꾸기 {kinds['paraphrase']}, 숨긴 지시문 {kinds['injection']}, 사실 뒤집기 {kinds['fact_flip']} (전환·100% 넘는 증가는 뒤집지 않음)")
    print(f"  모델에 넣을 입력 {n_inputs}개. 모델 4개 × {cfg['panel']['n_runs']}회면 호출 {n_inputs * 4 * cfg['panel']['n_runs']}회")
    if remarks:
        print("\n알아 둘 것:\n" + "\n".join(remarks))
    if left_out:
        print(f"\n뺀 공시 {len(left_out)}건:\n" + "\n".join(left_out))
    print("\nperturbations.csv에는 실제 회사명이 든 조작 글이 들어 있습니다. 공개 리포에 올리지 마세요.")
    return 0


if __name__ == "__main__":
    sys.exit(main(int(sys.argv[1]) if len(sys.argv) > 1 else 10))
