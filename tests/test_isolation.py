"""Evaluator runs policies out of process; timeouts truncate; adapters behave."""

import unittest

from auditgym.evaluator import WorkerProcess, evaluate, run_episode, summarize
from auditgym.policies.scripted import SimpleReconciler

from tests.helpers import episode, run_policy


class TestIsolation(unittest.TestCase):
    def test_worker_matches_in_process(self):
        ep = episode(seed=51, preset="mixed")
        w = WorkerProcess("reconciler")
        try:
            g, _ = run_episode(ep, "reconciler", w)
        finally:
            w.close()
        _, _, info = run_policy(ep, SimpleReconciler())
        self.assertEqual(g["reward"], info["grade"]["reward"])

    def test_timeout_truncates(self):
        ep = episode(seed=52, preset="single")
        w = WorkerProcess("expert")
        try:
            g, _ = run_episode(ep, "expert", w, time_limit_s=0.0)
        finally:
            w.close()
        self.assertEqual(g["terminated_by"], "time_limit")
        self.assertEqual(g["n_findings"], 0)

    def test_four_baseline_adapters(self):
        eps = [episode(seed=53, preset="clean"), episode(seed=54, preset="interacting")]
        rows, _ = evaluate(eps, ("random", "reconciler", "flag_all", "oracle"))
        s = summarize(rows)
        self.assertEqual(s["oracle"]["mean_return"], 1.0)
        self.assertEqual(s["flag_all"]["mean_return"], -1.0)
        self.assertLess(s["random"]["mean_return"], 0.5)
        for p in s.values():
            self.assertEqual(p["episodes"], 2)


if __name__ == "__main__":
    unittest.main()
