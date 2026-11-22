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


class TestHardening(unittest.TestCase):
    def test_evaluator_secret_changes_world_and_is_deterministic(self):
        import os
        from auditgym.generator import generate_episode
        base = generate_episode(123, {"preset": "single"})
        os.environ["AUDITGYM_SECRET"] = "closed-eval-secret"
        try:
            a = generate_episode(123, {"preset": "single"})
            b = generate_episode(123, {"preset": "single"})
        finally:
            del os.environ["AUDITGYM_SECRET"]
        self.assertEqual(a.full_hash(), b.full_hash())
        self.assertNotEqual(a.full_hash(), base.full_hash())
        self.assertNotEqual(a.episode_id, base.episode_id)

    def test_worker_sandbox_has_only_policy_code(self):
        import os
        import subprocess
        import sys
        from auditgym.evaluator import _drop_privileges, policy_sandbox
        d = policy_sandbox()
        files = sorted(os.path.relpath(os.path.join(r, f), d) for r, _, fs in os.walk(d) for f in fs)
        self.assertNotIn(os.path.join("auditgym", "generator.py"), files)
        self.assertNotIn(os.path.join("auditgym", "env.py"), files)
        code = "import sys; sys.path.insert(0, %r)\ntry:\n import auditgym.generator; print('LEAK')\nexcept ImportError: print('ok')" % d
        r = subprocess.run([sys.executable, "-I", "-S", "-c", code], capture_output=True, text=True, cwd=d,
                           env={"PATH": "/usr/bin:/bin", "AUDITGYM_SECRET": ""}, preexec_fn=_drop_privileges)
        self.assertEqual(r.stdout.strip(), "ok")
