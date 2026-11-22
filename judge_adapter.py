"""Jury adapter for AuditGym (interface from genesis-exe.com/fintech-checks.html).

Working directory: the repository root (/app in the container). Python >= 3.11, stdlib only.

    import judge_adapter as ja
    ja.generate_episode(seed, config, output_dir)          # writes all episode files into output_dir
    env = ja.make_env()
    obs, info = env.reset(seed, {"mode": "closed", "episode_dir": output_dir})   # or {"mode": "train", ...}
    obs, reward, terminated, truncated, info = env.step({"name": "list_records",
                                                         "args": {"table": "ledger", "cursor": None, "limit": 50}})
    result = ja.score_episode(output_dir, findings, inspection_steps)

Files written by generate_episode (flat layout, all in output_dir):
    manifest.json policy.json ledger.csv invoices.jsonl payments.jsonl fx.csv      (public)
    truth.json provenance.json clean_ledger.csv                                    (closed)

config for generate_episode: an AuditGym episode config (e.g. {"preset": "interacting"}), or a dict
holding it under "team_config". Keys "mode"/"episode_dir" are ignored there.

score_episode result schema:
    {"valid": bool, "tp": int|null, "fp": int|null, "fn": int|null, "precision": float|null,
     "recall": float|null, "f1": float|null, "return": float, "experimental_return": float|null,
     "inspection_steps": int, "error": str|null}
An invalid (structurally wrong) submit gives return = -1 and null metrics.
"""

import csv
import json
import os
import sys

_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from auditgym.env import AuditEnv                                   # noqa: E402
from auditgym.episode import LEDGER_COLS, _write_csv                # noqa: E402
from auditgym.generator import generate_episode as _generate       # noqa: E402
from auditgym.reward import grade                                   # noqa: E402

_ID_KEYS = ("row_id", "doc_id", "invoice_id", "payment_id", "fx_id")


def _generation_config(config):
    cfg = dict(config or {})
    if "team_config" in cfg:
        return cfg["team_config"]
    for k in ("mode", "episode_dir"):
        cfg.pop(k, None)
    return cfg or None


def generate_episode(seed: int, config: dict, output_dir: str) -> None:
    """Generate one episode (same seed + config + version => identical files)."""
    ep = _generate(int(seed), _generation_config(config))
    ep.save_flat(output_dir)
    if getattr(ep, "clean_ledger", None) is not None:
        _write_csv(os.path.join(output_dir, "clean_ledger.csv"), LEDGER_COLS, ep.clean_ledger)


def make_env():
    """Environment object with reset(seed, config) and step(action).
    reset config: {"mode": "closed", "episode_dir": dir} (policy-visible reward is 0) or
                  {"mode": "train", "episode_dir": dir} / {"mode": "train", "team_config": {...}}."""
    return AuditEnv(mode="train")


def _find(episode_dir, name):
    for p in (os.path.join(episode_dir, name), os.path.join(episode_dir, "private", name),
              os.path.join(episode_dir, "public", name)):
        if os.path.exists(p):
            return p
    return None


def _public_ids(episode_dir):
    ids, found = set(), False
    for name in ("ledger.csv", "fx.csv"):
        p = _find(episode_dir, name)
        if p:
            found = True
            with open(p, encoding="utf-8", newline="") as f:
                for row in csv.DictReader(f):
                    ids.update(v for k, v in row.items() if k in _ID_KEYS and v and v != "null")
    for name in ("invoices.jsonl", "payments.jsonl"):
        p = _find(episode_dir, name)
        if p:
            found = True
            with open(p, encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        row = json.loads(line)
                        ids.update(row[k] for k in _ID_KEYS if isinstance(row.get(k), str))
    return ids if found else None


def score_episode(episode_dir: str, findings, inspection_steps: int) -> dict:
    """Score a submission against the closed truth of episode_dir with the shared matcher and reward.
    `findings` may be the findings.json object ({"episode_id", "findings": [...]}), its JSON string,
    or the bare findings list."""
    with open(_find(episode_dir, "truth.json"), encoding="utf-8") as f:
        truth = json.load(f)
    if isinstance(truth, list):
        truth = {"issues": truth}
    truth.setdefault("issues", [])
    g = grade(findings, truth, int(inspection_steps), known_ids=_public_ids(episode_dir))
    if not g["valid"]:
        return {"valid": False, "tp": None, "fp": None, "fn": None, "precision": None, "recall": None,
                "f1": None, "return": -1.0, "experimental_return": None,
                "inspection_steps": int(inspection_steps), "error": g["error"]}
    return {"valid": True, "tp": g["tp"], "fp": g["fp"], "fn": g["fn"], "precision": g["precision"],
            "recall": g["recall"], "f1": g["f1"], "return": g["reward"],
            "experimental_return": g["experimental_reward"], "inspection_steps": int(inspection_steps),
            "error": None}
