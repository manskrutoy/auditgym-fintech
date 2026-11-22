"""Policy worker process.  The evaluator talks to it over stdin/stdout JSON lines;
the worker sees only observations (never truth, seeds, paths or grades).

    python -m auditgym.worker --policy reconciler --seed 0
"""

import argparse
import json
import sys

from .policies.scripted import POLICIES


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--policy", required=True, choices=sorted(POLICIES))
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args(argv)
    cls = POLICIES[a.policy]
    pol = cls(seed=a.seed) if a.policy == "random" else cls()
    out = sys.stdout
    for line in sys.stdin:
        msg = json.loads(line)
        cmd = msg.get("cmd")
        if cmd == "reset":
            pol.reset(msg["obs"])
            out.write(json.dumps({"ok": True}) + "\n")
        elif cmd == "act":
            try:
                action = pol.act(msg["obs"])
            except Exception as e:                       # a crashing policy just sends garbage
                action = {"action": "__policy_error__", "detail": type(e).__name__}
            out.write(json.dumps({"action": action}) + "\n")
        elif cmd == "close":
            break
        out.flush()


if __name__ == "__main__":
    main()
