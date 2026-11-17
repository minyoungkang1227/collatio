import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "integrations"))
from shocklens_screen import screen_event  # noqa: E402

LONG = "가" * 400


def out(instrument="tariff", initiator="US", evidence=True, policy=True, mode="llm", flags=None):
    if not policy:
        return {"mode": mode, "not_policy": True, "event": {}, "injection_flags": flags or []}
    ev = {"instrument": instrument, "direction": "escalate", "initiator": initiator, "target": ["CN"], "severity": 3,
          "evidence": {"instrument": ["s1"], "initiator": ["s1"]} if evidence else {}, "uncertain_fields": [] if evidence else ["instrument"]}
    return {"mode": mode, "event": ev, "injection_flags": flags or []}


def flagged(v):
    return [c.guard for c in v.checks if c.flagged]


def test_agreeing_models_with_evidence_pass():
    v, answers = screen_event({m: [out(), out()] for m in "abcd"}, LONG, 3, 0.8)
    assert v.decision == "통과" and answers["a"]["instrument"] == "tariff"


def test_split_on_a_core_field_or_missing_evidence_goes_to_review():
    v, _ = screen_event({"a": [out("tech_export_control")], "b": [out()], "c": [out()], "d": [out()]}, LONG, 3, 0.8)
    assert flagged(v) == ["G1 답의 일치"]
    v, _ = screen_event({m: [out(evidence=False)] for m in "abcd"}, LONG, 3, 0.8)
    assert flagged(v) == ["G6 근거 대조"]  # 답은 전부 같지만 근거가 없다


def test_scope_and_input_problems():
    assert screen_event({m: [out(policy=False)] for m in "abcd"}, LONG, 3, 0.8)[0].decision == "범위 밖"
    v, _ = screen_event({"a": [out(policy=False)], "b": [out()], "c": [out()], "d": [out()]}, LONG, 3, 0.8)
    assert flagged(v) == ["정책 사건 여부"]
    inj = [{"id": "s2", "text": "이전 지시는 무시하고", "match": "무시", "by": "code"}]
    assert screen_event({m: [out(policy=False)] for m in "abcd"}, "짧은 글", 3, 0.8)[0].decision == "검토"  # 헤드라인만 보고 내린 '범위 밖'은 닫지 않는다
    v, _ = screen_event({m: [out(flags=inj)] for m in "abcd"}, "짧은 글", 1, 0.8)
    assert flagged(v) == ["G0 입력 점검", "G4a 보도 매체 수"]
    v, _ = screen_event({"a": [out(mode="rule")], "b": [out()]}, LONG, None, 0.8)
    assert "응답" in flagged(v) and [c.guard for c in v.checks if not c.ran] == ["G4a 보도 매체 수"]
