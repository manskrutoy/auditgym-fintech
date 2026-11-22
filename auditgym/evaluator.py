"""Closed evaluator.  Holds the environment (and therefore the truth); runs every
non-oracle policy in a separate OS process that only exchanges JSON observations
and actions.  Rewards/diagnostics stay here until the run is over."""

import json
import os
import selectors
import subprocess
import sys
import tempfile
import time

from .constants import TIME_LIMIT_S
from .env import AuditEnv
from .policies.scripted import Oracle

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


_SANDBOX = None
_POLICY_FILES = ["__init__.py", "constants.py", "money.py", "worker.py",
                 "policies/__init__.py", "policies/base.py", "policies/scripted.py"]


def policy_sandbox():
    """A temp directory holding ONLY the policy code (no generator, env, episodes, configs).
    Workers run from there with `python -I -S`, so they cannot import the generator or read
    project files through the package path."""
    global _SANDBOX
    if _SANDBOX is None or not os.path.isdir(_SANDBOX):
        d = tempfile.mkdtemp(prefix="auditgym-policy-")
        for rel in _POLICY_FILES:
            dst = os.path.join(d, "auditgym", rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(os.path.join(ROOT, "auditgym", rel), "rb") as fi, open(dst, "wb") as fo:
                fo.write(fi.read())
        with open(os.path.join(d, "run_worker.py"), "w") as f:
            f.write("import sys\nsys.path.insert(0, %r)\nfrom auditgym.worker import main\nmain()\n" % d)
        for root, dirs, files in os.walk(d):
            os.chmod(root, 0o755)
            for fn in files:
                os.chmod(os.path.join(root, fn), 0o644)
        _SANDBOX = d
    return _SANDBOX


def _drop_privileges():
    """When the evaluator runs as root (e.g. in the official container), each policy process
    runs as `nobody`: it cannot read the evaluator's private files (mode 700), its environment
    or /proc, nor write into the project."""
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        os.setgroups([])
        os.setgid(65534)
        os.setuid(65534)


def protect_private(root=ROOT):
    """Make closed episode files unreadable for policy processes (they run as `nobody`)."""
    base = os.path.join(root, "episodes")
    for dirpath, dirnames, _ in os.walk(base):
        if os.path.basename(dirpath) == "private":
            try:
                os.chmod(dirpath, 0o700)
            except OSError:
                pass


class WorkerProcess:
    def __init__(self, policy, seed=0):
        sandbox = policy_sandbox()
        protect_private()
        env = {"PATH": "/usr/bin:/bin", "PYTHONHASHSEED": "0", "PYTHONDONTWRITEBYTECODE": "1"}
        self.proc = subprocess.Popen(
            [sys.executable, "-I", "-S", "-B", os.path.join(sandbox, "run_worker.py"),
             "--policy", policy, "--seed", str(seed)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            cwd=sandbox, env=env, text=True, bufsize=1,
            preexec_fn=_drop_privileges if os.name == "posix" else None,
        )
        self.sel = selectors.DefaultSelector()
        self.sel.register(self.proc.stdout, selectors.EVENT_READ)

    def call(self, msg, timeout):
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()
        if not self.sel.select(timeout=max(0.001, timeout)):
            raise TimeoutError
        line = self.proc.stdout.readline()
        if not line:
            raise RuntimeError("worker exited")
        return json.loads(line)

    def close(self):
        try:
            self.proc.stdin.write(json.dumps({"cmd": "close"}) + "\n")
            self.proc.stdin.flush()
            self.proc.wait(timeout=5)
        except Exception:
            self.proc.kill()
            self.proc.wait()
        finally:
            self.sel.close()
            for f in (self.proc.stdin, self.proc.stdout):
                try:
                    f.close()
                except Exception:
                    pass


def run_episode(ep, policy, worker=None, mode="eval", record=False, time_limit_s=TIME_LIMIT_S):
    """Run one episode. `policy` is a name; non-oracle policies need a WorkerProcess."""
    env = AuditEnv(mode=mode, record_trajectory=record, time_limit_s=time_limit_s)
    t0 = time.monotonic()
    obs, info = env.reset(episode=ep)
    local = Oracle(ep.truth) if policy == "oracle" else None
    try:
        if local:
            local.reset(obs)
        else:
            worker.call({"cmd": "reset", "obs": obs}, time_limit_s)
        while True:
            left = time_limit_s - (time.monotonic() - t0)
            action = local.act(obs) if local else worker.call({"cmd": "act", "obs": obs}, left)["action"]
            obs, reward, term, trunc, info = env.step(action)
            if term or trunc:
                break
    except (TimeoutError, RuntimeError):
        env.force_truncate("time_limit")
    except Exception:                            # a broken policy never stops the evaluation run
        env.force_truncate("policy_error")
    g = dict(env.last_grade)
    g["policy"] = policy
    g["wall_time_s"] = round(time.monotonic() - t0, 4)
    return g, env.trajectory


def evaluate(episodes, policies=("random", "reconciler", "flag_all", "oracle"), seed=0, record=False,
             mode="eval"):
    rows, trajs = [], {}
    for pol in policies:
        worker = None if pol == "oracle" else WorkerProcess(pol, seed)
        try:
            for ep in episodes:
                g, tr = run_episode(ep, pol, worker, mode=mode, record=record)
                g["n_truth"] = len(ep.truth["issues"])
                g["clean"] = g["n_truth"] == 0
                g["interacting"] = any(i.get("interaction_group") for i in ep.truth["issues"])
                rows.append(g)
                if record:
                    trajs[(pol, ep.episode_id)] = tr
        finally:
            if worker:
                worker.close()
    return rows, trajs


def summarize(rows):
    out = {}
    for r in rows:
        out.setdefault(r["policy"], []).append(r)
    summary = {}
    for pol, rs in out.items():
        n = len(rs)
        tp, fp, fn = sum(r["tp"] for r in rs), sum(r["fp"] for r in rs), sum(r["fn"] for r in rs)
        summary[pol] = {
            "episodes": n,
            "mean_precision": round(sum(r["precision"] for r in rs) / n, 4),
            "mean_recall": round(sum(r["recall"] for r in rs) / n, 4),
            "mean_f1": round(sum(r["f1"] for r in rs) / n, 4),
            "mean_return": round(sum(r["reward"] for r in rs) / n, 4),
            "mean_experimental_return": round(sum(r["experimental_reward"] for r in rs) / n, 4),
            "micro_tp_fp_fn": [tp, fp, fn],
            "mean_steps": round(sum(r["steps_used"] for r in rs) / n, 2),
            "mean_wall_time_s": round(sum(r["wall_time_s"] for r in rs) / n, 4),
            "invalid_submissions": sum(1 for r in rs if not r["valid"]),
            "truncated": sum(1 for r in rs if r["terminated_by"] != "submit"),
            "clean_mean_return": _mean([r["reward"] for r in rs if r["clean"]]),
            "erroneous_mean_return": _mean([r["reward"] for r in rs if not r["clean"]]),
            "missed_by_type": _count([t for r in rs for t in r.get("missed_types", [])]),
            "false_positives_by_type": _count([t for r in rs for t in r.get("fp_types", [])]),
        }
    return summary


def _mean(xs):
    return round(sum(xs) / len(xs), 4) if xs else None


def _count(xs):
    d = {}
    for x in xs:
        d[x] = d.get(x, 0) + 1
    return dict(sorted(d.items()))
