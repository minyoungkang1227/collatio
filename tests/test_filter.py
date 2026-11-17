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
    assert [c.guard for c in v.checks if not c.ran] == ["G3 말 바꿔 다시 묻기", "G4b 출처 대조", "G6 근거 대조"]


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
            assert "전년 동기 대비 32% 감소" in inp.text or "지난해 같은 분기보다 32% 줄었다" in inp.text
            return Completion(self.text)

    good = '{"intensity":4,"direction":-1,"basis_metric":"영업이익_전년동기대비","basis_value":"32% 감소"}'
    bad = '{"intensity":4,"direction":1,"basis_metric":"영업이익_전기대비","basis_value":"18.5% 증가"}'
    d = Disclosure(item_id="d1", corp="가나전자", date="2026-10-20", period="2026년 3분기", unit="억원", url="https://example.com",
                   revenue=8200, revenue_yoy=-4.1, revenue_qoq=6.3, op=1150, op_yoy=-32, op_qoq=18.5, net=640, net_yoy=-45.2)
    assert screen_disclosure(d, [Reader("a", good), Reader("b", good)], "s", 2, primary_verified=True, probe=True).decision == "통과"
    assert screen_disclosure(d, [Reader("a", good), Reader("b", good)], "s", 2).decision == "검토"  # 출처를 확인하지 않았고 독립 출처가 1곳뿐
    v = screen_disclosure(d, [Reader("a", good), Reader("b", good), Reader("c", good), Reader("d", good), Reader("e", bad)], "s", 2, primary_verified=True)
    assert v.decision == "검토" and "e → 영업이익_전기대비 18.5% 증가" in v.reasons[0]


def test_answer_that_moves_with_wording_goes_to_review():
    same = {m: [out(-1)] * 3 for m in MODELS}
    v = screen(same, figure=-32.0, primary_verified=True, probe_outputs={m: [out(1)] * 3 for m in MODELS})
    assert [c.guard for c in v.checks if c.flagged] == ["G3 말 바꿔 다시 묻기"]
    assert screen(same, figure=-32.0, primary_verified=True, probe_outputs=same).decision == "통과"


def test_dart_check_needs_the_receipt_to_exist_for_that_company():
    from echoguard.source import receipt_no, verify_dart

    class Reply:
        def __init__(self, body):
            self.body = body

        def json(self):
            return self.body

    listing = {"status": "000", "total_page": 1, "list": [
        {"rcept_no": "20261020900123", "corp_name": "가나전자", "report_nm": "연결재무제표기준영업(잠정)실적(공정공시)"}]}
    get = lambda url, params, timeout: Reply(listing)
    url = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20261020900123"
    assert receipt_no(url) == "20261020900123" and receipt_no("https://example.com/?rcpNo=20261020900123") is None
    assert verify_dart(url, "(주)가나전자", "k", get).verified
    assert not verify_dart(url, "다라화학", "k", get).verified
    assert not verify_dart(url.replace("900123", "900999"), "가나전자", "k", get).verified
    assert not verify_dart("https://blog.example.com/post", "가나전자", "k", get).verified


def test_drift_reports_changed_answers_and_versions():
    from echoguard.drift import compare
    from echoguard.schema import RunRecord

    def rec(item, direction, version):
        return RunRecord(item_id=item, perturbation="original", model="m", run=0, track="institutional", output=out(direction),
                         data_version="0.3", model_version=version, called_at="2026-11-17T00:00:00+00:00", input_tokens=0, output_tokens=0, raw="")

    r = compare([rec("a", -1, "v1"), rec("b", 1, "v1")], [rec("a", -1, "v2"), rec("b", -1, "v2")])["m"]
    assert r["share_changed"] == 0.5 and r["changed_items"] == ["b"] and r["version_changed"]


def _disclosure(**over):
    from echoguard.disclosure import Disclosure

    base = dict(item_id="d1", corp="가나전자", date="2026-10-20", period="2026년 3분기", unit="억원",
                url="https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20261020900123",
                revenue=8200, revenue_yoy=-4.1, revenue_qoq=6.3, op=1150, op_yoy=-32, op_qoq=18.5, net=640, net_yoy=-45.2)
    return Disclosure(**{**base, **over})


def test_input_check_finds_numbers_that_contradict_each_other():
    from echoguard.disclosure import quality

    assert quality(_disclosure()) == []
    assert any("적자전환" in p for p in quality(_disclosure(op_yoy="적자전환")))          # 이익인데 적자전환
    assert any("손실이면" in p for p in quality(_disclosure(op=-300, op_qoq="적자전환")))  # 손실인데 숫자 변동률
    assert any("매출액보다 크다" in p for p in quality(_disclosure(op=115000)))            # 단위 혼동
    assert any("접수일" in p for p in quality(_disclosure(date="2026-10-21")))
    assert any("기준일" in p for p in quality(_disclosure(), news_from="2026-11-01"))


def test_bad_input_is_stopped_before_any_model_is_called_and_every_verdict_is_logged(tmp_path):
    from echoguard import audit
    from echoguard.panel import Completion

    calls = []

    class Reader:
        name, family, tier = "a", "x", None

        def complete(self, system, inp, run):
            calls.append(run)
            return Completion('{"intensity":4,"direction":-1,"basis_metric":"영업이익_전년동기대비","basis_value":"32% 감소"}', model_version="v1")

    log = tmp_path / "decisions.jsonl"
    bad = screen_disclosure(_disclosure(op_yoy="적자전환"), [Reader()], "s", 2, log=log)
    assert bad.decision == "검토" and bad.checks[0].guard == "G0 입력 점검" and calls == []
    good = screen_disclosure(_disclosure(), [Reader()], "s", 2, primary_verified=True, log=log)
    assert good.decision == "통과" and len(calls) == 2

    s = audit.summary(log)
    assert s["n_decisions"] == 2 and s["review_rate"] == 0.5 and s["flagged_by"] == {"G0 입력 점검": 1}
    assert s["model_versions_seen"] == ["a: ", "a: v1"] and len(s["human_reviews"]["pending"]) == 1 and s["log_intact"]
    audit.review(log, s["human_reviews"]["pending"][0], "minyoung", "반려", "숫자 다시 옮길 것")
    assert audit.summary(log)["human_reviews"] == {"done": 1, "반려": 1, "pending": []}

    lines = log.read_text(encoding="utf-8").splitlines()
    log.write_text("\n".join([lines[0].replace('"검토"', '"통과"')] + lines[1:]) + "\n", encoding="utf-8")
    assert audit.verify(log) and not audit.summary(log)["log_intact"]
