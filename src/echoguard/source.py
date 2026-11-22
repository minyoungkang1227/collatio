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


DOCUMENT_API = "https://opendart.fss.or.kr/api/document.xml"
FIELDS = {
    "unit": "단위", "period": "분기",
    "revenue": "매출액", "revenue_yoy": "매출액 전년 동기 대비", "revenue_qoq": "매출액 전기 대비",
    "op": "영업이익", "op_yoy": "영업이익 전년 동기 대비", "op_qoq": "영업이익 전기 대비",
    "net": "순이익", "net_yoy": "순이익 전년 동기 대비",
    "cum_op": "누계 영업이익", "cum_op_yoy": "누계 영업이익 전년 동기 대비",
}


def differences(claimed, original) -> list[str]:
    """받은 숫자가 원문에서 읽은 숫자와 다른 곳. 비어 있으면 전부 같다.

    글을 넘겨받은 쪽이 할 수 있는 가장 확실한 확인이다. 모델이 글을 얼마나 잘 읽는지와 무관하게,
    글에 적힌 숫자가 원문과 다르면 여기서 드러난다.
    """
    out = []
    for name, label in FIELDS.items():
        a, b = getattr(claimed, name), getattr(original, name)
        same = a == b if isinstance(a, str) or isinstance(b, str) or a is None or b is None else abs(a - b) < 1e-9
        if not same:
            out.append(f"{label}: 받은 값 {a}, 원문 {b}")
    return out


def fetch_original(rcept_no: str, key: str, get=None) -> str | None:
    """전자공시에서 공시 원문을 받아 글로 돌려준다. 받지 못하면 None."""
    import io
    import zipfile

    if get is None:
        import requests

        get = requests.get
    r = get(DOCUMENT_API, params={"crtfc_key": key, "rcept_no": rcept_no}, timeout=30)
    if not r.content.startswith(b"PK"):
        return None
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        names = [n for n in z.namelist() if n.lower().endswith(".xml")]
        return z.read(names[0]).decode("utf-8", errors="replace") if names else None


def verify_numbers(claimed, key: str, get=None) -> SourceCheck:
    """받은 공시 숫자를 전자공시 원문과 대조한다(G4c).

    verify_dart는 그런 공시가 있는지만 본다. 이것은 원문을 받아 코드로 읽고 숫자를 하나씩 맞춰 본다.
    공시 주소만 진짜이고 숫자가 바뀐 글은 verify_dart를 지나가지만 여기서 걸린다.
    """
    from . import dart

    number = receipt_no(claimed.url)
    if number is None:
        return SourceCheck(False, "전자공시 주소가 아니거나 접수번호가 없어 원문과 대조할 수 없음")
    xml = fetch_original(number, key, get)
    if xml is None:
        return SourceCheck(False, f"전자공시에서 원문({number})을 받지 못함")
    parsed = dart.parse(xml, number, claimed.item_id, claimed.corp)
    if parsed.disclosure is None:
        return SourceCheck(False, "원문의 표를 읽지 못해 대조할 수 없음: " + "; ".join(parsed.problems)[:120])
    found = differences(claimed, parsed.disclosure)
    if found:
        return SourceCheck(False, "원문과 다른 숫자 → " + "; ".join(found))
    return SourceCheck(True, f"원문과 숫자 {len(FIELDS)}항목이 전부 같음")
