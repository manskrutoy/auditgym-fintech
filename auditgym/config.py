"""Episode configuration: presets, validation, canonical serialisation."""

import copy
import hashlib
import json
import random

from .constants import BASE_CURRENCIES, INTERACTIONS, ISSUE_TYPES

DEFAULTS = {
    "preset": "mixed",
    "base_currency": None,          # None -> sampled from BASE_CURRENCIES
    "n_customers": [6, 14],
    "n_invoices": [25, 70],         # invoices issued inside the period
    "ledger_rows": [220, 600],      # target total ledger rows (expense noise fills the gap)
    "foreign_share": 0.35,          # share of customers billed in a foreign currency
    "subsequent_days": 5,           # ledger/doc window after period end (cut-off testing)
    "errors": {t: [0, 1] for t in ISSUE_TYPES},
    "interactions": {k: 0 for k in INTERACTIONS},
    "distractors": {
        "recurring_customers": [1, 3],
        "split_payments": [1, 3],
        "multi_invoice_payments": [3, 6],
        "duplicate_payment_refunds": [0, 1],
        "advances": [0, 2],
        "unidentified_receipts": [0, 2],
        "boundary_documents": [1, 3],
    },
    "id_seed": None,                # None -> derived from episode seed
    "order_seed": None,             # None -> canonical (chronological) order
}

PRESETS = {
    "clean": {
        "errors": {t: 0 for t in ISSUE_TYPES},
        "interactions": {k: 0 for k in INTERACTIONS},
    },
    "mixed": {
        "errors": {t: [0, 2] for t in ISSUE_TYPES},
    },
    "single": {
        "errors": {t: [0, 1] for t in ISSUE_TYPES},
    },
    "all_types": {
        "errors": {t: 1 for t in ISSUE_TYPES},
    },
    "interacting": {
        "errors": {t: [0, 1] for t in ISSUE_TYPES},
        "interactions": {k: 1 for k in INTERACTIONS},
    },
    "hard": {
        "n_invoices": [55, 95],
        "ledger_rows": [900, 2000],
        "n_customers": [12, 24],
        "foreign_share": 0.5,
        "errors": {t: [1, 2] for t in ISSUE_TYPES},
        "interactions": {k: [0, 1] for k in INTERACTIONS},
    },
}

MAX_ISSUES = 12


class ConfigError(ValueError):
    pass


def _deep_merge(base, over):
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _check_range(name, v, lo, hi):
    if isinstance(v, bool):
        raise ConfigError("%s must be int or [min,max]" % name)
    if isinstance(v, int):
        v = [v, v]
    if not (isinstance(v, list) and len(v) == 2 and all(isinstance(x, int) and not isinstance(x, bool) for x in v)):
        raise ConfigError("%s must be int or [min,max]" % name)
    if not (lo <= v[0] <= v[1] <= hi):
        raise ConfigError("%s=%r outside [%d,%d]" % (name, v, lo, hi))
    return v


def normalize_config(cfg=None):
    """Return a fully specified, validated config dict (canonical form)."""
    cfg = dict(cfg or {})
    preset = cfg.get("preset", DEFAULTS["preset"])
    if preset not in PRESETS:
        raise ConfigError("unknown preset %r (known: %s)" % (preset, ", ".join(sorted(PRESETS))))
    unknown = set(cfg) - set(DEFAULTS)
    if unknown:
        raise ConfigError("unknown config keys: %s" % sorted(unknown))
    out = _deep_merge(_deep_merge(DEFAULTS, PRESETS[preset]), cfg)
    out["preset"] = preset
    if out["base_currency"] is not None and out["base_currency"] not in BASE_CURRENCIES:
        raise ConfigError("base_currency must be one of %s" % (BASE_CURRENCIES,))
    out["n_customers"] = _check_range("n_customers", out["n_customers"], 4, 40)
    out["n_invoices"] = _check_range("n_invoices", out["n_invoices"], 12, 170)
    out["ledger_rows"] = _check_range("ledger_rows", out["ledger_rows"], 150, 2000)
    out["subsequent_days"] = _check_range("subsequent_days", out["subsequent_days"], 3, 10)[0]
    fs = out["foreign_share"]
    if isinstance(fs, bool) or not isinstance(fs, (int, float)) or not (0.0 <= fs <= 1.0):
        raise ConfigError("foreign_share must be a number in [0,1]")
    out["foreign_share"] = float(fs)
    if set(out["errors"]) - set(ISSUE_TYPES):
        raise ConfigError("unknown error types: %s" % sorted(set(out["errors"]) - set(ISSUE_TYPES)))
    for t in ISSUE_TYPES:
        out["errors"][t] = _check_range("errors.%s" % t, out["errors"].get(t, 0), 0, 6)
    if set(out["interactions"]) - set(INTERACTIONS):
        raise ConfigError("unknown interactions: %s" % sorted(set(out["interactions"]) - set(INTERACTIONS)))
    for k in INTERACTIONS:
        out["interactions"][k] = _check_range("interactions.%s" % k, out["interactions"].get(k, 0), 0, 3)
    for k, v in list(out["distractors"].items()):
        if k not in DEFAULTS["distractors"]:
            raise ConfigError("unknown distractor %r" % k)
        out["distractors"][k] = _check_range("distractors.%s" % k, v, 0, 8)
    min_issues = sum(v[0] for v in out["errors"].values()) + 2 * sum(v[0] for v in out["interactions"].values())
    if min_issues > MAX_ISSUES:
        raise ConfigError("config requires at least %d issues; maximum is %d" % (min_issues, MAX_ISSUES))
    for k in ("id_seed", "order_seed"):
        v = out[k]
        if v is not None and (isinstance(v, bool) or not isinstance(v, int)):
            raise ConfigError("%s must be an int or null" % k)
    return out


def canonical_json(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def config_hash(cfg) -> str:
    return hashlib.sha256(canonical_json(cfg).encode()).hexdigest()[:16]


def sub_rng(*parts) -> random.Random:
    """Independent deterministic RNG stream derived from the given parts."""
    h = hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()
    return random.Random(int(h, 16))


def sample_range(rng: random.Random, r) -> int:
    lo, hi = r
    return rng.randint(lo, hi)
