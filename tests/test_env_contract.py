"""Contract & isolation: reset/step, schemas, limits, termination, invalid input, leaks."""

import json
import unittest

from auditgym.constants import MAX_STEPS
from auditgym.env import AuditEnv
from auditgym.policies.scripted import ExpertAuditor

from tests.helpers import episode, oracle_findings, run_policy, sub

CLOSED_MARKERS = ('"expected_amount_minor"', '"evidence_sets"', '"issue_id"', '"mutation"',
                  '"provenance"', '"seed"', "truth.json", "private")


class TestReset(unittest.TestCase):
    def test_reset_returns_observation_and_info(self):
        env = AuditEnv()
        obs, info = env.reset(seed=11, config={"preset": "single"})
        for k in ("task", "episode_id", "manifest", "policy", "tools", "remaining_steps"):
            self.assertIn(k, obs)
        self.assertEqual(obs["remaining_steps"], MAX_STEPS)
        for k in ("schema_version", "episode_id", "base_currency", "period_start", "period_end", "timezone", "counts", "rounding"):
            self.assertIn(k, obs["manifest"])
        self.assertEqual(info["mode"], "train")
        dumped = json.dumps([obs, info])
        self.assertNotIn('"seed"', dumped)
        self.assertRegex(obs["episode_id"], r"^ep-[0-9a-f]{12}$")   # a hash, not the seed

    def test_same_seed_same_records_and_transitions(self):
        actions = [{"action": "list_records", "table": "ledger", "cursor": None, "limit": 50},
                   {"action": "list_records", "table": "ledger", "cursor": "c1:ledger:50", "limit": 7},
                   {"action": "get_record", "table": "invoices", "id": "nope"},
                   {"action": "calculator", "expression": "1.10 * 3"}]
        outs = []
        for _ in range(2):
            env = AuditEnv()
            o, _ = env.reset(seed=77, config={"preset": "mixed"})
            seq = [o]
            for a in actions:
                seq.append(env.step(a)[:4])
            outs.append(json.dumps(seq, sort_keys=True))
        self.assertEqual(outs[0], outs[1])

    def test_reset_isolates_state(self):
        env = AuditEnv()
        env.reset(seed=1, config={"preset": "single"})
        for _ in range(5):
            env.step({"action": "calculator", "expression": "1+1"})
        submit = {"action": "submit", "findings": {"episode_id": env._ep.episode_id, "findings": []}}
        env.step(submit)
        obs, _ = env.reset(seed=2, config={"preset": "single"})
        self.assertEqual(env.steps_used, 0)
        self.assertFalse(env.done)
        self.assertEqual(obs["remaining_steps"], MAX_STEPS)

    def test_step_before_reset_raises(self):
        with self.assertRaises(RuntimeError):
            AuditEnv().step({"action": "calculator", "expression": "1"})


