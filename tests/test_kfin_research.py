"""연구 반영분 점검: 모델 쌍 비교, 라쉬 모형, 검토자 d′, 기여 점수 조작 방지, 채점자 계열 경고."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kfin_eval import models, probe, score, stats  # noqa: E402


class Research(unittest.TestCase):
    def test_paired_beats_overlap(self):
        # 두 모델이 같은 문항을 풀어 점수가 함께 움직이면, 따로 낸 구간은 겹쳐도 차이는 0에서 떨어진다
        rows = []
        for i in range(60):
            hard = i % 3 == 0
            rows.append({"model": "A", "item_id": f"q{i}", "score": 0.0 if hard and i % 2 else 1.0})
            rows.append({"model": "B", "item_id": f"q{i}", "score": 0.0 if hard else 1.0})
        d = stats.paired_diff(rows, "A", "B", {})
        self.assertGreater(d["diff"], 0)
        self.assertGreater(d["lo"], 0)
        same = [dict(r, model="C") for r in rows if r["model"] == "A"] + [r for r in rows if r["model"] == "A"]
        self.assertEqual(stats.paired_diff(same, "C", "A", {})["p"], 1.0)

    def test_holm(self):
        self.assertEqual(stats.holm([0.01, 0.04, 0.03]), [0.03, 0.06, 0.06])

    def test_rasch_orders_models_and_items(self):
        rows = []
        skill = {"weak": 1, "mid": 2, "strong": 3}
        for i in range(30):
            level = i % 4            # 0~3: 그 단 이하 실력이면 틀린다
            for m, s in skill.items():
                rows.append({"model": m, "item_id": f"L{level}-{i}", "score": 1.0 if s > level else 0.0})
        res = stats.rasch(rows)
        th = res["theta"]
        self.assertGreater(th["strong"], th["mid"])
        self.assertGreater(th["mid"], th["weak"])
        b1 = [v for k, v in res["b"].items() if k.startswith("L1")]
        b2 = [v for k, v in res["b"].items() if k.startswith("L2")]
        self.assertLess(max(b1), min(b2))
        self.assertTrue(all(k.startswith("L0") for k in res["all_right"]))

    def test_sdt_catches_reject_everything(self):
        careful = {"reviewer": "careful", "batch": "c1", "n_wrong": 6, "caught": 6, "missed": 0, "n_right": 14, "false_reject": 0}
        nayer = {"reviewer": "nayer", "batch": "n1", "n_wrong": 6, "caught": 6, "missed": 0, "n_right": 14, "false_reject": 14}
        self.assertGreater(probe.sdt(careful)["dprime"], 2)
        self.assertLess(abs(probe.sdt(nayer)["dprime"]), 0.5)   # 찍기와 같다(보정 때문에 정확히 0은 아니다)
        self.assertLess(probe.sdt(nayer)["c"], 0)                 # '틀림' 남발
        self.assertEqual(probe.untrusted([careful, nayer]), {"nayer"})   # 포착률 100%여도 미달
        # 전부 '틀림'이라고 적으면 검토 점수 0, 꼼꼼하면 양수
        self.assertEqual(score.review_points(nayer), 0)
        self.assertEqual(score.review_points(careful), 30)

    def test_cluster_adjust(self):
        rows = [{"item_id": f"x{i}", "points": 100.0, "cluster": ("gen-a", "calc")} for i in range(4)]
        rows.append({"item_id": "y", "points": 50.0, "cluster": ("gen-a", "other")})
        out = {r["item_id"]: r for r in score.adjust(rows)}
        self.assertEqual(sum(out[f"x{i}"]["points"] for i in range(4)), 200.0)   # 4개 × 100 → 100 × √4
        self.assertEqual(out["y"]["points"], 50.0)
        self.assertEqual(out["x0"]["raw_points"], 100.0)

    def test_judge_family(self):
        self.assertEqual(models.family("eg:claude-haiku"), "claude")
        self.assertEqual(models.family("gpt-luna"), "gpt")
        self.assertEqual(models.judge_conflicts("claude-opus-5-5", ["eg:claude-haiku", "eg:gpt-luna"]), ["eg:claude-haiku"])
        self.assertEqual(models.judge_conflicts(None, ["claude-x"]), [])


if __name__ == "__main__":
    unittest.main()
