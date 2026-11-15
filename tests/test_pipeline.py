"""모의 세계로 전체 흐름이 끝까지 도는지, 심어 둔 성질을 찾아내는지 확인한다."""

from pathlib import Path

import numpy as np
import pytest
import yaml

from echoguard import guard, pipeline, store
from echoguard.dataset import assign_split, load_labels
from echoguard.mock import make_world
from echoguard.perturb import UNVERIFIED_TAG, VERIFIED_TAG, build_inputs

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
    assert pooled["G4_corroboration"]["recall"] > pooled["G2_agreement_source_tag"]["recall"]
    assert pooled["G4_corroboration"]["recall"] > pooled["G1_agreement"]["recall"]
