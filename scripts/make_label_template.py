"""라벨링용 엑셀 양식을 만든다:  python scripts/make_label_template.py

data/labels/labeling_template.xlsx가 생긴다. 이 파일을 복사해 채운 뒤 scripts/xlsx_to_labels.py로 변환한다.
"""

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

ROOT = Path(__file__).resolve().parents[1]
FONT = "Malgun Gothic"
HEAD = PatternFill("solid", fgColor="1F3864")
INPUT = PatternFill("solid", fgColor="FFFF00")   # 직접 채우는 칸
EXAMPLE = PatternFill("solid", fgColor="D9D9D9")
ROWS = 130

# (열 이름, 너비, 고를 수 있는 값, 설명)
COLUMNS = [
    ("item_id", 9, None, "n001부터 순서대로"),
    ("date", 12, None, "기사 날짜 YYYY-MM-DD. 2026-10-01 이후만"),
    ("type", 8, "stock,macro", "stock 종목 / macro 거시·정책"),
    ("source", 14, None, "매체 또는 공시처"),
    ("url", 26, None, "원문 주소"),
    ("title", 30, None, "기사 제목"),
    ("summary", 60, None, "직접 쓴 2~3문장. 수치·주체·날짜를 넣고 평가어는 빼기"),
    ("intensity_true", 9, "1,2,3,4,5", "강도. 작성법 시트의 기준표"),
    ("direction_text", 9, "-1,0,1", "글에 적힌 사실만으로 본 방향. 주가를 보지 않고 정한다"),
    ("difficulty", 11, "clear,ambiguous", "명확 / 애매"),
    ("label_basis", 36, None, "방향을 그렇게 본 근거 한 줄"),
    ("source_verified", 9, "1,0", "공시·정부 발표 등 1차 출처가 확인되면 1"),
    ("n_independent_sources", 9, "0,1,2,3,4,5", "따로 확인해 준 독립 출처 수. 받아쓴 글은 세지 않는다"),
    ("n_reports", 9, "1,2,3,4,5", "같은 내용을 실은 글 수. 받아쓴 글도 센다. 5건 이상은 5"),
    ("fact_flip_text", 60, None, "summary에서 핵심 사실 하나만 뒤집은 글. 직접 쓴다"),
]
EXAMPLE_ROW = [
    "예시", "2026-10-20", "stock", "전자공시", "https://example.com/1", "가나전자 3분기 영업이익 32% 감소",
    "가나전자는 3분기 영업이익이 전년 동기 대비 32% 감소한 1,150억 원이라고 공시했다. 회사는 주력 제품의 판매 단가 하락을 원인으로 들었다.",
    4, -1, "clear", "영업이익 32% 감소가 공시로 확인됨", 1, 2, 5,
    "가나전자는 3분기 영업이익이 전년 동기 대비 32% 증가한 1,150억 원이라고 공시했다. 회사는 주력 제품의 판매 단가 상승을 원인으로 들었다.",
]
GUIDE = [
    ("이 파일은", "뉴스 100건의 요약과 정답을 적는 양식이다. '라벨' 시트의 노란 칸을 채운다."),
    ("예시 행", "'라벨' 시트 2행(회색)은 지어낸 예시다. 변환할 때 자동으로 빠진다. 지우지 않아도 된다."),
    ("순서", "① summary를 쓴다 → ② direction_text와 강도를 정한다 → ③ 근거를 적는다 → ④ 출처를 센다 → ⑤ fact_flip_text를 쓴다."),
    ("주가 금지", "direction_text를 정할 때 주가를 보지 않는다. 주가로 본 방향은 나중에 프로그램이 따로 채운다."),
    ("모델 금지", "라벨을 정할 때 AI에게 묻지 않는다. 채점 대상이 정답을 정하면 실험이 무효가 된다."),
    ("구성 목표", "종목 70 / 거시 30,  명확 80 / 애매 20,  출처 확인 70 / 미확인 30,  방향은 세 가지가 고르게."),
    ("강도 1", "관측·전망·검토 보도. 확정된 조치나 수치가 없다."),
    ("강도 2", "확정된 사실이지만 영향이 작다. 핵심 수치 변동 10% 미만, 또는 일정·대상이 불명확한 방침."),
    ("강도 3", "확정된 사실이고 영향이 중간. 변동 10% 이상 30% 미만, 또는 시행일·대상이 명시된 정책 발표."),
    ("강도 4", "확정된 사실이고 영향이 크다. 변동 30% 이상, 적자·흑자 전환, 핵심 산업이나 시장 전체에 적용되는 조치의 시행."),
    ("강도 5", "존속이나 거래 자체가 걸린 사건. 거래 정지, 상장폐지 사유, 부도·회생 신청, 자산 동결, 전면 금지."),
    ("핵심 수치", "영업이익의 전년 동기 대비 변동률. 없으면 매출. 수주·계약은 직전 연 매출 대비 비율. 걸치면 높은 쪽."),
    ("독립 출처", "공시·정부 발표, 그리고 자체 취재로 확인한 주요 매체만 센다. 받아쓴 기사, 통신사 전재, 커뮤니티 글은 세지 않는다."),
    ("사실 뒤집기", "summary에서 핵심 사실 하나만 반대로 바꾼다(감소→증가, 승인→불허). 나머지 문장은 그대로 둔다. 실제 회사명이 들어가므로 이 열은 공개 리포에 올리지 않는다."),
    ("다 채우면", "python scripts/xlsx_to_labels.py 채운파일.xlsx  를 실행한다. 빠진 칸과 구성 비율을 알려 준다."),
]


