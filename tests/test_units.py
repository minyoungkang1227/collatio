"""단위 환산 점검. 아래 풀이는 실제 응답의 꼴을 본떠 지어낸 것이다."""
from collatio import units


def test_reads_numbers_with_units_including_particles_and_formulas():
    text = "전년 동기는 $3{,}048.16 \\text{ (백만원)}$이며 30.48억원입니다. 출하량은 2,982,453.2kg이다. 인원 12.5천 명."
    assert units.mentions(text) == [(3048.16, "백만원"), (30.48, "억원"), (2982453.2, "kg"), (12.5, "천명")]


def test_does_not_read_other_words_as_units():
    assert units.mentions("3개월 뒤 원금 2,000만원, 건물 2개동\n\n최종답: 2468.0\n\n원금은") == [(2000.0, "만원")]


def test_wrong_power_of_ten_between_stated_value_and_final_answer_is_flagged():
    wrong = "1,133 ÷ 0.3717 ≈ 3,048.16 (백만원)\n억원으로 환산하면 304.82억원입니다.\n\n최종답: 304.82"
    right = "1,133 ÷ 0.3717 = 3,048.16백만원이며, 억원으로 환산하면 30.48억원입니다.\n\n최종답: 30.48"
    assert units.check(wrong, "억원", 304.82).flagged
    assert units.check(right, "억원", 30.48).status == "일치"


def test_no_pre_conversion_value_means_not_checked_rather_than_passed():
    assert units.check("계산하면 30.48억원입니다.\n최종답: 30.48", "억원", 30.48).status == "검사 안 함"
    assert units.check("답은 12%", "%", 12).status == "검사 안 함"


def test_written_arithmetic_is_recomputed():
    wrong = "지난해 출하량은 \\(3{,}954{,}733 \\div 1.326 \\div 1{,}000 = 2.98245\\ldots\\)t입니다.\n최종답: 2.98"
    right = "지난해 출하량 = 3,954,733 ÷ 1.326 ≈ 2,982,453.2kg ≈ 2,982.45t\n최종답: 2982.45"
    assert units.recompute(wrong).flagged and "10의 -3제곱" in units.recompute(wrong).detail
    assert units.recompute(right).status == "일치"


def test_truncated_expressions_and_non_arithmetic_are_left_alone():
    # 단위가 식 안에 끼어 앞부분이 잘리는 경우: 괄호 안만 읽어 1.234와 2,468을 비교하면 안 된다
    assert not units.recompute("2,000만원 × (1 + 0.078 × 3) = 2,000 × 1.234 = 2,468.0만원").flagged
    assert not units.recompute("지급액 = 10,000,000원 × (69 ÷ 100) = 6,900,000원 = 690.0만원").flagged
    assert units.equations("__import__('os').system('x') = 1") == []      # 식이 아닌 것은 계산하지 않는다
    assert units.equations("9**9**9 = 1") == []


def test_unit_check_counts_caught_and_false_flags():
    from kfin_eval import guardlink as GL

    items = {"q1": {"answer_type": "numeric", "answer": {"value": 30.48, "unit": "억원"}},
             "q2": {"answer_type": "choice", "answer": {"value": "A"}}}
    responses = [
        {"model": "a", "item_id": "q1", "response": "3,048.16백만원 = 304.82억원\n최종답: 304.82"},
        {"model": "b", "item_id": "q1", "response": "3,048.16백만원이며 30.48억원\n최종답: 30.48"},
        {"model": "c", "item_id": "q1", "response": "최종답: 30.48"},
        {"model": "a", "item_id": "q2", "response": "최종답: A"},
    ]
    grades = [{"model": "a", "item_id": "q1", "score": 0.0}, {"model": "b", "item_id": "q1", "score": 1.0},
              {"model": "c", "item_id": "q1", "score": 1.0}, {"model": "a", "item_id": "q2", "score": 1.0}]
    res = GL.unit_check(items, responses, grades)
    assert (res["n"], res["wrong"], res["caught"], res["false_flags"], res["not_checked"]) == (3, 1, 1, 0, 1)
