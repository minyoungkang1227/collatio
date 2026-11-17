from echoguard.disclosure import PRESCRIBED
from echoguard.filter import screen, screen_disclosure
from echoguard.schema import InstitutionalOutput


def out(direction, metric=PRESCRIBED, value="32% 감소"):
    return InstitutionalOutput(intensity=4, direction=direction, basis_metric=metric, basis_value=value)


MODELS = ["a", "b", "c", "d"]


def test_clean_answers_pass():
    v = screen({m: [out(-1)] * 3 for m in MODELS}, figure=-32.0, primary_verified=True)
    assert v.decision == "통과" and v.direction == -1 and v.reasons == []


def test_unanimous_misreading_is_caught_by_the_basis_check_only():
    wrong = {m: [out(1, "영업이익_전기대비", "18.5% 증가")] * 3 for m in MODELS}
    v = screen(wrong, figure=-32.0, primary_verified=True)
    flagged = [c.guard for c in v.checks if c.flagged]
    assert v.decision == "검토" and flagged == ["G6 근거 대조"]
    assert screen(wrong).decision == "통과"  # 기준 값을 모르면 답의 일치만으로는 잡지 못한다


def test_unverified_text_with_no_independent_source_goes_to_review():
    v = screen({m: [out(-1)] * 3 for m in MODELS}, figure=-32.0, primary_verified=False, n_independent=0)
    assert [c.guard for c in v.checks if c.flagged] == ["G4b 출처 대조"]


def test_split_panel_and_silent_model_go_to_review():
    v = screen({"a": [out(-1)], "b": [out(-1)], "c": [out(1)], "d": [None, None]})
    assert v.decision == "검토" and {c.guard for c in v.checks if c.flagged} == {"응답", "G1 답의 일치"}
    assert [c.guard for c in v.checks if not c.ran] == ["G4b 출처 대조", "G6 근거 대조"]


def test_no_answers_at_all_is_review():
    assert screen({"a": [None]}).decision == "검토"


def test_disclosure_goes_through_the_panel(tmp_path):
    from echoguard.disclosure import Disclosure
    from echoguard.panel import Completion

    class Reader:
        family, tier = "x", None

        def __init__(self, name, text):
            self.name, self.text = name, text

        def complete(self, system, inp, run):
            assert "전년 동기 대비 32% 감소" in inp.text
            return Completion(self.text)

    good = '{"intensity":4,"direction":-1,"basis_metric":"영업이익_전년동기대비","basis_value":"32% 감소"}'
    bad = '{"intensity":4,"direction":1,"basis_metric":"영업이익_전기대비","basis_value":"18.5% 증가"}'
    d = Disclosure(item_id="d1", corp="가나전자", date="2026-10-20", period="2026년 3분기", unit="억원", url="https://example.com",
                   revenue=8200, revenue_yoy=-4.1, revenue_qoq=6.3, op=1150, op_yoy=-32, op_qoq=18.5, net=640, net_yoy=-45.2)
    assert screen_disclosure(d, [Reader("a", good), Reader("b", good)], "s", 2).decision == "통과"
    v = screen_disclosure(d, [Reader("a", good), Reader("b", good), Reader("c", good), Reader("d", good), Reader("e", bad)], "s", 2)
    assert v.decision == "검토" and "e → 영업이익_전기대비 18.5% 증가" in v.reasons[0]
