"""출처 확인: 공시 주소가 가리키는 접수 건이 전자공시(OpenDART)에 실제로 있는지 본다.

G4b는 '1차 출처가 실제로 확인되었는가'를 입력으로 받는다. 글에 붙은 출처 표기를 믿으면 조작에 뚫리므로,
여기서는 표기가 아니라 금융감독원 접수 목록을 조회해 확인한다.

확인하는 것: 그 접수번호가 그 날짜의 거래소 공시 목록에 있고, 회사 이름이 같고, 잠정실적 공시다.
확인하지 않는 것: 옮겨 적은 숫자가 원문과 같은지. 그것은 아직 사람이 대조한다.

환경변수 DART_API_KEY가 필요하다. 키는 코드나 설정 파일에 적지 않는다.
"""

import re
from dataclasses import dataclass

API = "https://opendart.fss.or.kr/api/list.json"
KEYWORD = "잠정"


@dataclass
class SourceCheck:
    verified: bool
    detail: str


def receipt_no(url: str) -> str | None:
    """공시 주소에서 접수번호 14자리를 꺼낸다. dart.fss.or.kr 주소가 아니면 None."""
    if not re.match(r"https?://(www\.)?dart\.fss\.or\.kr/", url):
        return None
    found = re.search(r"rcpNo=(\d{14})\b", url)
    return found.group(1) if found else None


def _norm(name: str) -> str:
    return re.sub(r"\s|\(주\)|주식회사|㈜", "", name)


def verify_dart(url: str, corp: str, key: str, get=None) -> SourceCheck:
    """공시 주소의 접수 건이 전자공시 목록에 있는지 확인한다. get은 시험용으로 바꿔 끼울 수 있다."""
    number = receipt_no(url)
    if number is None:
        return SourceCheck(False, "전자공시 주소가 아니거나 접수번호가 없음")
    if get is None:
        import requests

        get = requests.get
    day, page = number[:8], 1
    while True:
        body = get(
            API,
            params={"crtfc_key": key, "bgn_de": day, "end_de": day, "pblntf_ty": "I", "page_no": page, "page_count": 100},
            timeout=30,
        ).json()
        if body.get("status") == "013":
            return SourceCheck(False, f"{day}에 접수된 거래소 공시가 없음")
        if body.get("status") != "000":
            return SourceCheck(False, f"전자공시 조회 실패 ({body.get('status')}: {body.get('message')})")
        for row in body["list"]:
            if row["rcept_no"] != number:
                continue
            if _norm(row["corp_name"]) != _norm(corp):
                return SourceCheck(False, f"접수 건의 회사가 다름: 전자공시에는 {row['corp_name']}")
            if KEYWORD not in row["report_nm"]:
                return SourceCheck(False, f"잠정실적 공시가 아님: {row['report_nm'].strip()}")
            return SourceCheck(True, f"전자공시에서 확인: {row['corp_name']} {row['report_nm'].strip()}")
        if page >= int(body.get("total_page", 1)):
            return SourceCheck(False, f"접수번호 {number}이 {day} 공시 목록에 없음")
        page += 1
