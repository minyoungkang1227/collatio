"""라벨링 후보를 규칙으로 뽑는다: 전자공시의 잠정실적 공시에서 무작위 추출.

    set DART_API_KEY=발급받은키        (opendart.fss.or.kr에서 무료 발급)
    python scripts/sample_candidates.py

사람이나 AI가 뉴스를 골라 담으면 고르는 쪽의 취향이 표본에 섞인다. 그래서 종목 뉴스 후보는
기준일 이후의 잠정실적 공시 전체에서 시드를 고정해 무작위로 뽑는다.
결과는 data/candidates/disclosures.csv에 쓴다. 여기서 골라 요약과 라벨을 붙인다.

주의: 이 스크립트는 실제 OpenDART로 아직 돌려 보지 않았다. 응답 형식이 다르면 고쳐야 한다.
"""

import csv
import os
import random
import sys
from datetime import date
from pathlib import Path

import requests
import yaml

ROOT = Path(__file__).resolve().parents[1]
API = "https://opendart.fss.or.kr/api/list.json"
KEYWORD = "영업(잠정)실적"


def fetch(key: str, begin: str, end: str, market: str) -> list[dict]:
    rows, page = [], 1
    while True:
        r = requests.get(
            API,
            params={
                "crtfc_key": key, "bgn_de": begin, "end_de": end, "pblntf_ty": "I",
                "corp_cls": market, "page_no": page, "page_count": 100,
            },
            timeout=30,
        )
        body = r.json()
        if body.get("status") == "013":  # 조회된 자료 없음
            break
        if body.get("status") != "000":
            sys.exit(f"OpenDART 오류 {body.get('status')}: {body.get('message')}")
        rows += body["list"]
        if page >= int(body.get("total_page", 1)):
            break
        page += 1
    return rows


def main(n: int = 140) -> None:
    key = os.environ.get("DART_API_KEY")
    if not key:
        sys.exit("환경변수 DART_API_KEY가 없습니다. opendart.fss.or.kr에서 발급받아 등록하세요.")
    cfg = yaml.safe_load((ROOT / "config" / "experiment.yaml").read_text(encoding="utf-8"))
    begin = cfg["dataset"]["news_from"].replace("-", "")
    end = date.today().strftime("%Y%m%d")
    found = [d for market in ("Y", "K") for d in fetch(key, begin, end, market) if KEYWORD in d["report_nm"]]
    found.sort(key=lambda d: d["rcept_no"])                       # 섞기 전 순서를 고정
    random.Random(cfg["seed"]).shuffle(found)
    picked = found[:n]
    out = ROOT / "data" / "candidates" / "disclosures.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8-sig", newline="") as f:  # 엑셀에서 한글이 깨지지 않게
        w = csv.writer(f)
        w.writerow(["date", "corp_name", "market", "report_nm", "url"])
        for d in picked:
            dt = d["rcept_dt"]
            w.writerow([
                f"{dt[:4]}-{dt[4:6]}-{dt[6:]}", d["corp_name"], d["corp_cls"], d["report_nm"].strip(),
                f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={d['rcept_no']}",
            ])
    print(f"{begin}~{end} 잠정실적 공시 {len(found)}건 중 {len(picked)}건을 뽑아 {out}에 썼습니다.")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 140)
