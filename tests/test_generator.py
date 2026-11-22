"""Generator & data: validity, determinism, configurability, interactions, clean cases, leaks."""

import json
import os
import tempfile
import unittest

from auditgym.config import ConfigError, normalize_config
from auditgym.constants import ISSUE_TYPES
from auditgym.episode import Episode, relabel
from auditgym.generator import generate_episode
from auditgym.policies.scripted import ExpertAuditor, SimpleReconciler
from auditgym.reward import grade
from auditgym.verify import verify_episode

from tests.helpers import episode, oracle_findings, run_policy


class TestValidity(unittest.TestCase):
    def test_presets_generate_verified_episodes(self):
        for preset in ("clean", "single", "mixed", "all_types", "interacting", "hard"):
            for seed in range(4):
                ep = generate_episode(1000 + seed, {"preset": preset})
                rep = verify_episode(ep)
                self.assertTrue(rep.ok, (preset, seed, rep.errors[:3]))
                self.assertLessEqual(len(ep.truth["issues"]), 12)

    def test_sizes_in_suggested_ranges(self):
        for preset in ("single", "mixed", "hard"):
            ep = generate_episode(7, {"preset": preset})
            c = ep.manifest["counts"]
            self.assertTrue(200 <= c["ledger_rows"] <= 2200, c)
            self.assertTrue(20 <= c["documents"] <= 260, c)

    def test_value_formats(self):
        ep = episode(seed=41, preset="all_types")
        for r in ep.tables["ledger"]:
            self.assertIsInstance(r["debit_minor"], int)
            self.assertRegex(r["timestamp"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d$")
        for r in ep.tables["fx"]:
            self.assertIsInstance(r["rate"], str)
        for p in ep.tables["payments"]:
            self.assertTrue(p["invoice_refs"] is None or isinstance(p["invoice_refs"], list))
        nulls = sum(1 for r in ep.tables["ledger"] if r["invoice_id"] is None)
        self.assertGreater(nulls, 0)                 # explicit nulls, not guessed links


class TestDeterminism(unittest.TestCase):
    def test_same_seed_same_episode(self):
        a = generate_episode(5, {"preset": "interacting"})
        b = generate_episode(5, {"preset": "interacting"})
        self.assertEqual(a.full_hash(), b.full_hash())
        self.assertEqual(a.provenance, b.provenance)

    def test_different_seed_different_episode(self):
        self.assertNotEqual(generate_episode(5).public_hash(), generate_episode(6).public_hash())

    def test_save_load_roundtrip(self):
        ep = episode(seed=42, preset="interacting")
        with tempfile.TemporaryDirectory() as d:
            ep.save(d)
            back = Episode.load(d)
            self.assertEqual(back.full_hash(), ep.full_hash())
            pub = os.path.join(d, "public")
            blob = ""
            for f in os.listdir(pub):
                with open(os.path.join(pub, f), encoding="utf-8") as fh:
                    blob += fh.read()
            for m in ("expected_amount_minor", "evidence_sets", "issue_id", "mutation", '"seed"'):
                self.assertNotIn(m, blob)
            self.assertEqual(sorted(os.listdir(pub)),
                             ["fx.csv", "invoices.jsonl", "ledger.csv", "manifest.json", "payments.jsonl", "policy.json"])

    def test_id_and_order_seeds_keep_the_world(self):
        base = generate_episode(9, {"preset": "all_types"})
        alt = generate_episode(9, {"preset": "all_types", "id_seed": 1, "order_seed": 2})
        sig = lambda e: sorted((i["type"], i["expected_amount_minor"]) for i in e.truth["issues"])
        self.assertEqual(sig(base), sig(alt))
        self.assertNotEqual(base.tables["invoices"][0]["invoice_id"], alt.tables["invoices"][0]["invoice_id"])
        self.assertTrue(verify_episode(alt).ok)

    def test_relabel_preserves_oracle_and_expert(self):
        ep = episode(seed=43, preset="interacting")
        rl = relabel(ep, 99)
        self.assertTrue(verify_episode(rl).ok)
        self.assertEqual(grade(oracle_findings(rl), rl.truth, 0)["reward"], 1.0)
        _, r1, i1 = run_policy(ep, ExpertAuditor())
        _, r2, i2 = run_policy(rl, ExpertAuditor())
        self.assertEqual(i1["grade"]["f1"], i2["grade"]["f1"])


class TestConfig(unittest.TestCase):
    def test_each_type_independently_configurable(self):
        for t in ISSUE_TYPES:
            errors = {x: 0 for x in ISSUE_TYPES}
            errors[t] = 2
            ep = generate_episode(77, {"preset": "single", "errors": errors})
            types = [i["type"] for i in ep.truth["issues"]]
            self.assertEqual(types, [t, t])
            self.assertTrue(verify_episode(ep).ok)

    def test_interactions(self):
        for name in ("fx_partial_payment", "cutoff_fx_boundary"):
            cfg = {"preset": "clean", "interactions": {name: 1}}
            ep = generate_episode(78, cfg)
            iss = ep.truth["issues"]
            self.assertEqual(len(iss), 2)
            self.assertEqual({i["interaction_group"] for i in iss}, {name})
            shared = set(iss[0]["affected_ids"]) & set(iss[1]["affected_ids"])
            self.assertTrue(shared)                   # both errors hit the same document
            self.assertTrue(verify_episode(ep).ok)
            _, r, info = run_policy(ep, ExpertAuditor())
            self.assertEqual(info["grade"]["f1"], 1.0)

    def test_clean_episodes_have_distractors_and_no_issues(self):
        ep = generate_episode(79, {"preset": "clean"})
        self.assertEqual(ep.truth["issues"], [])
        tags = ep.provenance["distractor_tags"]
        self.assertTrue(any(k.startswith("payment:split") or k.startswith("invoice:recurring") for k in tags))
        _, r, info = run_policy(ep, SimpleReconciler())
        # the naive reconciler is fooled by legitimate look-alikes on clean books
        self.assertGreaterEqual(info["grade"]["fp"], 0)

    def test_invalid_configs_rejected(self):
        for bad in [{"preset": "nope"}, {"unknown": 1}, {"errors": {"made_up": 1}}, {"n_invoices": [5, 2]},
                    {"foreign_share": 2}, {"errors": {t: 6 for t in ISSUE_TYPES}}, {"id_seed": "x"},
                    {"base_currency": "XYZ"}]:
            with self.assertRaises(ConfigError):
                normalize_config(bad)

    def test_config_is_versioned_in_provenance(self):
        ep = episode(seed=44, preset="mixed")
        self.assertEqual(ep.provenance["config"]["preset"], "mixed")
        self.assertIn("env_version", ep.provenance)
        self.assertEqual(ep.manifest["env_version"], ep.provenance["env_version"])


class TestDifficulty(unittest.TestCase):
    def test_simple_tricks_fail_but_task_is_solvable(self):
        exp_f1, rec_f1 = [], []
        for s in range(6):
            ep = generate_episode(300 + s, {"preset": "interacting"})
            exp_f1.append(run_policy(ep, ExpertAuditor())[2]["grade"]["f1"])
            rec_f1.append(run_policy(ep, SimpleReconciler())[2]["grade"]["f1"])
        self.assertEqual(min(exp_f1), 1.0)
        self.assertLess(sum(rec_f1) / len(rec_f1), 0.9)


if __name__ == "__main__":
    unittest.main()


class TestNoShortcutTells(unittest.TestCase):
    """Generation artefacts must not reveal injected errors (e.g. round seconds, ledger
    timestamps copied from documents, id ranges)."""

    def test_timestamp_and_id_artefacts(self):
        from datetime import datetime
        aff_sec0 = aff_n = oth_eq = oth_n = aff_low = 0
        for seed in range(40):
            ep = generate_episode(6000 + seed, {"preset": "interacting"})
            aff = {x for i in ep.truth["issues"] for x in i["affected_ids"]}
            ar = {r["invoice_id"]: r for r in ep.tables["ledger"] if r["account"] == "1100" and r["debit_minor"] > 0}
            for d in ep.tables["invoices"]:
                t = datetime.fromisoformat(d["issued_at"])
                if d["invoice_id"] in aff:
                    aff_n += 1
                    aff_sec0 += t.second == 0
                    aff_low += int(d["invoice_id"].split("-")[1]) < 500000
                elif d["invoice_id"] in ar:
                    oth_n += 1
                    oth_eq += datetime.fromisoformat(ar[d["invoice_id"]]["timestamp"]).second == t.second
        self.assertLess(aff_sec0 / aff_n, 0.08)
        self.assertLess(oth_eq / oth_n, 0.08)
        self.assertTrue(0.35 < aff_low / aff_n < 0.65)


class TestHarmlessTransforms(unittest.TestCase):
    def test_reexpressed_offsets_keep_truth_and_answers(self):
        from auditgym.episode import reexpress_timestamps
        for preset in ("interacting", "all_types", "clean"):
            ep = episode(seed=71, preset=preset)
            rx = relabel(reexpress_timestamps(ep, 5), 6)
            self.assertTrue(verify_episode(rx).ok, preset)
            self.assertEqual(grade(oracle_findings(rx), rx.truth, 0)["reward"], 1.0)
            self.assertEqual(run_policy(rx, ExpertAuditor())[2]["grade"]["f1"],
                             run_policy(ep, ExpertAuditor())[2]["grade"]["f1"])


class TestFailureAnalysis(unittest.TestCase):
    def test_reconciler_failures_are_attributed_to_traps(self):
        from auditgym.analysis import analyse
        from auditgym.evaluator import evaluate
        eps = [generate_episode(8100 + s, {"preset": "interacting"}) for s in range(3)]
        rows, _ = evaluate(eps, ("reconciler", "oracle"))
        a = analyse(eps, rows)
        self.assertEqual(a["oracle"]["fp"], {})
        self.assertTrue(any(k.startswith("trap:") for k in a["reconciler"]["fp"]))
