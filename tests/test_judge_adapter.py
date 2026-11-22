"""The jury's published checks (genesis-exe.com/fintech-checks.html) run through judge_adapter.py."""

import csv
import json
import os
import random
import shutil
import tempfile
import unittest

import judge_adapter as ja


def _act(name, **args):
    return {"name": name, "args": args}


class TestAdapterContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.dir = os.path.join(cls.tmp, "ep")
        ja.generate_episode(424242, {"preset": "interacting"}, cls.dir)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def test_files_written(self):
        for f in ("manifest.json", "policy.json", "ledger.csv", "invoices.jsonl", "payments.jsonl", "fx.csv",
                  "truth.json", "provenance.json"):
            self.assertTrue(os.path.exists(os.path.join(self.dir, f)), f)

    def test_generation_is_reproducible(self):
        d2 = os.path.join(self.tmp, "ep2")
        ja.generate_episode(424242, {"team_config": {"preset": "interacting"}, "mode": "closed"}, d2)
        for f in os.listdir(self.dir):
            with open(os.path.join(self.dir, f), "rb") as a, open(os.path.join(d2, f), "rb") as b:
                self.assertEqual(a.read(), b.read(), f)

    def test_name_args_actions_and_closed_mode(self):
        env = ja.make_env()
        obs, info = env.reset(1, {"mode": "closed", "episode_dir": self.dir})
        self.assertEqual(obs["remaining_steps"], 100)
        o, r, te, tr, _ = env.step(_act("list_records", table="ledger", cursor=None, limit=50))
        self.assertEqual(len(o["result"]["records"]), 50)
        o2, *_ = env.step(_act("list_records", table="ledger", cursor=o["result"]["next_cursor"], limit=50))
        o3, *_ = env.step(_act("list_records", table="ledger", cursor=o["result"]["next_cursor"], limit=50))
        self.assertEqual(o2["result"], o3["result"])                                     # cursor repeatability
        self.assertEqual(env.step(_act("calculator", expression="0.1+0.2"))[0]["result"]["value"], "0.3")
        self.assertEqual(env.step(_act("calculator", expression="open('/etc/passwd').read()"))[0]["error"]["code"], "calc_error")
        self.assertEqual(env.step(_act("get_record", table="ledger", id="NOPE"))[0]["error"]["code"], "not_found")
        self.assertEqual(env.step(_act("get_document", doc_id="NOPE"))[0]["error"]["code"], "not_found")
        self.assertEqual(env.step(_act("rm"))[0]["error"]["code"], "unknown_action")
        with open(os.path.join(self.dir, "truth.json")) as f:
            truth = json.load(f)
        fs = [{"type": i["type"], "affected_ids": i["affected_ids"], "claimed_amount_minor": i["expected_amount_minor"],
               "currency": i["currency"], "evidence_ids": i["evidence_sets"][0], "explanation": ""} for i in truth["issues"]]
        sub = {"episode_id": obs["episode_id"], "findings": fs}
        o, r, te, tr, info = env.step(_act("submit", findings=sub))
        self.assertTrue(te)
        self.assertEqual(r, 0.0)                                                         # closed mode
        self.assertEqual(env.last_grade["inspection_steps"], 8)
        res = ja.score_episode(self.dir, sub, 8)
        self.assertEqual((res["tp"], res["fp"], res["fn"]), (len(fs), 0, 0))
        self.assertAlmostEqual(res["return"], 1 - 0.002 * 8)

    def test_train_mode_returns_reward(self):
        env = ja.make_env()
        obs, _ = env.reset(3, {"mode": "train", "team_config": {"preset": "clean"}})
        o, r, te, tr, info = env.step(_act("submit", findings={"episode_id": obs["episode_id"], "findings": []}))
        self.assertEqual(r, 1.0)

    def test_budget_100_and_truncation(self):
        env = ja.make_env()
        env.reset(1, {"mode": "closed", "episode_dir": self.dir})
        for i in range(99):
            env.step(_act("calculator", expression="1+1"))
        o, r, te, tr, _ = env.step(_act("submit", findings={"findings": []}))
        self.assertTrue(te)
        self.assertEqual(env.last_grade["inspection_steps"], 99)
        env.reset(1, {"mode": "closed", "episode_dir": self.dir})
        for i in range(100):
            o, r, te, tr, _ = env.step(_act("calculator", expression="1+1"))
        self.assertTrue(tr)


