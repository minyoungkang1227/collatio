"""받은 숫자를 전자공시 원문과 대조하는 가드(G4c)를 실제 전자공시에 대고 돌려 본다.

    set DART_API_KEY=발급받은키
    python scripts/check_against_dart.py

data/labels/disclosures.csv(dart_to_labels.py가 만든 것)의 공시마다 두 가지를 넣어 본다.
  원문 그대로인 숫자          → 통과해야 한다
  영업이익 증감의 부호만 바꾼 숫자 → 걸려야 한다 (주소는 진짜 공시의 것 그대로)
모델은 부르지 않는다. 전자공시만 조회한다. 공시 한 건에 조회 세 번이다.
"""

import csv
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from echoguard.disclosure import Disclosure, flipped  # noqa: E402
from echoguard.source import verify_dart, verify_numbers  # noqa: E402

NUMBERS = ROOT / "data" / "labels" / "disclosures.csv"


def main() -> int:
    key = os.environ.get("DART_API_KEY")
    if not key:
        sys.exit("환경변수 DART_API_KEY가 없습니다.")
    if not NUMBERS.exists():
        sys.exit("data/labels/disclosures.csv가 없습니다. 먼저 python scripts/dart_to_labels.py 를 실행하세요.")
    with open(NUMBERS, encoding="utf-8", newline="") as f:
        rows = [Disclosure.model_validate({k: v for k, v in r.items() if v != ""}) for r in csv.DictReader(f)]
    clean_ok = fake_n = fake_caught = exists = 0
    for d in rows:
        company = d.corp.split("(")[-1].replace("의 자회사)", "") if "의 자회사)" in d.corp else d.corp
        there = verify_dart(d.url, company, key)
        exists += there.verified
        same = verify_numbers(d, key)
        clean_ok += same.verified
        line = f"  {d.item_id} {d.corp[:18]}: 공시 {'있음' if there.verified else '확인 안 됨'} | 원문 그대로 → {'통과' if same.verified else '걸림'}"
        fake = flipped(d)
        if fake is not None:
            fake_n += 1
            got = verify_numbers(fake, key)
            fake_caught += not got.verified
            line += f" | 부호 바꿈 → {'걸림' if not got.verified else '통과(놓침)'}"
        print(line)
        for check in (there, same):
            if not check.verified:
                print(f"      {check.detail}")
        time.sleep(0.3)
    print(f"\n공시 {len(rows)}건: 접수 건 확인 {exists}건, 원문 그대로인 숫자 통과 {clean_ok}건")
    print(f"영업이익 증감의 부호를 바꾼 숫자 {fake_n}건 중 {fake_caught}건을 잡음")
    return 0


if __name__ == "__main__":
    sys.exit(main())
