from pathlib import Path

from echoguard import dart
from echoguard.disclosure import quality, to_news_item

FIX = Path(__file__).parent / "fixtures"


def read(name):
    return dart.parse((FIX / name).read_text(encoding="utf-8"), "20261020900123", "d001", "가나전자")


def test_reads_the_table_as_written():
    p = read("dart_ok.xml")
    d = p.disclosure
    assert p.problems == [] and d.period == "2026년 3분기" and d.unit == "백만원" and d.date == "2026-10-20"
    assert (d.revenue, d.revenue_yoy, d.revenue_qoq) == (8200, -4.1, 6.3)
    assert (d.op, d.op_yoy, d.op_qoq, d.cum_op, d.cum_op_yoy) == (1150, -31.99, 18.56, 2890, -12.4)
    assert (d.net, d.net_yoy) == (-120, "적자지속")  # 손실에서 손실: 공시는 숫자를 적지만 적자지속으로 읽는다
    assert quality(d) == [] and to_news_item(d, "code").direction_text == -1


def test_a_rate_that_contradicts_the_amounts_is_reported():
    p = read("dart_wrong_sign.xml")
    assert any("영업이익 전년 동기 대비" in x and "다르다" in x for x in p.problems)


def test_loss_to_loss_operating_profit_and_corrections():
    p = read("dart_loss_to_loss.xml")
    assert p.disclosure.op_yoy == "적자지속" and p.disclosure.op_qoq == "적자지속"
    assert any("정정" in n for n in p.notes)
    try:
        to_news_item(p.disclosure, "code")
        raise AssertionError("적자지속은 라벨을 만들지 않아야 한다")
    except ValueError:
        pass


def test_unreadable_document_gives_a_reason_not_a_guess():
    p = dart.parse("<DOCUMENT><BODY><P>표가 없는 문서</P></BODY></DOCUMENT>", "20261020900123", "d001", "가나전자")
    assert p.disclosure is None and p.problems
