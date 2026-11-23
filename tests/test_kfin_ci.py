"""CI 점검(kfin_eval/ci.py) 테스트. 실제 모델은 부르지 않는다."""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kfin_eval import bridges, ci  # noqa: E402
from kfin_eval.__main__ import main  # noqa: E402

IDS = ["a", "b", "c", "d", "e"]


class JudgeSmoke(unittest.TestCase):
    def test_tolerance_boundary(self):
        base = {"m": {"a": 0, "b": 1, "c": 1, "d": 1, "e": 1}}                 # 기준선 오답 1개
        three = {"m": {"a": 0, "b": 0, "c": 0, "d": 1, "e": 1}}                # 3개 = +2 → 허용
        four = {"m": {"a": 0, "b": 0, "c": 0, "d": 0, "e": 1}}                 # 4개 = +3 → 실패
        self.assertTrue(ci.judge_smoke(three, base, IDS, 2)["ok"])
        r = ci.judge_smoke(four, base, IDS, 2)
        self.assertFalse(r["ok"])
        self.assertEqual(r["rows"][0]["new_wrong"], ["b", "c", "d"])

    def test_fixed_items_reported(self):
        base = {"m": {"a": 0, "b": 0, "c": 1, "d": 1, "e": 1}}
        now = {"m": {i: 1 for i in IDS}}
        r = ci.judge_smoke(now, base, IDS, 2)
        self.assertTrue(r["ok"])
        self.assertEqual(r["rows"][0]["fixed"], ["a", "b"])

    def test_joint_failure_fails_even_within_tolerance(self):
        base = {"x": {i: 1 for i in IDS}, "y": {i: 1 for i in IDS}}
        now = {"x": {**{i: 1 for i in IDS}, "c": 0}, "y": {**{i: 1 for i in IDS}, "c": 0}}
        r = ci.judge_smoke(now, base, IDS, 2)
        self.assertEqual(r["joint"], ["c"])
        self.assertFalse(r["ok"])

    def test_model_without_baseline_is_not_failed(self):
        r = ci.judge_smoke({"new": {i: 0 for i in IDS}}, {}, IDS, 2)
        self.assertTrue(r["ok"])                     # 모델 하나면 '함께 틀림'도 정의하지 않는다
        self.assertIsNone(r["rows"][0]["base"])


class AnswerKey(unittest.TestCase):
    def test_rounding_ignores_float_noise_but_not_real_change(self):
        it = {"id": "q", "answer": {"value": 12.3456781, "unit": "억원", "rel_tol": 0.005}}
        noise = {"id": "q", "answer": {"value": 12.3456789, "unit": "억원", "rel_tol": 0.005}}
        real = {"id": "q", "answer": {"value": 12.40, "unit": "억원", "rel_tol": 0.005}}
        self.assertEqual(ci.answer_hash(it), ci.answer_hash(noise))
        self.assertNotEqual(ci.answer_hash(it), ci.answer_hash(real))
        self.assertEqual(ci._round_sig(0.000123456789), 0.00012346)

    def test_compare_key(self):
        old = {"g": {"a": "1", "b": "2", "c": "3"}, "gone": {"z": "9"}}
        new = {"g": {"a": "1", "b": "X", "d": "4"}}
        d = ci.compare_key(old, new)
        self.assertEqual(d, {"g": {"changed": ["b"], "missing": ["c"], "new": ["d"]}})   # 못 돈 생성기는 비교 안 함

    def test_committed_key_matches_current_generators(self):
        key, skipped = ci.build_key(ROOT)
        stored = json.loads((ROOT / "ci" / "answer_key.json").read_text(encoding="utf-8"))
        diff = ci.compare_key(stored, key)
        self.assertFalse(any(any(v.values()) for v in diff.values()), diff)
        if not bridges.available()["shocklens"]:
            self.assertIn("shocklens", " ".join(skipped))


class Cli(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        for sub in ("ci", "dist", "plugins"):
            shutil.copytree(ROOT / sub, self.tmp / sub)
        (self.tmp / "data" / "items").mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_ci_key_fails_on_tampered_key(self):
        path = self.tmp / "ci" / "answer_key.json"
        k = json.loads(path.read_text(encoding="utf-8"))
        first = sorted(k["els"])[0]
        k["els"][first] = "0" * 16
        path.write_text(json.dumps(k), encoding="utf-8")
        self.assertEqual(main(["--root", str(self.tmp), "ci-key"]), 1)

    def test_ci_smoke_mock(self):
        self.assertEqual(main(["--root", str(self.tmp), "ci-smoke", "--models", "mock-perfect", "--no-guard"]), 0)

    def test_ci_smoke_herd_fails(self):
        # 무리 모델 둘이 같은 오답을 낸다 → 함께 틀린 문항이 있으면 실패해야 한다
        self.assertEqual(main(["--root", str(self.tmp), "ci-smoke", "--models", "mock-herd,mock-herd-b", "--no-guard"]), 1)


if __name__ == "__main__":
    unittest.main()
