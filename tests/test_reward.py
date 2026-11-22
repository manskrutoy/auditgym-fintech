"""Matcher & terminal reward: required orderings, attacks, normalisation, edge cases."""

import unittest

from auditgym.constants import ISSUE_TYPES
from auditgym.matcher import match, validate_submission
from auditgym.reward import grade, metrics, shared_reward

from tests.helpers import episode, finding_from_issue, sub


def R(ep, findings, steps=0):
    return grade(sub(ep, findings), ep.truth, steps)


def _known(ep):
    ids = set()
    for rows in ep.tables.values():
        for r in rows:
            for k in ("row_id", "doc_id", "invoice_id", "payment_id", "fx_id"):
                if r.get(k):
                    ids.add(r[k])
    return ids


class TestMetrics(unittest.TestCase):
    def test_edge_cases(self):
        self.assertEqual(metrics(0, 0, 0), (0.0, 0.0, 1.0))      # empty truth, empty answer
        self.assertEqual(metrics(0, 3, 0)[2], 0.0)               # empty truth, accusations
        self.assertEqual(metrics(0, 0, 4), (0.0, 0.0, 0.0))
        p, r, f = metrics(2, 1, 1)
        self.assertAlmostEqual(p, 2 / 3)
        self.assertAlmostEqual(r, 2 / 3)
        self.assertAlmostEqual(f, 4 / 6)

    def test_reward_formula_and_clip(self):
        self.assertEqual(shared_reward(1.0, 0), 1.0)
        self.assertAlmostEqual(shared_reward(1.0, 50), 0.9)
        self.assertEqual(shared_reward(0.0, 100), -1.0)
        self.assertGreaterEqual(shared_reward(0.0, 10 ** 6), -1.0)


class TestRequiredOrderings(unittest.TestCase):
    """The five properties required by section 05."""

    def setUp(self):
        self.err = episode(seed=31, preset="interacting")
        self.clean = episode(seed=32, preset="clean")
        self.assertTrue(self.err.truth["issues"])
        self.assertFalse(self.clean.truth["issues"])
        self.full = [finding_from_issue(i) for i in self.err.truth["issues"]]

    def test_full_correct_answer_beats_silence_on_erroneous_books(self):
        g_full, g_silent = R(self.err, self.full, 40), R(self.err, [], 0)
        self.assertEqual(g_full["f1"], 1.0)
        self.assertGreater(g_full["reward"], g_silent["reward"])
        self.assertEqual(g_silent["reward"], -1.0)

    def test_silence_beats_false_accusations_on_clean_books(self):
        inv = self.clean.tables["invoices"][0]
        row = self.clean.tables["ledger"][0]
        accuse = [{"type": "duplicate_invoice", "affected_ids": [inv["invoice_id"]], "claimed_amount_minor": inv["total_minor"],
                   "currency": inv["currency"], "evidence_ids": [inv["doc_id"], row["row_id"]], "explanation": "x"}]
        g_silent, g_acc = R(self.clean, [], 30), R(self.clean, accuse, 30)
        self.assertGreater(g_silent["reward"], g_acc["reward"])
        self.assertAlmostEqual(g_silent["reward"], 1.0 - 0.06)
        self.assertEqual(g_acc["reward"], -1.0)

    def test_duplicates_give_no_benefit(self):
        once = R(self.err, self.full)
        twice = R(self.err, self.full + self.full)
        self.assertEqual(once["tp"], twice["tp"])
        self.assertEqual(twice["fp"], len(self.full))
        self.assertLess(twice["reward"], once["reward"])
        # padding one correct finding with copies never beats submitting it once
        one = R(self.err, self.full[:1])
        many = R(self.err, self.full[:1] * 5)
        self.assertLess(many["reward"], one["reward"])

    def test_flag_everything_scores_badly(self):
        ep = self.err
        spam = []
        for inv in ep.tables["invoices"]:
            for t in ISSUE_TYPES:
                spam.append({"type": t, "affected_ids": [inv["invoice_id"]], "claimed_amount_minor": inv["total_minor"],
                             "currency": inv["currency"], "evidence_ids": [inv["doc_id"]], "explanation": "all"})
        g = R(ep, spam[:30])
        self.assertLessEqual(g["reward"], -0.9)
        # even spamming on top of the full correct answer is clearly worse than the answer alone
        g2 = R(ep, self.full + spam[:30 - len(self.full)])
        self.assertLess(g2["reward"], R(ep, self.full)["reward"] - 0.5)

    def test_step_savings_only_slightly_separate_equal_answers(self):
        a, b = R(self.err, self.full, 10), R(self.err, self.full, 90)
        self.assertGreater(a["reward"], b["reward"])
        self.assertLessEqual(a["reward"] - b["reward"], 0.2 + 1e-9)
        # one extra true positive is worth more than any step saving
        partial = R(self.err, self.full[:-1], 0)
        self.assertGreater(b["reward"], partial["reward"])