def build(path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "라벨"
    for c, (name, width, choices, _) in enumerate(COLUMNS, start=1):
        cell = ws.cell(row=1, column=c, value=name)
        cell.font = Font(name=FONT, bold=True, color="FFFFFF")
        cell.fill = HEAD
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        letter = cell.column_letter
        ws.column_dimensions[letter].width = width
        if choices:
            dv = DataValidation(type="list", formula1=f'"{choices}"', allow_blank=True, showErrorMessage=True)
            dv.error, dv.errorTitle = f"{choices} 중에서 고르세요", "값 확인"
            ws.add_data_validation(dv)
            dv.add(f"{letter}3:{letter}{ROWS}")
        for r in range(3, ROWS + 1):
            cell = ws.cell(row=r, column=c)
            cell.fill = INPUT
            cell.font = Font(name=FONT)
            cell.alignment = Alignment(vertical="top", wrap_text=True)
    for c, value in enumerate(EXAMPLE_ROW, start=1):
        cell = ws.cell(row=2, column=c, value=value)
        cell.fill = EXAMPLE
        cell.font = Font(name=FONT, italic=True)
        cell.alignment = Alignment(vertical="top", wrap_text=True)
    ws.row_dimensions[1].height = 32
    ws.freeze_panes = "B3"

    guide = wb.create_sheet("작성법")
    guide.column_dimensions["A"].width = 14
    guide.column_dimensions["B"].width = 110
    for r, (key, text) in enumerate(GUIDE, start=1):
        guide.cell(row=r, column=1, value=key).font = Font(name=FONT, bold=True)
        cell = guide.cell(row=r, column=2, value=text)
        cell.font = Font(name=FONT)
        cell.alignment = Alignment(wrap_text=True, vertical="top")
    start = len(GUIDE) + 2
    guide.cell(row=start, column=1, value="열 설명").font = Font(name=FONT, bold=True)
    for r, (name, _, choices, desc) in enumerate(COLUMNS, start=start + 1):
        guide.cell(row=r, column=1, value=name).font = Font(name=FONT, bold=True)
        cell = guide.cell(row=r, column=2, value=desc + (f"  (고르는 값: {choices})" if choices else ""))
        cell.font = Font(name=FONT)
        cell.alignment = Alignment(wrap_text=True, vertical="top")
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


if __name__ == "__main__":
    out = ROOT / "data" / "labels" / "labeling_template.xlsx"
    build(out)
    print(f"만들었습니다: {out}")
