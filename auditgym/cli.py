"""Command line: python -m auditgym <command>

  check      single official self-check (tests, reproducibility, data verification,
             baselines, paired checks, leak scan) -> reports/check_report.{json,md}
  generate   write the open train/dev episodes to episodes/<split>/<name>/
  verify     independent data verification of episodes
  evaluate   run baseline policies (isolated processes, eval mode) and print metrics
  run        record trajectories (train mode) to a JSONL file
  demo       step-by-step run of the scripted expert on one episode
"""

import argparse
import hashlib
import io
import json
import os
import platform
import sys
import time
import unittest
import zlib

from .config import canonical_json
from .constants import ENV_VERSION, ISSUE_TYPES
from .episode import Episode, relabel
from .evaluator import WorkerProcess, evaluate, run_episode, summarize
from .generator import generate_episode
from .verify import verify_episode

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASELINES = ("random", "reconciler", "flag_all", "oracle")


def load_split(name):
    with open(os.path.join(ROOT, "configs", "%s.json" % name), encoding="utf-8") as f:
        return json.load(f)["episodes"]


def episodes_for(split, from_disk=True):
    out = []
    for e in load_split(split):
        d = os.path.join(ROOT, "episodes", split, e["name"])
        if from_disk and os.path.isdir(d):
            out.append(Episode.load(d))
        else:
            out.append(generate_episode(e["seed"], e["config"]))
    return out


# ------------------------------------------------------------------------ commands
def cmd_generate(a):
    index = {"env_version": ENV_VERSION, "episodes": []}
    for split in a.split:
        for e in load_split(split):
            ep = generate_episode(e["seed"], e["config"])
            d = os.path.join(ROOT, a.out, split, e["name"])
            ep.save(d)
            index["episodes"].append({"split": split, "name": e["name"], "episode_id": ep.episode_id,
                                      "public_sha256": ep.public_hash(), "full_sha256": ep.full_hash(),
                                      "issues": len(ep.truth["issues"])})
            print("%-6s %-9s %s issues=%d rows=%d" % (split, e["name"], ep.episode_id, len(ep.truth["issues"]),
                                                     ep.manifest["counts"]["ledger_rows"]))
    with open(os.path.join(ROOT, a.out, "index.json"), "w") as f:
        json.dump(index, f, indent=2)
        f.write("\n")


def cmd_verify(a):
    bad = 0
    for split in a.split:
        for e, ep in zip(load_split(split), episodes_for(split)):
            rep = verify_episode(ep)
            print("%-14s %-9s %s %s" % (split, e["name"], "OK " if rep.ok else "FAIL", "; ".join(rep.errors[:3])))
            bad += not rep.ok
    return 1 if bad else 0


def cmd_evaluate(a):
    eps = [ep for s in a.split for ep in episodes_for(s)]
    rows, _ = evaluate(eps, a.policies, seed=a.seed)
    print(json.dumps(summarize(rows), indent=2))


def cmd_run(a):
    eps = [ep for s in a.split for ep in episodes_for(s)]
    os.makedirs(os.path.dirname(os.path.abspath(a.trajectories)), exist_ok=True)
    n = 0
    with open(a.trajectories, "w", encoding="utf-8") as f:
        for pol in a.policies:
            worker = None if pol == "oracle" else WorkerProcess(pol, a.seed)
            try:
                for ep in eps:
                    g, traj = run_episode(ep, pol, worker, mode=a.mode, record=True)
                    for t in traj:
                        t = dict(t, policy=pol)
                        f.write(json.dumps(t, sort_keys=True, ensure_ascii=False) + "\n")
                        n += 1
            finally:
                if worker:
                    worker.close()
    print("wrote %d steps to %s" % (n, a.trajectories))


