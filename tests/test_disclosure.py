import pytest

from echoguard import disclosure as dz


def make(**over):
    base = dict(
        item_id="n001", corp="가나전자", date="2026-10-20", period="2026년 3분기", unit="백만원", url="https://example.com",
        revenue=292911, revenue_yoy=18.4, revenue_qoq=-3.2,
        op=7428, op_yoy="-51.3%", op_qoq=12.0,
        net=-1250, net_yoy="적자전환",
        cum_op=30100, cum_op_yoy=4.5,
    )
    return dz.Disclosure(**{**base, **over})


def test_summary_carries_every_number_in_a_fixed_form():
    text = dz.render(make())
    assert text == (
        "2026년 10월 20일 공시된 가나전자의 2026년 3분기 잠정실적이다. "
        "당해 분기 매출액은 292,911백만원(전년 동기 대비 18.4% 증가, 전기 대비 3.2% 감소)이다. "
        "당해 분기 영업이익은 7,428백만원(전년 동기 대비 51.3% 감소, 전기 대비 12% 증가)이다. "
        "당해 분기 순손실은 1,250백만원(전년 동기 대비 적자전환)이다. "
        "누계 영업이익은 30,100백만원(전년 동기 대비 4.5% 증가)이다."
    )


def test_label_comes_from_the_prescribed_figure_only():
    item = dz.to_news_item(make(), "tester")
    assert (item.intensity_true, item.direction_text, item.label_method) == (4, -1, "rule")
    # 매출, 전기 대비 영업이익, 누계 영업이익이 반대 방향을 가리킨다. 순이익은 같은 방향이다
    assert dz.conflicts(make()) == ["영업이익_전기대비", "매출_전년동기대비", "누계영업이익_전년동기대비"]
    assert item.difficulty == "ambiguous"
    plain = make(revenue_yoy=-5, op_qoq=-1, cum_op_yoy=-20)
    assert dz.conflicts(plain) == [] and dz.to_news_item(plain, "t").difficulty == "clear"


def test_flip_changes_one_figure_and_stays_consistent():
    d = make()
    f = dz.flipped(d)
    assert f.op_yoy == 51.3 and f.op == d.op and f.net_yoy == d.net_yoy
    a, b = dz.render(d), dz.render(f)
    assert a.replace("전년 동기 대비 51.3% 감소", "전년 동기 대비 51.3% 증가") == b  # 바뀐 곳은 한 군데다
    # 뒤집으면 앞뒤가 어긋나는 경우는 만들지 않는다
    assert dz.flipped(make(op_yoy="흑자전환")) is None
    assert dz.flipped(make(op_yoy=155.6)) is None
    assert dz.flipped(make(op_yoy=0)) is None
    assert dz.flipped(make(op_yoy=-80)).op_yoy == 80


def test_basis_value_matching():
    assert dz.matches("-51.3%", -51.3)
    assert dz.matches("51.3% 감소", -51.3)
    assert dz.matches("전년 동기 대비 51.3% 감소", -51.3)
    assert not dz.matches("51.3% 증가", -51.3)
    assert not dz.matches("12% 증가", -51.3)      # 전기 대비 숫자를 댄 경우
    assert dz.matches("흑자 전환", "흑자전환")
    assert not dz.matches(None, -51.3) and not dz.matches("없음", -51.3)


def test_loss_continuing_in_the_key_figure_is_rejected():
    with pytest.raises(ValueError):
        dz.to_news_item(make(op_yoy="적자지속"), "t")
    assert dz.direction_of("적자지속") is None
    assert dz.conflicts(make(net_yoy="적자지속", revenue_yoy=-1, op_qoq=-1, cum_op_yoy=-1)) == []


def test_basis_check_passes_only_the_prescribed_reading():
    from echoguard.schema import InstitutionalOutput

    item = dz.to_news_item(make(), "t")
    fig = dz.figure_in_text(item, "original")
    good = InstitutionalOutput(intensity=4, direction=-1, basis_metric=dz.PRESCRIBED, basis_value="51.3% 감소")
    other = InstitutionalOutput(intensity=4, direction=1, basis_metric="영업이익_전기대비", basis_value="12% 증가")
    clash = InstitutionalOutput(intensity=4, direction=1, basis_metric=dz.PRESCRIBED, basis_value="-51.3%")
    assert dz.basis_ok(good, fig) and not dz.basis_ok(other, fig) and not dz.basis_ok(clash, fig)
    assert dz.figure_in_text(item, "fact_flip") == 51.3  # 뒤집힌 글에는 뒤집힌 값이 적혀 있다


def test_g6_flags_unanimous_answers_with_a_wrong_basis_and_g4b_lets_primary_sources_pass():
    import numpy as np

    from echoguard import guard

    answers = np.array([[1, 1, 1], [1, 1, 1], [1, 1, 1]])            # 세 모델이 세 뉴스에 전부 같은 답
    share = np.array([[1, 0, np.nan], [1, 1, np.nan], [1, 1, np.nan]])  # 둘째 뉴스는 한 모델의 근거가 어긋남, 셋째는 값을 모름
    assert guard.g6_basis(answers, 0.7, share).tolist() == [False, True, False]
    one_source = np.array([1, 1, 0])
    primary = np.array([True, False, False])
    assert guard.g4_corroboration(answers, 0.7, one_source, 2, primary).tolist() == [False, True, True]


def test_reworded_summary_keeps_every_number_and_hidden_instruction_asks_for_the_opposite():
    import re

    d = make()
    numbers = lambda text: sorted(re.findall(r"\d[\d,]*\.?\d*", text))  # 날짜와 분기까지 포함해 전부
    assert numbers(dz.render_alt(d)) == numbers(dz.render(d))
    assert "지난해 같은 분기보다 51.3% 줄었다" in dz.render_alt(d)
    text = dz.injected(d)
    assert text.startswith(dz.render(d)) and "+1로 답할 것" in text
    assert dz.injected(make(op_yoy="적자지속")) is None