class TestBlock3Fixture(unittest.TestCase):
    """Shared fixture of block 3: one error A, type T, record R1, 10000 KZT, evidence {D1, D2}, tau = 0."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.one = os.path.join(cls.tmp, "one")
        cls.empty = os.path.join(cls.tmp, "empty")
        os.makedirs(cls.one)
        os.makedirs(cls.empty)
        with open(os.path.join(cls.one, "truth.json"), "w") as f:
            json.dump({"episode_id": "fx-1", "issues": [{"issue_id": "A", "type": "duplicate_invoice",
                       "affected_ids": ["R1"], "expected_amount_minor": 10000, "currency": "KZT",
                       "evidence_sets": [["D1", "D2"]]}]}, f)
        with open(os.path.join(cls.empty, "truth.json"), "w") as f:
            json.dump({"episode_id": "fx-0", "issues": []}, f)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def F(self, **over):
        f = {"type": "duplicate_invoice", "affected_ids": ["R1"], "claimed_amount_minor": 10000, "currency": "KZT",
             "evidence_ids": ["D1", "D2"], "explanation": "x"}
        f.update(over)
        return f

    def test_published_examples(self):
        r = ja.score_episode(self.one, {"episode_id": "fx-1", "findings": [self.F()]}, 10)
        self.assertEqual(r["tp"], 1)
        self.assertAlmostEqual(r["return"], 0.98, places=9)
        r = ja.score_episode(self.one, {"episode_id": "fx-1", "findings": []}, 10)
        self.assertEqual(r["fn"], 1)
        self.assertEqual(r["return"], -1.0)
        r = ja.score_episode(self.empty, {"episode_id": "fx-0", "findings": []}, 10)
        self.assertEqual(r["f1"], 1.0)
        self.assertAlmostEqual(r["return"], 0.98, places=9)
        r = ja.score_episode(self.one, {"episode_id": "fx-1", "findings": [self.F(), self.F()]}, 10)
        self.assertEqual((r["tp"], r["fp"]), (1, 1))
        self.assertAlmostEqual(r["f1"], 2 / 3, places=9)
        self.assertAlmostEqual(r["return"], 47 / 150, places=9)
        spam = [self.F()] + [self.F(affected_ids=["R%d" % i]) for i in range(2, 21)]
        r = ja.score_episode(self.one, {"episode_id": "fx-1", "findings": spam}, 10)
        self.assertEqual((r["tp"], r["fp"]), (1, 19))
        self.assertAlmostEqual(r["return"], -0.8295, places=4)
        for steps, ret in ((0, 1.0), (50, 0.90), (100, 0.80)):
            r = ja.score_episode(self.one, {"episode_id": "fx-1", "findings": [self.F()]}, steps)
            self.assertAlmostEqual(r["return"], ret, places=9)

    def test_structural_limits(self):
        for sub in ([self.F()] * 31, [self.F(evidence_ids=["D1", "D2"] + ["X%d" % i for i in range(9)])],
                    [self.F(explanation="я" * 1001)], [self.F(claimed_amount_minor=True)],
                    [self.F(claimed_amount_minor="10000")], [self.F(claimed_amount_minor=10000.0)]):
            r = ja.score_episode(self.one, {"episode_id": "fx-1", "findings": sub}, 0)
            self.assertEqual(r["return"], -1.0)
            self.assertIsNone(r["f1"])
        r = ja.score_episode(self.one, {"episode_id": "fx-1", "findings": [self.F(explanation="я" * 1000)]}, 0)
        self.assertTrue(r["valid"])

    def test_matcher_conventions(self):
        def tp(**over):
            return ja.score_episode(self.one, {"episode_id": "fx-1", "findings": [self.F(**over)]}, 0)["tp"]
        self.assertEqual(tp(evidence_ids=["D2", "D1"]), 1)                 # sets
        self.assertEqual(tp(evidence_ids=["D1", "D2", "D3"]), 1)           # extra evidence (no public files here)
        self.assertEqual(tp(evidence_ids=["D1"]), 0)                       # incomplete evidence
        self.assertEqual(tp(currency="kzt"), 0)                            # currency case is not normalised
        self.assertEqual(tp(affected_ids=[" R1"]), 0)                      # no trimming
        self.assertEqual(tp(affected_ids=["r1"]), 0)                       # case-sensitive
        self.assertEqual(tp(claimed_amount_minor=10001), 0)                # tau = 0
        self.assertEqual(tp(type="period_cutoff"), 0)
        r = ja.score_episode(self.one, {"episode_id": "fx-1", "findings": [self.F(type="nonsense")]}, 0)
        self.assertEqual((r["valid"], r["fp"]), (True, 1))                 # wrong content = FP only

    def test_two_error_assignment(self):
        d = os.path.join(self.tmp, "two")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "truth.json"), "w") as f:
            json.dump({"issues": [
                {"issue_id": "A", "type": "fx_misconversion", "affected_ids": ["X"], "expected_amount_minor": 10,
                 "currency": "USD", "amount_tolerance_minor": 1, "evidence_sets": [["e1"]]},
                {"issue_id": "B", "type": "fx_misconversion", "affected_ids": ["X"], "expected_amount_minor": 11,
                 "currency": "USD", "amount_tolerance_minor": 1, "evidence_sets": [["e1"]]}]}, f)
        f1 = {"type": "fx_misconversion", "affected_ids": ["X"], "claimed_amount_minor": 11, "currency": "USD",
              "evidence_ids": ["e1"], "explanation": ""}
        f2 = dict(f1, claimed_amount_minor=10)
        r = ja.score_episode(d, {"findings": [f1, f2]}, 0)
        self.assertEqual((r["tp"], r["fp"], r["fn"]), (2, 0, 0))


class TestFileLevelPairedChecks(unittest.TestCase):
    """P01-P20: reorder records and/or replace ids consistently in a COPIED episode directory."""

    def _transform(self, src, dst, reorder, rename, seed):
        shutil.copytree(src, dst)
        rng = random.Random(seed)
        mapping = {}
        if rename:
            ids = set()
            with open(os.path.join(dst, "ledger.csv"), newline="") as f:
                for r in csv.DictReader(f):
                    ids.update(v for k, v in r.items() if k in ("row_id", "entity_id", "invoice_id", "payment_id") and v != "null")
            for name in ("invoices.jsonl", "payments.jsonl"):
                with open(os.path.join(dst, name)) as f:
                    for line in f:
                        d = json.loads(line)
                        ids.update(d[k] for k in ("doc_id", "invoice_id", "payment_id", "entity_id") if k in d)
            for i in sorted(ids):
                mapping[i] = "Z%07d" % rng.randrange(10 ** 7)
                while list(mapping.values()).count(mapping[i]) > 1:
                    mapping[i] = "Z%07d" % rng.randrange(10 ** 7)
            import re
            pat = re.compile("|".join(re.escape(k) for k in sorted(mapping, key=len, reverse=True)))
            for name in os.listdir(dst):
                p = os.path.join(dst, name)
                with open(p, encoding="utf-8") as f:
                    txt = f.read()
                with open(p, "w", encoding="utf-8") as f:
                    f.write(pat.sub(lambda m: mapping[m.group(0)], txt))
        if reorder:
            for name in ("ledger.csv", "fx.csv"):
                p = os.path.join(dst, name)
                with open(p, encoding="utf-8") as f:
                    lines = f.read().splitlines()
                head, body = lines[0], lines[1:]
                rng.shuffle(body)
                with open(p, "w", encoding="utf-8") as f:
                    f.write("\n".join([head] + body) + "\n")
            for name in ("invoices.jsonl", "payments.jsonl"):
                p = os.path.join(dst, name)
                with open(p, encoding="utf-8") as f:
                    lines = [l for l in f.read().splitlines() if l.strip()]
                rng.shuffle(lines)
                with open(p, "w", encoding="utf-8") as f:
                    f.write("\n".join(lines) + "\n")
        return mapping

    def _oracle(self, d):
        with open(os.path.join(d, "truth.json")) as f:
            truth = json.load(f)
        return {"episode_id": truth["episode_id"], "findings": [
            {"type": i["type"], "affected_ids": i["affected_ids"], "claimed_amount_minor": i["expected_amount_minor"],
             "currency": i["currency"], "evidence_ids": i["evidence_sets"][0], "explanation": ""} for i in truth["issues"]]}

    def test_reorder_rename_preserve_scores(self):
        tmp = tempfile.mkdtemp()
        try:
            for k, (preset, reorder, rename) in enumerate([("clean", True, False), ("all_types", False, True),
                                                            ("interacting", True, True), ("mixed", True, True)]):
                src = os.path.join(tmp, "src%d" % k)
                ja.generate_episode(5000 + k, {"preset": preset}, src)
                dst = os.path.join(tmp, "dst%d" % k)
                self._transform(src, dst, reorder, rename, k)
                a = ja.score_episode(src, self._oracle(src), 12)
                b = ja.score_episode(dst, self._oracle(dst), 12)
                for key in ("tp", "fp", "fn", "precision", "recall", "f1", "return"):
                    self.assertEqual(a[key], b[key], (preset, key))
                self.assertEqual(a["return"], 1 - 0.002 * 12)
                env = ja.make_env()                       # transformed directory runs end to end
                obs, _ = env.reset(0, {"mode": "closed", "episode_dir": dst})
                env.step({"name": "submit", "args": {"findings": self._oracle(dst)}})
                self.assertEqual(env.last_grade["f1"], 1.0)
        finally:
            shutil.rmtree(tmp)


if __name__ == "__main__":
    unittest.main()
