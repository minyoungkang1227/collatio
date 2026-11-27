"""BCBS 239 기준으로 붙인 점검: 원문 대조 기록, 수작업 수정 사유, 커버리지 보고서."""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from kfin_eval.__main__ import main  # noqa: E402
from kfin_eval.schema import load_items, validate_item  # noqa: E402


def _reg():
    return next(i for i in load_items(ROOT / "data" / "items") if i["id"] == "reg-0001")


class BCBS(unittest.TestCase):
    def test_verified_and_changes_format(self):
        it = _reg()
        self.assertEqual(validate_item(it)[0], [])
        bad = json.loads(json.dumps(it))
        bad["sources"][0]["verified"]["level"] = "maybe"
        bad["changes"] = [{"date": "2026-11-27", "by": "x"}]   # 사유 없음
        err = validate_item(bad)[0]
        self.assertTrue(any("verified" in e for e in err), err)
        self.assertTrue(any("changes[0]" in e for e in err), err)

    def test_regulation_warns_until_primary(self):
        it = _reg()
        self.assertTrue(any("2차 출처" in w for w in validate_item(it)[1]))
        it["sources"][0]["verified"]["level"] = "primary"
        self.assertFalse(any("2차 출처" in w for w in validate_item(it)[1]))
        del it["sources"][0]["verified"]
        self.assertTrue(any("원문 대조 기록" in w for w in validate_item(it)[1]))

    def test_coverage_report(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            (tmp / "data" / "items").mkdir(parents=True)
            (tmp / "config").mkdir()
            (tmp / "docs").mkdir()
            shutil.copy(ROOT / "data" / "items" / "seed.jsonl", tmp / "data" / "items" / "seed.jsonl")
            shutil.copy(ROOT / "config" / "coverage_plan.json", tmp / "config" / "coverage_plan.json")
            self.assertEqual(main(["--root", str(tmp), "coverage", "--extra"]), 0)
            text = (tmp / "docs" / "coverage.md").read_text(encoding="utf-8")
            self.assertIn("| risk | 1 | 2 | 0 |", text)
            self.assertIn("빈 칸", text)
            self.assertIn("disclosure 1단", text)   # 시드에 공시 문항이 없으니 빈 칸으로 잡혀야 한다
        finally:
            shutil.rmtree(tmp)


if __name__ == "__main__":
    unittest.main()


class DrillAndAudience(unittest.TestCase):
    """원칙 6(쪼개 보기)와 원칙 9(수신자별 보고서)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "data" / "items").mkdir(parents=True)
        shutil.copy(ROOT / "data" / "items" / "seed.jsonl", self.tmp / "data" / "items" / "seed.jsonl")
        self.cli = lambda *a: main(["--root", str(self.tmp), *a])
        self.cli("run", "--models", "mock-perfect,mock-noisy,mock-blank", "--include-draft", "--run-id", "d1")
        self.cli("grade", "--run-id", "d1")
        self.cli("failures", "--run-id", "d1")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_drill(self):
        from kfin_eval import store
        fails = store.read_jsonl(self.tmp / "data" / "failures.jsonl")
        self.cli("annotate", "--failure", fails[0]["id"], "--annotator", "kim", "--type", "calc")
        self.assertEqual(self.cli("drill", "--run-id", "d1"), 0)
        text = (self.tmp / "runs" / "d1" / "drill.md").read_text(encoding="utf-8")
        for h in ("## 분야별", "## 난도별", "## 답 형식별", "## 오류 유형별", "계산 오류", "미분류"):
            self.assertIn(h, text)
        self.assertIn("100.0 (3)*", text)        # mock-perfect의 risk 3문항: 표본 적음 표시
        with self.assertRaises(SystemExit):
            self.cli("drill", "--run-id", "d1", "--by", "color")

    def test_audience_reports(self):
        self.assertEqual(self.cli("report", "--run-id", "d1"), 0)
        cto = (self.tmp / "runs" / "d1" / "report_cto.md").read_text(encoding="utf-8")
        risk = (self.tmp / "runs" / "d1" / "report_risk.md").read_text(encoding="utf-8")
        self.assertIn("| 1 | mock-perfect |", cto)
        self.assertIn("피해야 할 칸", cto)
        self.assertIn("mock-blank", risk)
        self.assertIn("이 결과로 말할 수 없는 것", risk)
        self.assertIn("사람 검수자 0명", risk)
        self.assertNotIn("틀린 응답", cto)       # 모델 선택용에는 문항별 오답 목록을 넣지 않는다