class TestTools(unittest.TestCase):
    def setUp(self):
        self.ep = episode(seed=901, preset="mixed")
        self.env = AuditEnv()
        self.env.reset(episode=self.ep)

    def test_page_limit_and_stable_cursor(self):
        o, r, te, tr, _ = self.env.step({"action": "list_records", "table": "ledger", "limit": 500})
        res = o["result"]
        self.assertEqual(len(res["records"]), 50)
        self.assertEqual(res["next_cursor"], "c1:ledger:50")
        o2 = self.env.step({"action": "list_records", "table": "ledger", "cursor": res["next_cursor"]})[0]
        o3 = self.env.step({"action": "list_records", "table": "ledger", "cursor": res["next_cursor"]})[0]
        self.assertEqual(o2["result"], o3["result"])
        self.assertEqual(o2["result"]["records"][0], self.ep.tables["ledger"][50])
        self.assertEqual((r, te, tr), (0.0, False, False))

    def test_cursor_reaches_end(self):
        n = len(self.ep.tables["invoices"])
        cur, got = None, []
        while True:
            o = self.env.step({"action": "list_records", "table": "invoices", "cursor": cur})[0]
            got += o["result"]["records"]
            cur = o["result"]["next_cursor"]
            if cur is None:
                break
        self.assertEqual(len(got), n)

    def test_errors_are_bounded_and_consume_steps(self):
        bad = [
            {"action": "list_records", "table": "secrets"},
            {"action": "list_records", "table": "ledger", "cursor": "c1:invoices:0"},
            {"action": "list_records", "table": "ledger", "cursor": "garbage"},
            {"action": "list_records", "table": "ledger", "limit": 0},
            {"action": "get_record", "table": "ledger", "id": "ROW-doesnotexist"},
            {"action": "get_document", "doc_id": "DOC-x" * 30},
            {"action": "rm_rf"},
            {"action": "get_record", "table": "ledger"},
            {"action": "calculator", "expression": "1", "shell": "ls"},
            "not a dict",
            {"no_action": 1},
        ]
        for i, a in enumerate(bad, start=1):
            o, r, te, tr, info = self.env.step(a)
            self.assertIsNotNone(o["error"], a)
            self.assertLessEqual(len(o["error"]["message"]), 200)
            self.assertEqual(o["step"], i)
            self.assertEqual(o["remaining_steps"], MAX_STEPS - i)
            self.assertFalse(te or tr)
            blob = json.dumps(o)
            for m in CLOSED_MARKERS:
                self.assertNotIn(m, blob)

    def test_get_record_and_document(self):
        inv = self.ep.tables["invoices"][3]
        o = self.env.step({"action": "get_record", "table": "invoices", "id": inv["invoice_id"]})[0]
        self.assertEqual(o["result"]["record"], inv)
        o = self.env.step({"action": "get_document", "doc_id": inv["doc_id"]})[0]
        self.assertEqual(o["result"]["doc_type"], "invoice")
        fx = self.ep.tables["fx"][0]
        o = self.env.step({"action": "get_record", "table": "fx", "id": fx["fx_id"]})[0]
        self.assertEqual(o["result"]["record"], fx)

    def test_observations_are_copies(self):
        o = self.env.step({"action": "list_records", "table": "ledger", "limit": 1})[0]
        o["result"]["records"][0]["debit_minor"] = -999
        o2 = self.env.step({"action": "list_records", "table": "ledger", "limit": 1})[0]
        self.assertNotEqual(o2["result"]["records"][0]["debit_minor"], -999)

    def test_calculator_arithmetic_only(self):
        ok = {"1.10 * 3": "3.3", "(2+3)*4": "20", "10/4": "2.5", "-7 // 2": "-4", "2**10": "1024",
              "123456789.123 * 1.000001": "123456912.579789123"}
        for e, v in ok.items():
            o = self.env.step({"action": "calculator", "expression": e})[0]
            self.assertEqual(o["result"]["value"], v, e)
        for e in ["__import__('os')", "open('x')", "a + 1", "1;2", "[1,2]", "1/0", "9**999999", "x" * 300,
                  "1 if 1 else 2", "lambda: 1"]:
            o = self.env.step({"action": "calculator", "expression": e})[0]
            self.assertEqual(o["error"]["code"], "calc_error", e)


class TestTermination(unittest.TestCase):
    def test_step_limit_truncates_with_empty_answer(self):
        ep = episode(seed=902, preset="all_types")
        env = AuditEnv()
        env.reset(episode=ep)
        for i in range(MAX_STEPS):
            o, r, te, tr, info = env.step({"action": "calculator", "expression": "1+1"})
            if i < MAX_STEPS - 1:
                self.assertFalse(te or tr)
        self.assertTrue(tr)
        self.assertFalse(te)
        self.assertEqual(env.last_grade["n_findings"], 0)
        self.assertEqual(env.last_grade["inspection_steps"], 100)
        self.assertAlmostEqual(r, -1.0)          # empty answer on erroneous books

    def test_submit_at_step_100_is_allowed(self):
        ep = episode(seed=902, preset="all_types")
        env = AuditEnv()
        env.reset(episode=ep)
        for _ in range(MAX_STEPS - 1):
            env.step({"action": "calculator", "expression": "1"})
        o, r, te, tr, _ = env.step({"action": "submit", "findings": oracle_findings(ep)})
        self.assertTrue(te)
        self.assertFalse(tr)
        self.assertAlmostEqual(r, 1.0 - 0.002 * 99)

    def test_time_limit_truncates(self):
        t = [0.0]
        env = AuditEnv(clock=lambda: t[0], time_limit_s=60)
        ep = episode(seed=903, preset="single")
        env.reset(episode=ep)
        env.step({"action": "calculator", "expression": "1"})
        t[0] = 61.0
        o, r, te, tr, _ = env.step({"action": "submit", "findings": oracle_findings(ep)})
        self.assertTrue(tr)
        self.assertEqual(env.last_grade["terminated_by"], "time_limit")
        self.assertEqual(env.last_grade["n_findings"], 0)

    def test_after_terminal_nothing_changes(self):
        ep = episode(seed=904, preset="all_types")
        env = AuditEnv()
        env.reset(episode=ep)
        _, r1, te, _, _ = env.step({"action": "submit", "findings": sub(ep, [])})
        g = dict(env.last_grade)
        o, r2, te2, tr2, _ = env.step({"action": "submit", "findings": oracle_findings(ep)})
        self.assertEqual(o["error"]["code"], "episode_finished")
        self.assertEqual(r2, 0.0)
        self.assertEqual(env.last_grade, g)
        self.assertEqual(len(env.evaluator_log), 1)

    def test_invalid_structure_ends_with_minus_one(self):
        ep = episode(seed=905, preset="all_types")
        for bad in [{"episode_id": ep.episode_id}, "x", {"episode_id": "wrong", "findings": []}, None]:
            env = AuditEnv()
            env.reset(episode=ep)
            o, r, te, tr, info = env.step({"action": "submit", "findings": bad})
            self.assertTrue(te)
            self.assertEqual(r, -1.0)
            self.assertFalse(env.last_grade["valid"])
        env = AuditEnv()
        env.reset(episode=ep)
        o, r, te, tr, info = env.step({"action": "submit"})
        self.assertEqual((r, te), (-1.0, True))


