"""후보 목록의 공시 원문을 전자공시(OpenDART)에서 내려받는다.

    set DART_API_KEY=발급받은키
    python scripts/fetch_disclosures.py          # 후보 목록 위에서부터 10건
    python scripts/fetch_disclosures.py 50       # 50건

data/candidates/disclosures.csv의 순서대로 받는다. 골라 받지 않는다.
원문은 data/raw/dart/<접수번호>/ 에 풀린다. 이 폴더는 리포에 올리지 않는다.
이미 받은 공시는 건너뛴다. 키는 환경변수로만 받고 어디에도 적지 않는다.
"""

import csv
import io
import os
import re
import sys
import time
import zipfile
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
API = "https://opendart.fss.or.kr/api/document.xml"
CANDIDATES = ROOT / "data" / "candidates" / "disclosures.csv"
OUT = ROOT / "data" / "raw" / "dart"


def main(n: int = 10) -> int:
    key = os.environ.get("DART_API_KEY")
    if not key:
        sys.exit("환경변수 DART_API_KEY가 없습니다.")
    if not CANDIDATES.exists():
        sys.exit(f"후보 목록이 없습니다: {CANDIDATES}\n먼저 python scripts/sample_candidates.py 를 실행하세요.")
    with open(CANDIDATES, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))[:n]
    got = skipped = failed = 0
    for i, row in enumerate(rows, start=1):
        found = re.search(r"rcpNo=(\d{14})", row["url"])
        if not found:
            print(f"  {i:>3} {row['corp_name']}: 주소에 접수번호가 없음")
            failed += 1
            continue
        number = found.group(1)
        folder = OUT / number
        if folder.exists() and any(folder.iterdir()):
            skipped += 1
            continue
        r = requests.get(API, params={"crtfc_key": key, "rcept_no": number}, timeout=30)
        if not r.content.startswith(b"PK"):  # 압축 파일이 아니면 오류 응답이다
            message = re.sub(r"<[^>]+>", " ", r.text)[:120].split()
            print(f"  {i:>3} {row['corp_name']} ({number}): 받지 못함 - {' '.join(message)}")
            failed += 1
            continue
        folder.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            for name in z.namelist():
                (folder / Path(name).name).write_bytes(z.read(name))
        (folder / "_meta.txt").write_text(f"{row['date']}\t{row['corp_name']}\t{row['report_nm']}\t{row['url']}\n", encoding="utf-8")
        sizes = ", ".join(f"{p.name} {p.stat().st_size:,}B" for p in sorted(folder.iterdir()) if p.name != "_meta.txt")
        print(f"  {i:>3} {row['corp_name']} ({number}): {sizes}")
        got += 1
        time.sleep(0.3)
    print(f"\n받음 {got}건, 이미 있음 {skipped}건, 실패 {failed}건. 위치: {OUT}")
    return 1 if failed and not got and not skipped else 0


if __name__ == "__main__":
    sys.exit(main(int(sys.argv[1]) if len(sys.argv) > 1 else 10))
