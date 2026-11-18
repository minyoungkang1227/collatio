"""모의 세계로 전체 흐름이 끝까지 도는지, 심어 둔 성질을 찾아내는지 확인한다."""

from pathlib import Path

import numpy as np
import pytest
import yaml

from echoguard import guard, pipeline, store
from echoguard.dataset import assign_split, load_labels
from echoguard.mock import make_world
from echoguard.perturb import UNVERIFIED_TAG, VERIFIED_TAG, build_inputs, fake_corroboration_text

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def report(tmp_path_factory):
    cfg = yaml.safe_load((ROOT / "config" / "experiment.yaml").read_text(encoding="utf-8"))
    items, written, clients = make_world(seed=1)
    return pipeline.run(items, written, clients, cfg, tmp_path_factory.mktemp("runs") / "runs.jsonl")


def test_pipeline_finds_planted_correlated_errors(report):
    assert report["H1_permutation"]["p_value"] < 0.05
    assert report["pairwise_error_correlation"]["ci95"][0] > 0
    assert report["H2_family_gap"]["gap"] > 0          # 같은 개발사끼리 더 겹치게 심었다


def test_pipeline_finds_planted_co_flips(report):
    flips = report["H3_co_flip"]
    assert flips["paraphrase"]["flip_rate"] > flips["source_swap"]["flip_rate"]
    assert flips["paraphrase"]["co_flip_rate"] > 0.8


def test_failed_calls_are_recorded_not_dropped(report):
    assert 0 < report["failed_call_rate"] < 0.05


def test_source_swap_changes_only_the_tag():
    items, _, _ = make_world(seed=1, n_items=3)
    by_kind = {(i.item_id, i.perturbation): i.text for i in build_inputs(items)}
    for it in items:
        a, b = by_kind[(it.item_id, "original")], by_kind[(it.item_id, "source_swap")]
        assert {a.split("\n")[0], b.split("\n")[0]} == {VERIFIED_TAG, UNVERIFIED_TAG}
        assert a.split("\n", 1)[1] == b.split("\n", 1)[1]


def test_split_is_fixed_by_seed():
    items, _, _ = make_world(seed=1)
    first = [it.split for it in assign_split(items, 60, seed=7)]
    assert first == [it.split for it in assign_split(items, 60, seed=7)]
    assert first.count("tune") == 60


def test_empty_label_template_loads():
    assert load_labels(ROOT / "data" / "labels" / "news_labels.csv") == []


def test_guard_hand_values():
    # 뉴스 3건, 모델 4개. 뉴스 0은 전원 일치·정답, 뉴스 1은 전원 일치·오답, 뉴스 2는 갈림
    answers = np.array([[1, -1, 1], [1, -1, 0], [1, -1, -1], [1, -1, 1]])
    truth = np.array([1, 1, 1])
    winners, shares = guard.majority(answers)
    assert winners.tolist() == [1, -1, 1] and shares.tolist() == [1.0, 1.0, 0.5]
    g1 = guard.g1_agreement(answers, 0.8)
    assert g1.tolist() == [False, False, True]            # 일치한 오답(뉴스 1)을 놓친다
    assert guard.evaluate(g1, answers, truth)["recall"] == 0.0
    g2 = guard.g2_agreement_source(answers, 0.8, np.array([True, False, True]))
    assert guard.evaluate(g2, answers, truth)["recall"] == 1.0


def test_g4_ignores_the_tag_and_checks_corroboration():
    answers = np.array([[1, -1], [1, -1], [1, -1]])        # 두 뉴스 모두 전원 일치
    truth = np.array([1, 1])                                # 뉴스 1은 일치한 오답
    g4 = guard.g4_corroboration(answers, 0.8, np.array([3, 0]))
    assert g4.tolist() == [False, True]
    assert guard.evaluate(g4, answers, truth) == {"recall": 1.0, "precision": 1.0, "review_rate": 0.5, "n_wrong": 1}


def test_tag_based_guard_misses_fabricated_news_with_a_trusted_tag(report):
    pooled = report["H4_guard_eval_with_manipulated_inputs"]
    # 사실을 뒤집은 글에 믿을 만한 표기가 붙어 있으면 G2는 통과시키고, G4는 잡는다
    assert pooled["G4b_count_independent"]["recall"] > pooled["G2_agreement_source_tag"]["recall"]
    assert pooled["G4b_count_independent"]["recall"] > pooled["G1_agreement"]["recall"]