class TestModesAndLeaks(unittest.TestCase):
    def test_eval_mode_withholds_reward(self):
        ep = episode(seed=906, preset="all_types")
        env = AuditEnv(mode="eval")
        env.reset(episode=ep)
        o, r, te, tr, info = env.step({"action": "submit", "findings": oracle_findings(ep)})
        self.assertEqual(r, 0.0)
        self.assertTrue(info.get("reward_withheld"))
        self.assertNotIn("grade", info)
        self.assertEqual(o["result"], {"submitted": True})
        self.assertEqual(env.evaluator_log[-1]["reward"], 1.0)

    def test_no_closed_data_in_any_observation(self):
        for preset in ("all_types", "interacting", "clean"):
            ep = episode(seed=907, preset=preset)
            env, r, info = run_policy(ep, ExpertAuditor(), mode="eval")
            blob = json.dumps(env.trajectory)
            for m in CLOSED_MARKERS:
                self.assertNotIn(m, blob)
            for iss in ep.truth["issues"]:
                self.assertNotIn(iss["issue_id"], blob)

    def test_trajectory_fields(self):
        ep = episode(seed=908, preset="single")
        env, r, info = run_policy(ep, ExpertAuditor())
        for t in env.trajectory:
            self.assertEqual(set(t), {"episode_id", "step", "action", "observation", "reward", "terminated", "truncated"})
        self.assertTrue(env.trajectory[-1]["terminated"])
        self.assertEqual([t["step"] for t in env.trajectory], list(range(len(env.trajectory))))


if __name__ == "__main__":
    unittest.main()


class TestRedTeamRegressions(unittest.TestCase):
    """Inputs found by the adversarial review: none may crash step()."""

    def setUp(self):
        self.env = AuditEnv(record_trajectory=True)
        self.env.reset(episode=episode(seed=909, preset="single"))

    def test_malformed_cursors_are_errors(self):
        for c in ["c1:ledger:²", "c1:ledger:" + "0" * 4400, "c1:ledger:١٢", "c1:ledger:-1", "c1:ledger:1.5"]:
            o = self.env.step({"action": "list_records", "table": "ledger", "cursor": c})[0]
            self.assertEqual(o["error"]["code"], "invalid_cursor", c)

    def test_calculator_overflow_and_precision(self):
        for e in ["1e999999*1e999999", "(1e999999)**64", "1e31", "10**31"]:
            o = self.env.step({"action": "calculator", "expression": e})[0]
            self.assertEqual(o["error"]["code"], "calc_error", e)
        o = self.env.step({"action": "calculator", "expression": "1e29 % 7"})[0]
        self.assertEqual(o["result"]["value"], str(10 ** 29 % 7))
        o = self.env.step({"action": "calculator", "expression": "-7 % 3"})[0]
        self.assertEqual(o["result"]["value"], "2")

    def test_error_messages_bounded_and_odd_python_inputs(self):
        o = self.env.step({"action": "get_document", "doc_id": "x", "k" * 100000: 1})[0]
        self.assertLessEqual(len(o["error"]["message"]), 200)
        o = self.env.step({"action": "list_records", "table": "ledger", "limit": {1, 2}})[0]
        self.assertIsNotNone(o["error"])
        o = self.env.step({"action": "get_record", "table": "ledger", "id": b"bytes"})[0]
        self.assertIsNotNone(o["error"])

    def test_non_ascii_currency_rejected(self):
        from auditgym.reward import grade
        ep = episode(seed=909, preset="single")
        f = {"type": "period_cutoff", "affected_ids": ["X"], "claimed_amount_minor": 1, "currency": "UſD",
             "evidence_ids": [], "explanation": ""}
        self.assertFalse(grade({"episode_id": ep.episode_id, "findings": [f]}, ep.truth, 0)["valid"])