def cmd_demo(a):
    from .env import AuditEnv
    from .policies.scripted import ExpertAuditor
    split, name = a.episode.split("/")
    e = [x for x in load_split(split) if x["name"] == name][0]
    ep = generate_episode(e["seed"], e["config"])
    env = AuditEnv(mode="train")
    obs, info = env.reset(episode=ep)
    m = obs["manifest"]
    print("episode %s | %s | base %s | period %s..%s (UTC%s) | rows=%d docs=%d" % (
        m["episode_id"], m["company_name"], m["base_currency"], m["period_start"], m["period_end"],
        m["timezone"], m["counts"]["ledger_rows"], m["counts"]["documents"]))
    pol = ExpertAuditor()
    pol.reset(obs)
    while True:
        act = pol.act(obs)
        obs, r, term, trunc, info = env.step(act)
        if act["action"] == "list_records":
            res = obs["result"]
            print("step %3d list_records %-8s cursor=%-14s -> %d records" % (
                obs["step"], act["table"], act["cursor"], len(res["records"])))
        else:
            print("step %3d submit: %d findings" % (obs["step"], len(act["findings"]["findings"])))
            for fnd in act["findings"]["findings"]:
                print("   - %-20s %-30s %12d %s  evidence=%s" % (fnd["type"], ",".join(fnd["affected_ids"]),
                      fnd["claimed_amount_minor"], fnd["currency"], ",".join(fnd["evidence_ids"])))
        if term or trunc:
            break
    g = info["grade"]
    print("reward=%.3f  P=%.2f R=%.2f F1=%.2f  TP=%d FP=%d FN=%d  inspection_steps=%d" % (
        g["reward"], g["precision"], g["recall"], g["f1"], g["tp"], g["fp"], g["fn"], g["inspection_steps"]))
    print("truth (closed, shown for the demo only): %s" % [(i["type"], i["affected_ids"]) for i in ep.truth["issues"]])


def cmd_serve(a):
    """Language-agnostic JSON-lines server around AuditEnv (one process = one evaluator).
    in : {"cmd":"reset","seed":1,"config":{...}} | {"cmd":"reset","split":"dev","name":"dev_01"}
         {"cmd":"step","action":{...}} | {"cmd":"close"}
    out: {"observation":..,"info":..} | {"observation":..,"reward":..,"terminated":..,"truncated":..,"info":..}"""
    from .env import AuditEnv
    env = AuditEnv(mode=a.mode)
    for line in sys.stdin:
        try:
            msg = json.loads(line)
            if msg.get("cmd") == "reset":
                if "split" in msg:
                    e = [x for x in load_split(msg["split"]) if x["name"] == msg["name"]][0]
                    obs, info = env.reset(seed=e["seed"], config=e["config"])
                else:
                    obs, info = env.reset(seed=msg.get("seed"), config=msg.get("config"))
                out = {"observation": obs, "info": info}
            elif msg.get("cmd") == "step":
                obs, r, te, tr, info = env.step(msg.get("action"))
                out = {"observation": obs, "reward": r, "terminated": te, "truncated": tr, "info": info}
            elif msg.get("cmd") == "close":
                break
            else:
                out = {"error": "unknown cmd"}
        except Exception as ex:          # never crash the server; never echo internals
            out = {"error": type(ex).__name__}
        sys.stdout.write(json.dumps(out) + "\n")
        sys.stdout.flush()


# ------------------------------------------------------------------------ check
def _run_unit_tests():
    loader = unittest.TestLoader()
    suite = loader.discover(os.path.join(ROOT, "tests"), top_level_dir=ROOT)
    buf = io.StringIO()
    res = unittest.TextTestRunner(stream=buf, verbosity=1).run(suite)
    return {"ran": res.testsRun, "failures": len(res.failures), "errors": len(res.errors),
            "ok": res.wasSuccessful(), "details": [str(t) for t, _ in res.failures + res.errors][:20]}


def _traj_hash(traj):
    return hashlib.sha256(canonical_json(traj).encode()).hexdigest()


