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
    ("op_yoy_pct", 9, None, "잠정실적 공시만. 영업이익의 전년 동기 대비 변동률(%). 32% 감소면 -32. 공시에 적힌 숫자를 그대로 옮긴다"),
    ("op_turn", 10, "없음,적자전환,흑자전환,적자지속", "잠정실적 공시만. 영업이익이 흑자에서 적자로 바뀌었으면 적자전환"),
    ("intensity_true", 9, "1,2,3,4,5", "강도. 위 두 칸을 채운 공시는 비워 둔다(자동 계산). 그 밖에는 작성법 시트의 기준표로 직접 정한다"),
    ("direction_text", 9, "-1,0,1", "방향. 위 두 칸을 채운 공시는 비워 둔다(자동 계산). 그 밖에는 글에 적힌 사실만으로 직접 정한다"),
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
    -32, "없음", None, None, "clear", "영업이익 32% 감소가 공시로 확인됨", 1, 2, 5,
    "가나전자는 3분기 영업이익이 전년 동기 대비 32% 증가한 1,150억 원이라고 공시했다. 회사는 주력 제품의 판매 단가 상승을 원인으로 들었다.",
]
# 잠정실적 공시는 숫자만 옮긴다. 요약, 정답, 난이도, 뒤집은 글은 변환할 때 만들어진다.
D_COLUMNS = [
    ("item_id", 9, None, "d001부터 순서대로"),
    ("corp", 16, None, "회사 이름"),
    ("date", 12, None, "공시일 YYYY-MM-DD"),
    ("period", 14, None, "예: 2026년 3분기"),
    ("unit", 8, "백만원,억원", "공시에 적힌 금액 단위"),
    ("url", 26, None, "공시 원문 주소"),
    ("revenue", 12, None, "당해 분기 매출액"),
    ("revenue_yoy", 10, None, "매출액 전년 동기 대비 증감률(%). 감소는 음수"),
    ("revenue_qoq", 10, None, "매출액 전기 대비 증감률(%)"),
    ("op", 12, None, "당해 분기 영업이익. 손실은 음수"),
    ("op_yoy", 10, None, "영업이익 전년 동기 대비 증감률(%). 공시에 흑자전환·적자전환·적자지속이라 적혀 있으면 그 말을 그대로"),
    ("op_qoq", 10, None, "영업이익 전기 대비 증감률(%) 또는 전환"),
    ("net", 12, None, "당해 분기 당기순이익. 손실은 음수"),
    ("net_yoy", 10, None, "당기순이익 전년 동기 대비 증감률(%) 또는 전환"),
    ("cum_op", 12, None, "누계 영업이익. 1분기 공시처럼 누계가 따로 없으면 비운다"),
    ("cum_op_yoy", 10, None, "누계 영업이익 전년 동기 대비 증감률(%) 또는 전환"),
    ("n_independent_sources", 9, "1,2,3,4,5", "독립 출처 수. 공시 원문을 1로 센다"),
    ("n_reports", 9, "1,2,3,4,5", "같은 내용을 실은 글 수. 5건 이상은 5"),
]
D_EXAMPLE = ["예시", "가나전자", "2026-10-20", "2026년 3분기", "억원", "https://example.com/1",
             8200, -4.1, 6.3, 1150, -32, 18.5, 640, -45.2, 2890, -12.4, 1, 3]

GUIDE = [
    ("공시 시트", "잠정실적 공시는 '공시' 시트에 숫자만 옮긴다. 요약 문장, 강도와 방향, 난이도, 사실을 뒤집은 글은 변환할 때 숫자에서 만들어진다. '라벨' 시트에는 공시가 아닌 뉴스(정책, 미확인 보도)만 적는다."),
    ("공시 고르기", "후보 목록의 위에서부터 차례로 고른다. 골라 뽑지 않는다. 영업이익이 적자지속인 공시는 건너뛴다."),
    ("공시 숫자", "공시 원문 표의 '당해실적', '전기 대비 증감률', '전년 동기 대비 증감률', '누계실적' 칸을 그대로 옮긴다. 계산하거나 반올림하지 않는다."),
    ("이 파일은", "뉴스 100건의 요약과 정답을 적는 양식이다. '라벨' 시트의 노란 칸을 채운다."),
    ("예시 행", "'라벨' 시트 2행(회색)은 지어낸 예시다. 변환할 때 자동으로 빠진다. 지우지 않아도 된다."),
    ("순서", "① summary를 쓴다 → ② 공시면 숫자 두 칸을, 아니면 강도와 방향을 채운다 → ③ 근거를 적는다 → ④ 출처를 센다 → ⑤ fact_flip_text를 쓴다."),
    ("자동 계산", "잠정실적 공시는 op_yoy_pct와 op_turn만 적는다. 강도와 방향은 변환할 때 규칙으로 계산된다: 변동 30% 이상 또는 적자·흑자 전환은 강도 4, 10% 이상은 3, 그 미만은 2. 방향은 증가 +1, 감소 -1."),
    ("뒤집기 제외", "뒤집으면 말이 안 되는 건(100% 넘는 증가를 감소로 바꾸는 경우 등)은 fact_flip_text에 '제외: 이유'라고 적는다. 그 뉴스는 뒤집기 변형에서만 빠진다."),
    ("적자지속", "적자가 이어진 공시는 변동률의 뜻이 모호해 자동 계산하지 않는다. op_turn에 적자지속을 고르고 강도와 방향을 직접 채운다."),
    ("스스로 점검", "공시에도 강도와 방향을 직접 적어 두면, 변환할 때 규칙 값과 몇 건이 다른지 알려 준다. 정답에는 규칙 값이 쓰인다."),
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

    ds = wb.create_sheet("공시", 0)
    for c, (name, width, choices, _) in enumerate(D_COLUMNS, start=1):
        cell = ds.cell(row=1, column=c, value=name)
        cell.font = Font(name=FONT, bold=True, color="FFFFFF")
        cell.fill = HEAD
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        letter = cell.column_letter
        ds.column_dimensions[letter].width = width
        if choices:
            dv = DataValidation(type="list", formula1=f'"{choices}"', allow_blank=True, showErrorMessage=True)
            dv.error, dv.errorTitle = f"{choices} 중에서 고르세요", "값 확인"
            ds.add_data_validation(dv)
            dv.add(f"{letter}3:{letter}{ROWS}")
        for r in range(3, ROWS + 1):
            cell = ds.cell(row=r, column=c)
            cell.fill = INPUT
            cell.font = Font(name=FONT)
        ex = ds.cell(row=2, column=c, value=D_EXAMPLE[c - 1])
        ex.fill = EXAMPLE
        ex.font = Font(name=FONT, italic=True)
    ds.row_dimensions[1].height = 32
    ds.freeze_panes = "C3"

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
    start += len(COLUMNS) + 2
    guide.cell(row=start, column=1, value="공시 시트 열").font = Font(name=FONT, bold=True)
    for r, (name, _, choices, desc) in enumerate(D_COLUMNS, start=start + 1):
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