class TestAttacks(unittest.TestCase):
    def setUp(self):
        self.ep = episode(seed=33, preset="all_types")
        self.issues = {i["type"]: i for i in self.ep.truth["issues"]}

    def test_guessed_ids_do_not_match(self):
        iss = self.issues["period_cutoff"]
        wrong = self.ep.tables["invoices"][0]["invoice_id"]
        if wrong in iss["affected_ids"]:
            wrong = self.ep.tables["invoices"][1]["invoice_id"]
        g = R(self.ep, [finding_from_issue(iss, affected_ids=[wrong])])
        self.assertEqual(g["tp"], 0)
        self.assertEqual(g["fp"], 1)
        # partial id set for a two-id issue
        dup = self.issues["duplicate_invoice"]
        g = R(self.ep, [finding_from_issue(dup, affected_ids=dup["affected_ids"][:1])])
        self.assertEqual(g["tp"], 0)
        # superset of ids
        g = R(self.ep, [finding_from_issue(dup, affected_ids=dup["affected_ids"] + [wrong])])
        self.assertEqual(g["tp"], 0)

    def test_unsupported_evidence_does_not_match(self):
        for iss in self.ep.truth["issues"]:
            ev = iss["evidence_sets"][0]
            for drop in range(len(ev)):
                g = R(self.ep, [finding_from_issue(iss, evidence_ids=ev[:drop] + ev[drop + 1:])])
                self.assertEqual(g["tp"], 0, (iss["type"], drop))
            g = R(self.ep, [finding_from_issue(iss, evidence_ids=[])])
            self.assertEqual(g["tp"], 0)
            # extra (irrelevant) evidence is fine
            extra = ev + [self.ep.tables["ledger"][0]["row_id"]]
            g = R(self.ep, [finding_from_issue(iss, evidence_ids=extra[:10])])
            self.assertEqual(g["tp"], 1)

    def test_currency_must_match(self):
        for iss in self.ep.truth["issues"]:
            other = "XXX" if iss["currency"] != "XXX" else "YYY"
            self.assertEqual(R(self.ep, [finding_from_issue(iss, currency=other)])["tp"], 0)
            # jury convention: currency is compared exactly (no case folding, no trimming)
            self.assertEqual(R(self.ep, [finding_from_issue(iss, currency=iss["currency"].lower())])["tp"], 0)
            self.assertEqual(R(self.ep, [finding_from_issue(iss, currency=" " + iss["currency"])])["tp"], 0)

    def test_amount_tolerance(self):
        fx = self.issues["fx_misconversion"]
        e = fx["expected_amount_minor"]
        self.assertEqual(R(self.ep, [finding_from_issue(fx, claimed_amount_minor=e + 1)])["tp"], 1)
        self.assertEqual(R(self.ep, [finding_from_issue(fx, claimed_amount_minor=e + 2)])["tp"], 0)
        dup = self.issues["duplicate_invoice"]
        self.assertEqual(R(self.ep, [finding_from_issue(dup, claimed_amount_minor=dup["expected_amount_minor"] + 1)])["tp"], 0)

    def test_type_must_match(self):
        iss = self.issues["period_cutoff"]
        g = R(self.ep, [finding_from_issue(iss, type="fx_misconversion")])
        self.assertEqual(g["tp"], 0)

    def test_explanation_is_not_scored(self):
        iss = self.issues["unallocated_payment"]
        a = R(self.ep, [finding_from_issue(iss, explanation="")])
        b = R(self.ep, [finding_from_issue(iss, explanation="I am extremely confident, this is definitely right " * 10)])
        self.assertEqual(a["reward"], b["reward"])
        bad = R(self.ep, [finding_from_issue(self.issues["period_cutoff"], affected_ids=["INV-000000"],
                                             explanation="trust me, this is the duplicate invoice " * 5)])
        self.assertEqual(bad["tp"], 0)

    def test_sets_exact_ids_and_existing_evidence(self):
        dup = self.issues["duplicate_invoice"]
        # order and repeats do not matter (sets)
        f = finding_from_issue(dup, affected_ids=list(reversed(dup["affected_ids"])),
                               evidence_ids=list(reversed(dup["evidence_sets"][0])) + [dup["evidence_sets"][0][0]])
        self.assertEqual(R(self.ep, [f])["tp"], 1)
        # ids are exact: no trimming, case-sensitive
        f = finding_from_issue(dup, affected_ids=[" " + x for x in dup["affected_ids"]])
        self.assertEqual(R(self.ep, [f])["tp"], 0)
        f = finding_from_issue(dup, affected_ids=[x.lower() for x in dup["affected_ids"]])
        self.assertEqual(R(self.ep, [f])["tp"], 0)
        # extra EXISTING evidence is fine, evidence that does not exist is not
        ok = dup["evidence_sets"][0] + [self.ep.tables["ledger"][0]["row_id"]]
        self.assertEqual(grade(sub(self.ep, [finding_from_issue(dup, evidence_ids=ok)]), self.ep.truth, 0,
                               known_ids=_known(self.ep))["tp"], 1)
        bad = dup["evidence_sets"][0] + ["ROW-doesnotexist"]
        self.assertEqual(grade(sub(self.ep, [finding_from_issue(dup, evidence_ids=bad)]), self.ep.truth, 0,
                               known_ids=_known(self.ep))["tp"], 0)