def paired_checks(entries, n=20):
    """Per episode: (1) regenerate + replay the same actions -> identical records,
    observations and rewards; (2) relabel ids + permute order -> oracle answer maps and
    reward is unchanged; (3) generator id/order seeds -> same hidden world."""
    from .env import AuditEnv
    from .policies.scripted import ExpertAuditor
    results = []
    for e in entries[:n]:
        r = {"name": e["name"]}
        ep1 = generate_episode(e["seed"], e["config"])
        ep2 = generate_episode(e["seed"], e["config"])
        r["regenerate_identical"] = ep1.full_hash() == ep2.full_hash()

        def replay(ep, actions=None):
            env = AuditEnv(mode="train", record_trajectory=True, time_limit_s=None)
            obs, _ = env.reset(episode=ep)
            pol = ExpertAuditor()
            pol.reset(obs)
            acts = []
            i = 0
            while True:
                act = actions[i] if actions is not None else pol.act(obs)
                i += 1
                acts.append(act)
                obs, rew, te, tr, _ = env.step(act)
                if te or tr:
                    return acts, env.trajectory, env.last_grade
        acts, t1, g1 = replay(ep1)
        _, t2, g2 = replay(ep2, acts)
        r["replay_identical"] = _traj_hash(t1) == _traj_hash(t2) and g1["reward"] == g2["reward"]

        rl = relabel(ep1, seed=zlib.crc32(e["name"].encode()))
        g_or, _ = run_episode(ep1, "oracle")
        g_or2, _ = run_episode(rl, "oracle")
        _, _, g_ex2 = replay(rl)
        mapped = sorted((i["type"], sorted(rl.id_mapping.get(x, x) for x in i["affected_ids"]), i["expected_amount_minor"])
                        for i in ep1.truth["issues"])
        got = sorted((i["type"], i["affected_ids"], i["expected_amount_minor"]) for i in rl.truth["issues"])
        r["relabel_truth_maps"] = mapped == got
        r["relabel_oracle_reward_equal"] = g_or["reward"] == g_or2["reward"] == 1.0
        r["relabel_expert_reward_equal"] = abs(g_ex2["f1"] - g1["f1"]) < 1e-12
        r["relabel_verifies"] = verify_episode(rl).ok

        cfg2 = dict(e["config"], id_seed=12345 + len(results), order_seed=777 + len(results))
        ep3 = generate_episode(e["seed"], cfg2)
        sig = lambda ep: sorted((i["type"], i["expected_amount_minor"], i["currency"]) for i in ep.truth["issues"])
        g3, _ = run_episode(ep3, "oracle")
        r["id_order_seed_same_world"] = sig(ep1) == sig(ep3) and \
            ep1.manifest["counts"] == ep3.manifest["counts"] and g3["reward"] == g_or["reward"]
        r["ok"] = all(v for k, v in r.items() if k not in ("name",))
        results.append(r)
    return results


def leak_scan(path, truths):
    """Closed fields or values must never appear in recorded observations."""
    bad_keys = ['"expected_amount_minor"', '"evidence_sets"', '"issue_id"', '"mutation"', '"provenance"',
                '"seed"', "truth.json", "provenance.json", "/private/"]
    issue_ids = {i["issue_id"] for t in truths for i in t["issues"]}
    hits = []
    if not os.path.exists(path):
        return {"ok": False, "hits": ["missing %s" % path]}
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f):
            obs = json.dumps(json.loads(line)["observation"])
            for k in bad_keys:
                if k in obs:
                    hits.append("line %d contains %s" % (n + 1, k))
            for iid in issue_ids:
                if iid in obs:
                    hits.append("line %d contains issue id" % (n + 1))
    return {"ok": not hits, "hits": hits[:10]}