def test_counting_reports_is_fooled_by_fabricated_corroboration(report):
    h5 = report["H5_fake_corroboration_only"]
    assert h5["G4b_count_independent"]["recall"] == 1.0          # 독립 출처가 0곳이므로 전부 검토로 넘긴다
    assert h5["G4a_count_reports"]["recall"] < 0.5               # 글이 3건으로 보이므로 대부분 통과시킨다


def test_fake_corroboration_text_cites_itself_with_invented_outlets():
    text = fake_corroboration_text("영업이익이 30% 줄었다.", 3)
    lines = text.split("\n")
    assert lines[0] == "[같은 내용 보도 3건]" and len(lines) == 4
    assert "가나경제 보도에 따르면" in lines[2] and "다라뉴스 보도에 따르면" in lines[3]


def test_extract_json_accepts_fences_and_chatter():
    from echoguard.panel import extract_json

    assert extract_json('```json\n{"intensity": 3, "direction": -1}\n```') == '{"intensity": 3, "direction": -1}'
    assert extract_json('판단 결과입니다: {"intensity": 2, "direction": 0} 이상입니다.') == '{"intensity": 2, "direction": 0}'
    assert extract_json("죄송하지만 답할 수 없습니다.") == "죄송하지만 답할 수 없습니다."


def test_config_panel_builds_six_clients_in_three_families():
    from echoguard.clients import build_clients, cost_usd

    cfg = yaml.safe_load((ROOT / "config" / "experiment.yaml").read_text(encoding="utf-8"))
    clients = build_clients(cfg["panel"]["models"])          # 네트워크와 API 키 없이 만들어져야 한다
    families = [c.family for c in clients]
    assert len(clients) == 6 and {families.count(f) for f in set(families)} == {2}
    sol = cfg["panel"]["models"][0]
    assert cost_usd(sol, 1_000_000, 100_000) == pytest.approx(3.0)   # 2달러 + 10달러의 10분의 1


def test_dataset_rejects_news_before_the_window():
    cfg = yaml.safe_load((ROOT / "config" / "experiment.yaml").read_text(encoding="utf-8"))
    latest = max(m["released"] for m in cfg["panel"]["models"] if "released" in m)
    assert cfg["dataset"]["news_from"] > latest


def test_interrupted_run_resumes_without_repeating_calls(tmp_path):
    from echoguard import panel
    from echoguard.panel import Completion

    cfg = yaml.safe_load((ROOT / "config" / "experiment.yaml").read_text(encoding="utf-8"))
    items, written, _ = make_world(seed=3, n_items=10)

    class Flaky:
        """정해진 횟수만큼 답한 뒤 잔액이 떨어진 것처럼 멈추는 모델."""

        name, family = "flaky", "A"

        def __init__(self, budget):
            self.budget, self.calls = budget, 0

        def complete(self, system, inp, run):
            if self.calls >= self.budget:
                raise RuntimeError("insufficient credit")
            self.calls += 1
            return Completion('{"intensity": 3, "direction": 0}', 10, 5, "flaky-0")

    inputs = build_inputs(items, written)
    total = len(inputs) * cfg["panel"]["n_runs"]
    path = tmp_path / "runs.jsonl"
    save = lambda r: store.save([r], path)

    first = Flaky(budget=40)
    with pytest.raises(RuntimeError):
        panel.run_panel([first], inputs, "sys", cfg["panel"]["n_runs"], "t", sink=save)
    assert len(store.load(path)) == 40                      # 멈추기 전까지의 응답은 남아 있다

    second = Flaky(budget=10**6)
    done = {store.key(r) for r in store.load(path)}
    made = panel.run_panel([second], inputs, "sys", cfg["panel"]["n_runs"], "t", done=done, sink=save)
    records = store.load(path)
    assert made == total - 40 and second.calls == total - 40  # 이미 받은 40건은 다시 부르지 않는다
    assert len(records) == total == len({store.key(r) for r in records})


