"""plugins/units_long.py: 같은 핵심 사실에서 나온 길이별 문항은 정답이 같고, 정답은 손계산과 맞는다."""
import importlib.util
import re
from collections import defaultdict
from pathlib import Path

from kfin_eval.schema import validate_all

ROOT = Path(__file__).resolve().parents[1]


def _gen():
    spec = importlib.util.spec_from_file_location("units_long", ROOT / "plugins" / "units_long.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_items_valid_and_paired():
    U = _gen()
    items = U.units_long_items(40, seed=1)
    assert len(items) == 40
    assert not {k: v for k, v in validate_all(items).items() if v[0]}
    groups = defaultdict(list)
    for it in items:
        groups[it["meta"]["group"]].append(it)
    for g in groups.values():
        assert [i["meta"]["variant"] for i in g] == [f"len_{x}" for x in U.LENGTHS]
        assert len({i["answer"]["value"] for i in g}) == 1          # 길이만 다르고 정답은 같다


def test_answer_matches_hand_calc_and_length_grows():
    U = _gen()
    items = U.units_long_items(40, seed=7)
    for it in items:
        m = re.search(r"연결 영업이익은 ([\d,]+)백만원으로 전년 동기 대비 ([\d.]+)% (증가|감소)", it["question"])
        op, p = int(m[1].replace(",", "")), float(m[2]) * (1 if m[3] == "증가" else -1)
        assert abs(op / (1 + p / 100) / 100 - it["answer"]["value"]) < 1e-3
    n = {L: min(i["meta"]["n_numbers"] for i in items if i["id"].endswith(L)) for L in U.LENGTHS}
    assert n["short1"] < n["short4"] < n["long16"] and n["long16"] >= 16


def test_mixed_has_other_units_but_core_in_million():
    U = _gen()
    for it in U.units_long_items(40, seed=3):
        if it["id"].endswith("mixed"):
            body = it["question"]
            assert "천원" in body or "억원" in body.split("물음:")[0]
            assert re.search(r"연결 영업이익은 [\d,]+백만원", body)


def _report():
    spec = importlib.util.spec_from_file_location("ulr", ROOT / "scripts" / "units_long_report.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_report_counts_pairs_and_digit_errors():
    R = _report()
    rows = []
    for g in range(6):          # 6묶음: short1은 모두 맞고, long16은 5묶음에서 10배 작게 틀림
        for L in R.LENGTHS:
            wrong = L == "long16" and g < 5
            got = 75.739 if wrong else 757.39
            rows.append({"item_id": f"ulong-s1-{g:03d}-{L}", "model": "m", "score": 0.0 if wrong else 1.0,
                         "detail": f"응답 {got} / 정답 757.39 (허용 ±1.0%)"})
    models, cell, pairs, digits = R.analyze(rows)
    assert cell[("m", "long16")] == [1, 6]
    b, c, p = pairs[("m", "long16")]
    assert (b, c) == (5, 0) and abs(p - 0.0625) < 1e-9      # 2 × (1/2)^5
    assert digits[("m", "long16")]["자릿수 10^-1"] == 5
    assert "| m | short1 → long16 | 5 | 0 | 0.062 | 차이 없음 |" in R.render("t", models, cell, pairs, digits)
    assert R.digit_error("응답 757.39 / 정답 757.39") is None
    assert R.digit_error("응답 700 / 정답 757.39") is None