def cmd_check(a):
    t0 = time.time()
    report = {"env_version": ENV_VERSION, "python": platform.python_version(),
              "platform": platform.platform(), "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    ok = True

    print("[1/6] unit tests ...", flush=True)
    report["unit_tests"] = _run_unit_tests()
    ok &= report["unit_tests"]["ok"]
    print("      %(ran)d tests, failures=%(failures)d errors=%(errors)d" % report["unit_tests"])

    print("[2/6] reproducibility of committed episodes ...", flush=True)
    idx_path = os.path.join(ROOT, "episodes", "index.json")
    repro = []
    if os.path.exists(idx_path):
        with open(idx_path) as f:
            index = {(x["split"], x["name"]): x for x in json.load(f)["episodes"]}
        for split in ("train", "dev"):
            for e in load_split(split):
                ep = generate_episode(e["seed"], e["config"])
                disk = Episode.load(os.path.join(ROOT, "episodes", split, e["name"]))
                exp = index.get((split, e["name"]), {})
                repro.append({"split": split, "name": e["name"],
                              "regenerated_matches_index": ep.full_hash() == exp.get("full_sha256"),
                              "disk_matches_regenerated": disk.full_hash() == ep.full_hash()})
    report["reproducibility"] = {"ok": bool(repro) and all(r["regenerated_matches_index"] and r["disk_matches_regenerated"] for r in repro),
                                 "episodes": repro}
    ok &= report["reproducibility"]["ok"]
    print("      %d episodes, ok=%s" % (len(repro), report["reproducibility"]["ok"]))

    print("[3/6] independent data verification ...", flush=True)
    ver = []
    split_eps = {}
    for split in ("train", "dev", "local_holdout"):
        split_eps[split] = episodes_for(split)
        for e, ep in zip(load_split(split), split_eps[split]):
            rep = verify_episode(ep)
            ver.append({"split": split, "name": e["name"], "ok": rep.ok, "errors": rep.errors[:5],
                        "issues": len(ep.truth["issues"])})
    report["data_verification"] = {"ok": all(v["ok"] for v in ver), "episodes": ver}
    ok &= report["data_verification"]["ok"]
    print("      %d episodes, failures=%d" % (len(ver), sum(not v["ok"] for v in ver)))

    print("[4/6] baseline policies (separate processes, eval mode) ...", flush=True)
    base = {}
    for split in ("dev", "local_holdout"):
        rows, _ = evaluate(split_eps[split], BASELINES + ("expert",))
        base[split] = summarize(rows)
    report["baselines"] = base
    hold = base["local_holdout"]
    sanity = {
        "oracle_max_reward": hold["oracle"]["mean_return"] == 1.0,
        "flag_all_bad": hold["flag_all"]["mean_return"] <= -0.5,
        "random_bad": hold["random"]["mean_return"] < 0.0,
        "oracle_beats_reconciler": hold["oracle"]["mean_return"] > hold["reconciler"]["mean_return"],
        "no_invalid_or_truncated_oracle": hold["oracle"]["invalid_submissions"] == 0 and hold["oracle"]["truncated"] == 0,
    }
    report["baseline_sanity"] = sanity
    ok &= all(sanity.values())
    for pol, s in hold.items():
        print("      holdout %-10s F1=%.3f return=%+.3f steps=%.1f time=%.3fs" % (
            pol, s["mean_f1"], s["mean_return"], s["mean_steps"], s["mean_wall_time_s"]))

    print("[5/6] paired checks (replay, relabel+permute, id/order seeds) ...", flush=True)
    pc = paired_checks(load_split("local_holdout"), 20)
    report["paired_checks"] = {"passed": sum(r["ok"] for r in pc), "total": len(pc), "details": pc}
    ok &= all(r["ok"] for r in pc)
    print("      %d/%d passed" % (report["paired_checks"]["passed"], len(pc)))

    print("[6/6] leak scan of trajectories ...", flush=True)
    tpath = os.path.join(ROOT, "trajectories", "trajectories.jsonl")
    truths = [ep.truth for s in ("train", "dev") for ep in split_eps[s]]
    report["leak_scan"] = leak_scan(tpath, truths)
    ok &= report["leak_scan"]["ok"]
    print("      ok=%s" % report["leak_scan"]["ok"])

    report["ok"] = bool(ok)
    report["duration_s"] = round(time.time() - t0, 1)
    os.makedirs(os.path.join(ROOT, "reports"), exist_ok=True)
    with open(os.path.join(ROOT, "reports", "check_report.json"), "w") as f:
        json.dump(report, f, indent=2, default=str)
        f.write("\n")
    with open(os.path.join(ROOT, "reports", "check_report.md"), "w") as f:
        f.write(render_md(report))
    print("\nCHECK %s in %.1fs -> reports/check_report.md" % ("PASSED" if ok else "FAILED", report["duration_s"]))
    return 0 if ok else 1


def render_md(r):
    L = ["# AuditGym check report", "",
         "- env_version: `%s`, python %s, %s" % (r["env_version"], r["python"], r["platform"]),
         "- overall: **%s** (%.1fs)" % ("PASSED" if r["ok"] else "FAILED", r["duration_s"]), "",
         "| check | result |", "|---|---|",
         "| unit tests | %d run, %d failures, %d errors |" % (r["unit_tests"]["ran"], r["unit_tests"]["failures"], r["unit_tests"]["errors"]),
         "| reproducibility (train+dev regenerate == committed) | %s |" % r["reproducibility"]["ok"],
         "| data verification (%d episodes) | %d failures |" % (len(r["data_verification"]["episodes"]),
                                                            sum(not v["ok"] for v in r["data_verification"]["episodes"])),
         "| paired checks | %d/%d |" % (r["paired_checks"]["passed"], r["paired_checks"]["total"]),
         "| leak scan | %s |" % r["leak_scan"]["ok"], ""]
    for split, s in r["baselines"].items():
        L += ["## Baselines on %s (eval mode, policies in separate processes)" % split, "",
              "| policy | P | R | F1 | return | clean return | erroneous return | steps | time s | FP by type | missed by type |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]
        for pol, x in s.items():
            L.append("| %s | %.3f | %.3f | %.3f | %+.3f | %s | %s | %.1f | %.4f | %s | %s |" % (
                pol, x["mean_precision"], x["mean_recall"], x["mean_f1"], x["mean_return"],
                x["clean_mean_return"], x["erroneous_mean_return"], x["mean_steps"], x["mean_wall_time_s"],
                x["false_positives_by_type"] or "-", x["missed_by_type"] or "-"))
        L.append("")
    L += ["Precision/recall are 0 by definition when their denominator is 0 (e.g. clean books "
          "answered with no findings), so mean P/R are below 1 even for the oracle; F1 and return "
          "follow the spec (empty truth + empty answer => F1 = 1).", ""]
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m auditgym")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("check")
    s.set_defaults(fn=cmd_check)
    s = sub.add_parser("generate")
    s.add_argument("--split", nargs="+", default=["train", "dev"])
    s.add_argument("--out", default="episodes")
    s.set_defaults(fn=cmd_generate)
    s = sub.add_parser("verify")
    s.add_argument("--split", nargs="+", default=["train", "dev", "local_holdout"])
    s.set_defaults(fn=cmd_verify)
    s = sub.add_parser("evaluate")
    s.add_argument("--split", nargs="+", default=["dev"])
    s.add_argument("--policies", nargs="+", default=list(BASELINES) + ["expert"])
    s.add_argument("--seed", type=int, default=0)
    s.set_defaults(fn=cmd_evaluate)
    s = sub.add_parser("run")
    s.add_argument("--split", nargs="+", default=["train"])
    s.add_argument("--policies", nargs="+", default=["expert", "reconciler", "random", "flag_all"])
    s.add_argument("--mode", default="train", choices=["train", "eval"])
    s.add_argument("--seed", type=int, default=0)
    s.add_argument("--trajectories", default=os.path.join(ROOT, "trajectories", "trajectories.jsonl"))
    s.set_defaults(fn=cmd_run)
    s = sub.add_parser("serve")
    s.add_argument("--mode", default="eval", choices=["train", "eval"])
    s.set_defaults(fn=cmd_serve)
    s = sub.add_parser("demo")
    s.add_argument("--episode", default="dev/dev_08")
    s.set_defaults(fn=cmd_demo)
    a = ap.parse_args(argv)
    rc = a.fn(a)
    sys.exit(rc or 0)