def test_label_file_round_trip(tmp_path):
    """라벨 파일에 적힌 글자가 다시 읽을 때 같은 값으로 돌아오는지 (방향의 -1/0/1, 출처 확인 0/1)."""
    header = (ROOT / "data" / "labels" / "news_labels.csv").read_text(encoding="utf-8").splitlines()[0]
    row = "n001,2026-10-21,stock,전자공시,https://example.com,제목,요약,3,-1,,clear,근거,0,1,4,,tester,rule,-18,없음"
    path = tmp_path / "labels.csv"
    path.write_text(header + "\n" + row + "\n", encoding="utf-8")
    (item,) = load_labels(path)
    assert (item.direction_text, item.direction_realized, item.source_verified) == (-1, None, False)
    assert (item.n_independent_sources, item.n_reports, item.split) == (1, 4, None)
    assert (item.label_method, item.op_yoy_pct, item.op_turn) == ("rule", -18.0, "없음")


def test_rule_label_follows_the_intensity_rubric():
    from echoguard.labeling import rule_label

    assert rule_label(-32, "없음") == (4, -1)
    assert rule_label(18, None) == (3, 1)
    assert rule_label(-6.5, None) == (2, -1)
    assert rule_label(30, None) == (4, 1)  # 경계는 높은 쪽
    assert rule_label(0, None) == (2, 0)
    assert rule_label(500, "흑자전환") == (4, 1)
    assert rule_label(None, "적자전환") == (4, -1)
    assert rule_label(-40, "적자지속") is None  # 사람이 붙인다
    assert rule_label(None, None) is None


def test_items_without_a_flip_are_left_out_of_manipulated_scoring(tmp_path):
    """뒤집기 글이 없는 뉴스를 '전원 실패'로 세어 틀린 판단으로 잡으면 안 된다."""
    import yaml

    from echoguard.mock import make_world
    from echoguard.pipeline import run

    cfg = yaml.safe_load((ROOT / "config" / "experiment.yaml").read_text(encoding="utf-8"))
    items, written, clients = make_world(seed=cfg["seed"])
    full = run(items, written, clients, cfg, tmp_path / "full.jsonl")
    drop = {it.item_id for it in items[:30]}
    fewer = {k: v for k, v in written.items() if not (k[0] in drop and k[1] == "fact_flip")}
    part = run(items, fewer, clients, cfg, tmp_path / "part.jsonl")
    assert part["H5_fake_corroboration_only"]["n_items"] < full["H5_fake_corroboration_only"]["n_items"]
    pooled = "H4_guard_eval_with_manipulated_inputs"
    assert part[pooled]["G1_agreement"]["n_wrong"] <= full[pooled]["G1_agreement"]["n_wrong"]


def test_perturbations_that_were_not_sent_are_not_scored(tmp_path):
    """문체 변형을 만들지 않은 실행에서 '답이 전부 바뀌었다'고 보고하면 안 된다."""
    import yaml

    from echoguard.mock import make_world
    from echoguard.pipeline import run

    cfg = yaml.safe_load((ROOT / "config" / "experiment.yaml").read_text(encoding="utf-8"))
    items, written, clients = make_world(seed=cfg["seed"], n_items=20)
    only_flips = {k: v for k, v in written.items() if k[1] == "fact_flip"}
    report = run(items, only_flips, clients, cfg, tmp_path / "r.jsonl")
    assert isinstance(report["H3_co_flip"]["paraphrase"], str)
    assert isinstance(report["H3_co_flip"]["source_swap"], dict)
    assert isinstance(report["H4_guard_eval_original"]["G3_probe"], str)


def test_sending_only_some_kinds_still_analyzes(tmp_path):
    cfg = yaml.safe_load((ROOT / "config" / "experiment.yaml").read_text(encoding="utf-8"))
    items, written, clients = make_world(seed=2, n_items=40)
    r = pipeline.run(items, written, clients, cfg, tmp_path / "runs.jsonl", kinds=["original", "raw_table"])
    assert r["raw_table"]["n_items"] == 40 and r["injection"] == "이 변형을 보내지 않음"
    assert set(r["raw_table"]["panel_value"]["accuracy_by_model"]) == {c.name for c in clients}