class TestSchema(unittest.TestCase):
    def setUp(self):
        self.ep = episode(seed=34, preset="single")
        self.good = {"type": "duplicate_invoice", "affected_ids": ["INV-1"], "claimed_amount_minor": 5,
                     "currency": "USD", "evidence_ids": [], "explanation": ""}

    def bad(self, **over):
        f = dict(self.good)
        f.update(over)
        return R(self.ep, [f])

    def test_invalid_structures_give_minus_one(self):
        structural = [
            {"claimed_amount_minor": True}, {"claimed_amount_minor": 1.5}, {"claimed_amount_minor": "5"},
            {"currency": 840}, {"affected_ids": "INV-1"}, {"affected_ids": [1]}, {"type": 7},
            {"evidence_ids": ["x"] * 11}, {"explanation": "x" * 1001}, {"evidence_ids": "E1"},
        ]
        for c in structural:
            g = self.bad(**c)
            self.assertFalse(g["valid"], c)
            self.assertEqual(g["reward"], -1.0)
        f = dict(self.good)
        del f["currency"]
        self.assertEqual(R(self.ep, [f])["reward"], -1.0)
        self.assertEqual(R(self.ep, [self.good] * 31)["reward"], -1.0)
        self.assertEqual(grade({"episode_id": "other", "findings": []}, self.ep.truth, 0)["reward"], -1.0)
        self.assertEqual(grade({"episode_id": self.ep.episode_id}, self.ep.truth, 0)["reward"], -1.0)
        self.assertEqual(grade("not json", self.ep.truth, 0)["reward"], -1.0)

    def test_wrong_content_is_only_a_false_positive(self):
        # jury convention: wrong content does not invalidate the submit
        for c in [{"type": "made_up"}, {"claimed_amount_minor": -1}, {"currency": "US"}, {"affected_ids": []},
                  {"affected_ids": ["x"] * 11}]:
            g = self.bad(**c)
            self.assertTrue(g["valid"], c)
            self.assertEqual(g["fp"], 1, c)
        f = dict(self.good, extra_field=1)
        self.assertTrue(R(self.ep, [f])["valid"])

    def test_limits_exactly_allowed(self):
        f = dict(self.good, evidence_ids=["E%d" % i for i in range(10)], explanation="x" * 1000)
        g = R(self.ep, [f] * 30)
        self.assertTrue(g["valid"])


