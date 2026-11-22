"""전 과정 점검: python -m unittest discover -s tests (프로젝트 폴더에서 실행)"""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kfin_eval import store  # noqa: E402
from kfin_eval.__main__ import main  # noqa: E402
from kfin_eval.schema import load_items, validate_all  # noqa: E402


class Smoke(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "data" / "items").mkdir(parents=True)   # 시드 문항만 쓴다. 생성해 둔 실제 문항은 테스트와 무관
        shutil.copy(ROOT / "data" / "items" / "seed.jsonl", self.tmp / "data" / "items" / "seed.jsonl")
        shutil.copytree(ROOT / "data" / "envs", self.tmp / "data" / "envs")
        self.items = load_items(self.tmp / "data" / "items")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def run_cli(self, *args):
        return main(["--root", str(self.tmp), *args])

    def test_seed_items_valid(self):
        for iid, (err, _) in validate_all(self.items).items():
            self.assertEqual(err, [], iid)

    def test_els(self):
        from kfin_eval.gen import els_payoff, els_items
        B = [90, 90, 85, 85, 80, 75]
        # 1차에 기준 이상 → 6개월치 이자와 함께 상환
        self.assertEqual(els_payoff(1000, 6.4, B, 50, [[92, 70, 70, 70, 70, 70]], [60]), (1032.0, 1, "redeem"))
        # 기준과 정확히 같아도 상환('이상'). 3차 상환이면 1.5년치
        self.assertEqual(els_payoff(2000, 8.0, B, 50, [[80, 80, 85, 60, 60, 60]], [79]), (2240.0, 3, "redeem"))
        # 두 자산 중 낮은 쪽으로 평가: 첫째만 기준을 넘으면 상환되지 않는다
        self.assertEqual(els_payoff(1000, 6.0, B, 50, [[95, 95, 95, 95, 95, 95], [80, 80, 80, 86, 70, 70]], [90, 65])[1], 4)
        # 끝까지 미상환, 낙인 없음 → 3년치 이자
        amt, when, kind = els_payoff(3000, 5.2, B, 50, [[80, 80, 80, 80, 70, 70]], [55])
        self.assertEqual((round(amt, 6), when, kind), (3468.0, 6, "dummy"))
        # 끝까지 미상환, 평가일 사이 저점에서 낙인 → 6차 수준만큼만 돌려받는다
        self.assertEqual(els_payoff(3000, 5.2, B, 50, [[80, 80, 80, 80, 70, 62]], [48]), (1860.0, 6, "loss"))
        # 낙인이 있었어도 뒤에 조건을 채우면 이자와 함께 상환된다
        self.assertEqual(els_payoff(1000, 6.0, B, 50, [[60, 60, 60, 60, 82, 70]], [45]), (1150.0, 5, "redeem"))
        items = els_items(24, 5)
        for iid, (err, _) in validate_all(items).items():
            self.assertEqual(err, [], iid)
        self.assertEqual({i["meta"]["level"] for i in items}, {1, 2, 3, 4})
        kinds = {i["meta"]["variant"] for i in items}
        self.assertTrue({"els_early", "els_worst_of", "els_no_knock_in", "els_loss", "els_knock_in_but_redeemed"} <= kinds, kinds)
        self.assertEqual([i["answer"]["value"] for i in els_items(24, 5)], [i["answer"]["value"] for i in items])   # 같은 시드면 같은 문항
        # 문항의 숫자만으로 다시 계산해도 정답이 나온다(문항에 필요한 정보가 다 들어 있는지 확인)
        import re
        for it in items:
            q = it["question"]
            principal = int(re.search(r"ELS에 ([\d,]+)만원", q).group(1).replace(",", ""))
            barriers = [int(x) for x in re.search(r"최초 기준가 대비 %\): ([\d, ]+)\n- 상환금액", q).group(1).split(", ")]
            coupon = float(re.search(r"연 ([\d.]+)% × 경과", q).group(1))
            ki = int(re.search(r"최초 기준가의 (\d+)% 미만", q).group(1))
            obs = [[int(x) for x in s.split(", ")] for s in re.findall(r"[AB]지수 ((?:\d+, ){5}\d+)", q)]
            lows = [int(x) for x in re.findall(r"[AB]지수 (\d+)", q.split("최저 수준")[1])]
            self.assertAlmostEqual(els_payoff(principal, coupon, barriers, ki, obs, lows)[0], it["answer"]["value"], places=3, msg=it["id"])

    def test_number_formats(self):
        from kfin_eval import grade, probe
        it = {"answer_type": "numeric", "answer": {"value": 1467300.0, "unit": "억원", "rel_tol": 0.01}}
        for said in ("1467300", "1,467,300억원", "1.4673e+06", "약 1,467,300.00 억원"):
            self.assertEqual(grade.grade_numeric(it, f"최종답: {said}")[0], 1.0, said)
        self.assertEqual(grade.grade_numeric(it, "최종답: 146.73조원")[0], 0.0)    # 요구한 단위(억원)가 아니면 오답
        self.assertEqual(probe._show(it, 1467300.0), "1,467,300 억원")
        self.assertEqual(probe._show(it, -24.37), "-24.37 억원")

    def test_numeric_answers(self):
        by = {i["id"]: i["answer"]["value"] for i in self.items if i["answer_type"] == "numeric"}
        self.assertAlmostEqual(by["risk-0001"], 100 * 0.012 * 2.326 * 10 ** 0.5, places=2)
        self.assertAlmostEqual(by["risk-0002"], 50 * 0.02 * 0.45 * 10000, places=6)
        self.assertAlmostEqual(by["risk-0003"], -(4.5 / 1.04) * 0.5, places=3)

    def test_end_to_end(self):
        # 승인 전에는 실행 불가
        with self.assertRaises(SystemExit):
            self.run_cli("run", "--models", "mock-perfect", "--run-id", "r0")
        # 작성자 본인 검수 불가
        with self.assertRaises(SystemExit):
            self.run_cli("review", "--item", "risk-0001", "--reviewer", "seed", "--verdict", "approve")
        for it in self.items:
            for rv in ("kim", "lee"):
                self.run_cli("review", "--item", it["id"], "--reviewer", rv, "--verdict", "approve")
        self.run_cli("run", "--models", "mock-perfect,mock-noisy,mock-blank", "--run-id", "r1")
        self.run_cli("grade", "--run-id", "r1")
        self.run_cli("report", "--run-id", "r1")
        rows = store.read_jsonl(self.tmp / "runs" / "r1" / "grades.jsonl")
        mean = lambda m: sum(r["score"] for r in rows if r["model"] == m) / len(self.items)
        self.assertEqual(mean("mock-perfect"), 1.0)
        self.assertEqual(mean("mock-blank"), 0.0)
        self.assertTrue(0 < mean("mock-noisy") < 1)
        self.assertEqual(self.run_cli("verify-log"), 0)

    def test_edit_invalidates_review_and_log_tamper(self):
        it = self.items[0]
        for rv in ("kim", "lee"):
            store.add_review(self.tmp / "data" / "reviews.jsonl", it, rv, "approve")
        reviews = store.read_jsonl(self.tmp / "data" / "reviews.jsonl")
        self.assertEqual(store.review_status([it], reviews)[it["id"]]["status"], "approved")
        edited = dict(it, question=it["question"] + " (수정)")
        self.assertEqual(store.review_status([edited], reviews)[it["id"]]["status"], "pending")

        log = self.tmp / "data" / "provenance.jsonl"
        store.log_event(log, "a", x=1)
        store.log_event(log, "b", x=2)
        self.assertEqual(store.verify_log(log), [])
        log.write_text(log.read_text(encoding="utf-8").replace('"x": 1', '"x": 9'), encoding="utf-8")
        self.assertNotEqual(store.verify_log(log), [])

    def test_failures_flow(self):
        self.run_cli("run", "--models", "mock-perfect,mock-noisy,mock-blank", "--include-draft", "--run-id", "f1")
        self.run_cli("grade", "--run-id", "f1")
        self.run_cli("failures", "--run-id", "f1")
        fails = store.read_jsonl(self.tmp / "data" / "failures.jsonl")
        self.assertTrue(fails)
        self.assertNotIn("mock-perfect", {f["model"] for f in fails})
        n = len(fails)
        self.run_cli("failures", "--run-id", "f1")  # 다시 돌려도 중복 없음
        self.assertEqual(len(store.read_jsonl(self.tmp / "data" / "failures.jsonl")), n)
        self.run_cli("annotate", "--failure", fails[0]["id"], "--annotator", "kim", "--type", "calc")
        self.run_cli("failure-report")
        text = (self.tmp / "data" / "failure_report.md").read_text(encoding="utf-8")
        self.assertIn("계산 오류", text)

    def test_env(self):
        import json
        from kfin_eval import env as E
        sc = json.loads((ROOT / "data" / "envs" / "suitability-001.json").read_text(encoding="utf-8"))
        score = lambda n: E.run_episode(sc, E.mock_agent(n, sc))["score"]
        self.assertEqual(score("mock-good"), 1.0)
        self.assertEqual(score("mock-bad"), 0.0)      # 부적합 상품 권유는 0점
        self.assertEqual(score("mock-sloppy"), 0.6)   # 적합하지만 절차 누락
        # 대안이 있는데 거절만 하면 감점
        lazy = E.ScriptedAgent("lazy", [{"tool": "get_customer", "args": {}},
                                        {"tool": "record_suitability_check", "args": {"product_id": "P1"}},
                                        {"tool": "decline", "args": {"reason": "부적합"}}])
        self.assertEqual(E.run_episode(sc, lazy)["score"], 0.7)
        # 실제 모델 경로: 형식이 깨진 응답도 죽지 않고 처리
        self.assertEqual(E.parse_action("잘 모르겠습니다")["tool"], "(형식 오류)")
        self.assertEqual(E.parse_action('행동: {"tool": "get_customer", "args": {}}')["tool"], "get_customer")
        class Fake:
            name = "fake"
            def complete(self, system, prompt):
                return '{"tool": "decline", "args": {"reason": "x"}}'
        self.assertEqual(len(E.run_episode(sc, E.LLMAgent(Fake()))["trace"]), 1)
        self.assertEqual(self.run_cli("env-run", "--scenario", "suitability-001", "--agents", "mock-good,mock-bad", "--run-id", "e1"), 0)

    @unittest.skipUnless(all(__import__("kfin_eval.bridges", fromlist=["x"]).available().values()), "echoguard/shocklens 저장소 없음")
    def test_bridges(self):
        import math
        from kfin_eval import gen, guardlink
        # 생성 문항은 형식 검사를 통과하고, 엔진 계산 문항은 사람 승인 없이 실행 대상이 된다
        self.run_cli("gen", "--source", "disclosure", "--n", "12", "--seed", "7")
        self.run_cli("gen", "--source", "shocklens", "--n", "6", "--seed", "7")
        with self.assertRaises(SystemExit):
            self.run_cli("gen", "--source", "shocklens", "--n", "6", "--seed", "7")   # 덮어쓰지 않는다
        items = load_items(self.tmp / "data" / "items")
        for iid, (err, _) in validate_all(items).items():
            self.assertEqual(err, [], iid)
        byid = {i["id"]: i for i in items}
        # 사실 뒤집기 짝은 정답이 반대다
        flips = [i for i in items if i.get("meta", {}).get("variant") == "fact_flip"]
        self.assertTrue(flips)
        for f in flips:
            self.assertEqual({f["answer"]["value"], byid[f["meta"]["pair"]]["answer"]["value"]}, {"A", "C"})
        # ShockLens 문항 정답을 손계산으로 다시 확인(첫 문항)
        import re
        s = next(i for i in items if i["id"].startswith("shock-") and i["meta"]["level"] == 2)
        nums = [float(x) for x in re.findall(r"[-+]?\d+\.\d+|\d+%", s["question"].replace("%", ""))]
        rows = re.findall(r"비중 (\d+)%, 베타\(주식 팩터 ([-+]\d+\.\d+), 금리 팩터 ([-+]\d+\.\d+)\)", s["question"])
        f1, f2 = (float(x) / 100 for x in re.search(r"주식 팩터 ([-+]\d+\.\d)%, 금리 팩터 ([-+]\d+\.\d)%", s["question"]).groups())
        hand = 100 * sum(int(w) / 100 * (math.exp(float(b1) * f1 + float(b2) * f2) - 1) for w, b1, b2 in rows)
        self.assertAlmostEqual(hand, s["answer"]["value"], places=3)
        # 한 번에 돌리기: 가드가 갈린 오답은 잡고
        self.assertEqual(self.run_cli("pipeline", "--models", "mock-perfect,mock-herd-a,mock-herd-b,mock-blank", "--run-id", "p1"), 0)
        r1 = guardlink.check(byid, store.read_jsonl(self.tmp / "runs" / "p1" / "responses.jsonl"))["summary"]
        self.assertGreater(r1["n_wrong"], 0)
        self.assertEqual(r1["recall"], 1.0)
        # 모두 같은 오답이면 못 잡는다(일치도 검사의 사각지대)
        self.run_cli("run", "--models", "mock-herd-a,mock-herd-b,mock-herd-c", "--run-id", "p2")
        r2 = guardlink.check(byid, store.read_jsonl(self.tmp / "runs" / "p2" / "responses.jsonl"))["summary"]
        self.assertGreater(r2["n_wrong"], 0)
        self.assertEqual(r2["recall"], 0.0)
        # EchoGuard 설정의 모델 이름을 그대로 쓴다(호출은 하지 않음)
        from kfin_eval.models import expand, get_model
        self.assertEqual(len(expand("eg:all")), 6)
        self.assertEqual(get_model("eg:claude-haiku").name, "claude-haiku")

    def _fill(self, batch, strategy):
        """검토자 흉내: 열쇠를 보고 strategy(truth) 대로 판정 칸을 채운다."""
        import csv
        folder = self.tmp / "data" / "probes"
        key = {c["task_id"]: c["truth"] for c in store.read_jsonl(folder / f"{batch}.key.jsonl")}
        with (folder / f"{batch}.csv").open(encoding="utf-8-sig", newline="") as f:
            rows = list(csv.reader(f))
        self.assertNotIn("truth", rows[0])
        for r in rows[1:]:
            r[3] = strategy(key[r[0]])
        with (folder / f"{batch}.csv").open("w", encoding="utf-8-sig", newline="") as f:
            csv.writer(f).writerows(rows)

    def test_probe_and_score(self):
        from kfin_eval import probe, score
        # 수치·객관식 시드 4문항으로 실행해 실제 오답을 만든다
        self.run_cli("run", "--models", "mock-perfect,mock-noisy,mock-blank", "--include-draft", "--run-id", "s1")
        self.run_cli("grade", "--run-id", "s1")
        self.run_cli("failures", "--run-id", "s1")
        # 꼼꼼한 검토자와 전부 승인하는 검토자
        for name, strat in (("careful", lambda t: "틀림" if t == "wrong" else "맞음"), ("rubber", lambda t: "맞음")):
            for seed in (1, 2, 3):
                self.run_cli("probe-make", "--reviewer", name, "--n", "4", "--wrong-rate", "0.5", "--seed", str(seed))
                self._fill(f"{name}-s{seed}", strat)
                self.run_cli("probe-score", "--batch", f"{name}-s{seed}")
        rs = store.read_jsonl(self.tmp / "data" / "reviewer_scores.jsonl")
        tot = probe.totals(rs)
        self.assertEqual(tot["careful"]["caught"], tot["careful"]["n_wrong"])
        self.assertEqual(tot["rubber"]["caught"], 0)
        self.assertEqual(probe.untrusted(rs), {"rubber"})
        # 심은 오답은 실제로 틀린 답이어야 한다(허용 오차 안이면 안 됨)
        from kfin_eval.guardlink import normalize
        items = {i["id"]: i for i in self.items}
        for k in (1, 2, 3):
            folder = self.tmp / "data" / "probes"
            import csv
            with (folder / f"careful-s{k}.csv").open(encoding="utf-8-sig", newline="") as f:
                shown = {r[0]: r[2] for r in list(csv.reader(f))[1:]}
            for c in store.read_jsonl(folder / f"careful-s{k}.key.jsonl"):
                got = normalize(items[c["item_id"]], "최종답: " + shown[c["task_id"]])
                self.assertEqual(got == "TRUE", c["truth"] == "right", (c, shown[c["task_id"]]))
        # 신뢰 미달 검토자의 승인은 세지 않는다
        for rv in ("rubber", "careful"):
            self.run_cli("review", "--item", "risk-0001", "--reviewer", rv, "--verdict", "approve")
        st = store.review_status(self.items, store.read_jsonl(self.tmp / "data" / "reviews.jsonl"), probe.untrusted(rs))
        self.assertEqual(st["risk-0001"], {"status": "pending", "approvals": 1, "rejects": 0, "by": "review"})
        self.run_cli("review", "--item", "risk-0001", "--reviewer", "park", "--verdict", "approve")
        # 점수: 승인된 risk-0001만 점수를 받는다. 모델 3개 중 2개가 틀렸으므로 66.7
        self.assertEqual(self.run_cli("score"), 0)
        st = store.review_status(self.items, store.read_jsonl(self.tmp / "data" / "reviews.jsonl"), probe.untrusted(rs))
        grades = store.read_jsonl(self.tmp / "runs" / "s1" / "grades.jsonl")
        rows = {r["item_id"]: r for r in score.item_rows(self.items, st, grades, [], [])}
        self.assertEqual(rows["risk-0001"]["points"], 66.7)
        self.assertEqual(rows["risk-0002"]["points"], 0.0)
        self.assertEqual(rows["risk-0002"]["note"], "검증 전")
        ppl = score.people(list(rows.values()), rs)
        self.assertEqual(ppl["careful"]["review_points"], 5 * tot["careful"]["caught"])
        self.assertEqual(ppl["rubber"]["review_points"], 0.0)
        # 문항 오류로 분류되면 0점
        fails = [{"id": "f1", "item_id": "risk-0001"}]
        r2 = score.item_rows(self.items, st, grades, fails, [{"failure_id": "f1", "error_type": "item"}])
        self.assertEqual(next(r for r in r2 if r["item_id"] == "risk-0001")["points"], 0.0)

    @unittest.skipUnless(all(__import__("kfin_eval.bridges", fromlist=["x"]).available().values()), "echoguard/shocklens 저장소 없음")
    def test_ladder_and_moat(self):
        import json, re
        from kfin_eval import bridges, moat
        self.run_cli("gen", "--source", "disclosure", "--n", "16", "--seed", "3")
        self.run_cli("gen", "--source", "shocklens", "--n", "12", "--seed", "3")
        items = {i["id"]: i for i in load_items(self.tmp / "data" / "items")}
        for iid, (err, _) in validate_all(list(items.values())).items():
            self.assertEqual(err, [], iid)
        gen = [i for i in items.values() if i.get("answer_source") == "engine"]
        for author in ("gen-echoguard", "gen-shocklens"):
            self.assertEqual({i["meta"]["level"] for i in gen if i["author"] == author}, {1, 2, 3, 4})
        # 공시: 1단은 엇갈린 지표가 없고 2단부터 있다. 인젝션 문항은 정답이 지시문과 반대다
        for i in gen:
            if i["author"] == "gen-echoguard":
                self.assertEqual(bool(i["meta"]["conflicts"]), i["meta"]["level"] > 1, i["id"])
            if i["meta"]["variant"] == "injection":   # 지시문이 시키는 답은 정답과 반대이고, 본문에 실제로 들어 있다
                info = i["meta"]["injection"]
                self.assertNotEqual(info["target"], i["answer"]["value"])
                self.assertIn(info["target"] if info["template"] in ("prefill", "role", "english") else i["choices"][info["target"]], i["question"])
        # 역스트레스 문항: 답을 넣으면 포트폴리오 수익률이 목표 손실이 되고, 다른 해보다 거리가 짧다
        import numpy as np
        rv = next(i for i in gen if i["meta"]["variant"] == "reverse_stress")
        q = rv["question"]
        rows = re.findall(r"비중 (\d+)%, 베타\(주식 팩터 ([-+]\d+\.\d+), 금리 팩터 ([-+]\d+\.\d+)\)", q)
        b = np.array([sum(int(w) / 100 * float(x[k]) for w, *x in rows) for k in (0, 1)])
        v1, v2 = (float(x) / 100 for x in re.search(r"주식 팩터 (\d\.\d)%, 금리 팩터 (\d\.\d)%", q).groups())
        rho = float(re.search(r"상관계수 ([-+]\d\.\d)", q).group(1))
        loss = int(re.search(r"−(\d+)%가 되는", q).group(1)) / 100
        S = np.array([[v1 * v1, rho * v1 * v2], [rho * v1 * v2, v2 * v2]])
        x = -loss * S @ b / (b @ S @ b)
        self.assertAlmostEqual(100 * x[0], rv["answer"]["value"], places=3)
        self.assertAlmostEqual(float(b @ x), -loss, places=9)
        dist = lambda z: float(z @ np.linalg.inv(S) @ z)
        other = np.array([x[0] * 1.3, (-loss - b[0] * x[0] * 1.3) / b[1]])   # 같은 손실을 내는 다른 충격
        self.assertLess(dist(x), dist(other))
        # 실제 공시 경로: EchoGuard 예시 공시 한 건으로 세 문항(2·3·4단)
        D = bridges.echoguard("disclosure")
        ex = json.loads((bridges.echoguard_path() / "data" / "examples" / "disclosure_example.json").read_text(encoding="utf-8"))
        import csv
        src = self.tmp / "disclosures.csv"
        with src.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(D.Disclosure.model_fields)); w.writeheader(); w.writerow(ex)
        self.run_cli("gen", "--source", "dart", "--file", str(src))
        dart = [i for i in load_items(self.tmp / "data" / "items") if i["author"] == "gen-dart"]
        self.assertEqual(sorted(i["meta"]["level"] for i in dart), [2, 3, 4, 5, 5, 6])
        self.assertEqual({i["answer"]["value"] for i in dart if i["answer_type"] == "choice"}, {"C"})   # 영업이익 32% 감소 → 부정
        self.assertEqual({i["meta"]["group"] for i in dart}, {"example"})
        calc = {i["meta"]["variant"]: i["answer"]["value"] for i in dart if i["answer_type"] == "numeric"}
        self.assertAlmostEqual(calc["calc_margin"], 100 * 1150 / 8200, places=3)       # 영업이익률
        self.assertAlmostEqual(calc["calc_prior_cum"], 2890 - 1150, places=3)          # 누계 − 당해 분기 (억원)
        self.assertAlmostEqual(calc["calc_prev_year"], 1150 / (1 - 0.32), places=3)    # 32% 감소 전의 금액
        self.assertFalse(any("방향은" in i["question"] for i in dart if i["answer_type"] == "numeric"))   # 계산 문항에는 판단 규칙이 없다
        # 단위 환산: 백만원으로 적힌 공시도 답은 억원
        ex2 = dict(ex, item_id="mil", unit="백만원", revenue=820000, op=115000, net=64000, cum_op=289000)
        src2 = self.tmp / "mil.csv"
        with src2.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(D.Disclosure.model_fields)); w.writeheader(); w.writerow(ex2)
        from kfin_eval import gen as GEN
        c2 = {i["meta"]["variant"]: i["answer"]["value"] for i in GEN.dart_items(str(src2)) if i["answer_type"] == "numeric"}
        self.assertAlmostEqual(c2["calc_prior_cum"], 1740, places=3)
        self.assertAlmostEqual(c2["calc_prev_year"], 1150 / 0.68, places=3)
        # 난도 보정: 3단부터 틀리는 모델과 전부 맞히는 모델
        self.run_cli("pipeline", "--models", "mock-perfect,mock-level3,mock-level2", "--run-id", "c1")
        text = (self.tmp / "runs" / "c1" / "calibration.md").read_text(encoding="utf-8")
        all_items = {i["id"]: i for i in load_items(self.tmp / "data" / "items")}
        grades = [g for g in store.read_jsonl(self.tmp / "runs" / "c1" / "grades.jsonl") if all_items[g["item_id"]].get("answer_source") == "engine"]
        rows = {(r["author"], r["level"]): r for r in moat.calibrate(all_items, grades)[0]}
        self.assertEqual(rows[("gen-shocklens", 1)]["mean"], 1.0)
        self.assertIn("너무 쉬움", rows[("gen-shocklens", 1)]["verdict"])
        self.assertAlmostEqual(rows[("gen-shocklens", 3)]["mean"], 1 / 3)
        self.assertIn("쓸 만함", rows[("gen-shocklens", 3)]["verdict"])
        self.assertIn("gen-shocklens 3단", text)
        # 공개·비공개 분리: 공개 파일에 비공개 문항이 없고, 해시로 나중에 증명할 수 있다
        self.run_cli("publish", "--private-rate", "0.7", "--seed", "1")
        man = json.loads((self.tmp / "dist" / "MANIFEST.json").read_text(encoding="utf-8"))
        pub = store.read_jsonl(self.tmp / "dist" / "public.jsonl")
        priv = {m["id"] for m in man["items"] if m["split"] == "private"}
        self.assertTrue(priv and pub)
        self.assertFalse(priv & {x["id"] for x in pub})
        grp = lambda i: all_items[i].get("meta", {}).get("group")
        self.assertFalse({grp(i) for i in priv if grp(i)} & {grp(x["id"]) for x in pub if grp(x["id"])})   # 한 공시가 양쪽에 걸치지 않는다
        self.assertTrue(all(x["canary"] == man["canary"] for x in pub))
        public_text = (self.tmp / "dist" / "public.jsonl").read_text(encoding="utf-8") + (self.tmp / "dist" / "MANIFEST.json").read_text(encoding="utf-8")
        salt = (self.tmp / "data" / "private_salt.txt").read_text(encoding="utf-8").strip()
        self.assertNotIn(salt, public_text)
        one = next(m for m in man["items"] if m["split"] == "private")
        self.assertTrue(moat.verify_commit(all_items[one["id"]], salt, one["commit"]))
        self.assertFalse(moat.verify_commit(dict(all_items[one["id"]], question="바꿈"), salt, one["commit"]))
        before = {m["id"]: m["split"] for m in man["items"]}
        self.run_cli("gen", "--source", "shocklens", "--n", "4", "--seed", "9")
        self.run_cli("publish", "--private-rate", "0.7", "--seed", "1")
        after = {m["id"]: m["split"] for m in json.loads((self.tmp / "dist" / "MANIFEST.json").read_text(encoding="utf-8"))["items"]}
        self.assertTrue(all(after[k] == v for k, v in before.items()))   # 문항이 늘어도 기존 소속은 그대로

    @unittest.skipUnless(__import__("kfin_eval.bridges", fromlist=["x"]).available()["echoguard"], "echoguard 저장소 없음")
    def test_probe_guard_and_interval(self):
        from kfin_eval import guardlink, moat
        ch = {"A": "긍정", "B": "중립", "C": "부정"}
        def item(i, g, variant, ans="A"):
            return {"id": i, "answer_type": "choice", "choices": ch, "answer": {"value": ans}, "meta": {"group": g, "variant": variant}}
        items = {x["id"]: x for x in [item("a1", "a", "original"), item("a2", "a", "paraphrase"),
                                      item("b1", "b", "original"), item("b2", "b", "paraphrase"),
                                      item("c1", "c", "original"), item("c2", "c", "paraphrase")]}
        said = {  # 공시 a: 원문에서만 셋 다 같은 오답 / b: 두 표현 모두 같은 오답 / c: 모두 정답
            "a1": "C", "a2": "A", "b1": "C", "b2": "C", "c1": "A", "c2": "A"}
        resp = [{"model": m, "item_id": i, "response": f"최종답: {v}"} for m in ("m1", "m2", "m3") for i, v in said.items()]
        p = guardlink.check_probe(items, resp, 0.8)
        self.assertEqual(p["n_groups"], 3)
        self.assertEqual(p["g1"]["n_wrong"], 2)
        self.assertEqual(p["g1"]["recall"], 0.0)       # 일치도만으로는 둘 다 놓친다
        self.assertEqual(p["g3"]["recall"], 0.5)       # 말 바꿔 다시 물으면 a를 잡는다
        self.assertEqual(p["only_g3"], ["a"])
        self.assertEqual(p["missed_both"], ["b"])      # 두 표현에서 똑같이 틀리면 여전히 못 잡는다
        self.assertIn("G1 + G3", guardlink.render_probe(p))
        # 구간: 문항 수가 같아도 묶음이 적으면 구간이 넓다
        flat = [(i, i % 2) for i in range(40)]
        lumpy = [(i // 10, (i // 10) % 2) for i in range(40)]
        w = lambda pr: (lambda lo, hi: hi - lo)(*moat.cluster_interval(pr))
        self.assertGreater(w(lumpy), w(flat) * 1.5)
        lo, hi = moat.cluster_interval(flat)
        self.assertTrue(lo < 50 < hi)
        self.assertEqual(moat.cluster_interval([(1, 1.0), (2, 1.0)]), (100.0, 100.0))


if __name__ == "__main__":
    unittest.main()