class TestMatching(unittest.TestCase):
    def test_maximum_one_to_one(self):
        truth = [
            {"issue_id": "a", "type": "fx_misconversion", "affected_ids": ["X"], "expected_amount_minor": 10,
             "currency": "USD", "amount_tolerance_minor": 1, "evidence_sets": [["e1"]]},
            {"issue_id": "b", "type": "fx_misconversion", "affected_ids": ["X"], "expected_amount_minor": 11,
             "currency": "USD", "amount_tolerance_minor": 1, "evidence_sets": [["e1"]]},
        ]
        f1 = {"type": "fx_misconversion", "affected": frozenset(["X"]), "amount": 11, "currency": "USD", "evidence": frozenset(["e1"])}
        f2 = dict(f1, amount=10)
        # f1 is compatible with a and b, f2 only with a: greedy would fail, maximum matching finds 2
        pairs, fp, fn = match([f1, f2], truth)
        self.assertEqual(len(pairs), 2)
        self.assertEqual((fp, fn), ([], []))
        pairs, fp, fn = match([f1, f1, f1], truth)
        self.assertEqual(len(pairs), 2)
        self.assertEqual(len(fp), 1)

    def test_validate_keeps_ids_exact(self):
        out = validate_submission({"episode_id": "e", "findings": [{"type": "period_cutoff", "affected_ids": [" A ", "A"],
                                   "claimed_amount_minor": 1, "currency": "usd", "evidence_ids": [" B"], "explanation": ""}]}, "e")
        self.assertEqual(out[0]["affected"], frozenset([" A ", "A"]))
        self.assertEqual(out[0]["currency"], "usd")
        self.assertEqual(out[0]["evidence"], frozenset([" B"]))


if __name__ == "__main__":
    unittest.main()


class TestRedTeamFollowUps(unittest.TestCase):
    def setUp(self):
        self.ep = episode(seed=35, preset="interacting")

    def test_business_id_evidence_alias_and_lenient_submission(self):
        import json
        issues = self.ep.truth["issues"]
        fs = [finding_from_issue(i, evidence_ids=i["evidence_sets"][-1]) for i in issues]
        self.assertEqual(R(self.ep, fs)["tp"], len(issues))
        for f in fs:
            f.pop("explanation")
        self.assertEqual(grade(json.dumps(sub(self.ep, fs)), self.ep.truth, 0)["tp"], len(issues))

    def test_partial_allocation_needs_applied_ar_credits(self):
        for iss in self.ep.truth["issues"]:
            if iss["type"] == "unallocated_payment" and len(iss["evidence_sets"][0]) > 2:
                minimal = [e for e in iss["evidence_sets"][0]][:2]
                self.assertEqual(R(self.ep, [finding_from_issue(iss, evidence_ids=minimal)])["tp"], 0)
                return
        self.skipTest("no partial allocation in this episode")
