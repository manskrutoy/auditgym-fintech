"""Episode container: public records, closed truth/provenance, save/load, relabelling."""

import csv
import io
import json
import os
import random
from typing import Dict, List

from .config import canonical_json

LEDGER_COLS = ["row_id", "timestamp", "account", "debit_minor", "credit_minor", "currency",
               "entity_id", "invoice_id", "payment_id"]
FX_COLS = ["date", "source_currency", "target_currency", "rate", "fx_id"]   # fx_id derived: FX-{date}-{src}-{dst}
INT_COLS = {"debit_minor", "credit_minor"}


class Episode:
    """One company, one reporting period."""

    def __init__(self, manifest, policy, tables, truth, provenance):
        self.manifest = manifest
        self.policy = policy
        self.tables: Dict[str, List[dict]] = tables      # ledger, invoices, payments, fx
        self.truth = truth
        self.provenance = provenance

    @property
    def episode_id(self) -> str:
        return self.manifest["episode_id"]

    # ------------------------------------------------------------------ hashing
    def public_hash(self) -> str:
        import hashlib
        payload = canonical_json({"manifest": self.manifest, "policy": self.policy, "tables": self.tables})
        return hashlib.sha256(payload.encode()).hexdigest()

    def full_hash(self) -> str:
        import hashlib
        payload = canonical_json({"public": self.public_hash(), "truth": self.truth})
        return hashlib.sha256(payload.encode()).hexdigest()

    # ------------------------------------------------------------------ persistence
    def save(self, path: str):
        pub = os.path.join(path, "public")
        priv = os.path.join(path, "private")
        os.makedirs(pub, exist_ok=True)
        os.makedirs(priv, exist_ok=True)
        _write_json(os.path.join(pub, "manifest.json"), self.manifest)
        _write_json(os.path.join(pub, "policy.json"), self.policy)
        _write_csv(os.path.join(pub, "ledger.csv"), LEDGER_COLS, self.tables["ledger"])
        _write_csv(os.path.join(pub, "fx.csv"), FX_COLS, self.tables["fx"])
        _write_jsonl(os.path.join(pub, "invoices.jsonl"), self.tables["invoices"])
        _write_jsonl(os.path.join(pub, "payments.jsonl"), self.tables["payments"])
        _write_json(os.path.join(priv, "truth.json"), self.truth)
        _write_json(os.path.join(priv, "provenance.json"), self.provenance)
        if getattr(self, "clean_ledger", None) is not None:
            # books before error injection (same row_ids where the line still exists)
            _write_csv(os.path.join(priv, "clean_ledger.csv"), LEDGER_COLS, self.clean_ledger)

    @classmethod
    def load(cls, path: str, with_private: bool = True) -> "Episode":
        pub = os.path.join(path, "public")
        priv = os.path.join(path, "private")
        manifest = _read_json(os.path.join(pub, "manifest.json"))
        policy = _read_json(os.path.join(pub, "policy.json"))
        tables = {
            "ledger": _read_csv(os.path.join(pub, "ledger.csv")),
            "fx": _read_csv(os.path.join(pub, "fx.csv")),
            "invoices": _read_jsonl(os.path.join(pub, "invoices.jsonl")),
            "payments": _read_jsonl(os.path.join(pub, "payments.jsonl")),
        }
        truth = provenance = None
        if with_private:
            truth = _read_json(os.path.join(priv, "truth.json"))
            provenance = _read_json(os.path.join(priv, "provenance.json"))
        ep = cls(manifest, policy, tables, truth, provenance)
        cl = os.path.join(priv, "clean_ledger.csv")
        if with_private and os.path.exists(cl):
            ep.clean_ledger = _read_csv(cl)
        return ep


# ---------------------------------------------------------------------- file helpers
def _write_json(path, obj):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, indent=2, sort_keys=True, ensure_ascii=False)
        f.write("\n")


def _read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _write_jsonl(path, rows):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, sort_keys=True, ensure_ascii=False, separators=(",", ":")))
            f.write("\n")


def _read_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _cell(v):
    return "null" if v is None else str(v)


def _write_csv(path, cols, rows):
    buf = io.StringIO()
    wr = csv.writer(buf, lineterminator="\n")
    wr.writerow(cols)
    for r in rows:
        wr.writerow([_cell(r[c]) for c in cols])
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(buf.getvalue())


def _read_csv(path):
    out = []
    with open(path, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            row = {}
            for k, v in r.items():
                if v == "null":
                    row[k] = None
                elif k in INT_COLS:
                    row[k] = int(v)
                else:
                    row[k] = v
            out.append(row)
    return out


# ---------------------------------------------------------------------- relabelling
ID_FIELDS_LEDGER = ("row_id", "entity_id", "invoice_id", "payment_id")


def relabel(ep: Episode, seed: int, shuffle: bool = True) -> "Episode":
    """Harmless transformation used by paired checks: rename every identifier with a
    fresh random bijection and permute record order.  Truth is mapped consistently.
    The FX table key (date-currency) is not an opaque identifier and is kept."""
    rng = random.Random(seed)
    mapping = {}
    used = set()

    def m(x):
        if x is None:
            return None
        if x not in mapping:
            prefix = x.split("-")[0]
            while True:
                new = "%s-%s" % (prefix, "".join(rng.choice("0123456789ABCDEFGHJKMNPQRSTVWXYZ") for _ in range(9)))
                if new not in used:
                    break
            used.add(new)
            mapping[x] = new
        return mapping[x]

    t = ep.tables
    ledger = [dict(r, **{f: m(r[f]) for f in ID_FIELDS_LEDGER}) for r in t["ledger"]]
    invoices = []
    for d in t["invoices"]:
        invoices.append(dict(d, doc_id=m(d["doc_id"]), invoice_id=m(d["invoice_id"]), entity_id=m(d["entity_id"])))
    payments = []
    for d in t["payments"]:
        refs = None if d["invoice_refs"] is None else [
            {"invoice_id": m(r["invoice_id"]), "amount_minor": r["amount_minor"]} for r in d["invoice_refs"]]
        payments.append(dict(d, doc_id=m(d["doc_id"]), payment_id=m(d["payment_id"]), invoice_refs=refs))
    fx = [dict(r) for r in t["fx"]]
    if shuffle:
        for lst in (ledger, invoices, payments, fx):
            rng.shuffle(lst)
    truth = None
    if ep.truth is not None:
        truth = json.loads(json.dumps(ep.truth))
        for iss in truth["issues"]:
            iss["affected_ids"] = sorted(m(x) for x in iss["affected_ids"])
            iss["evidence_sets"] = [sorted(x if x.startswith("FX-") else m(x) for x in s) for s in iss["evidence_sets"]]
    manifest = json.loads(json.dumps(ep.manifest))
    prov = {"relabel_of": ep.episode_id, "relabel_seed": seed, "mapping_size": len(mapping)}
    new = Episode(manifest, ep.policy, {"ledger": ledger, "invoices": invoices, "payments": payments, "fx": fx},
                  truth, prov)
    new.id_mapping = mapping
    return new


def reexpress_timestamps(ep: Episode, seed: int) -> "Episode":
    """Harmless transformation: print every timestamp (documents AND ledger) in a random
    UTC offset.  Instants do not change, so truth must stay valid and answers unchanged."""
    from datetime import datetime, timedelta, timezone
    from .constants import DOC_OFFSETS
    rng = random.Random(seed)

    def rx(s):
        off = rng.choice(DOC_OFFSETS)
        return datetime.fromisoformat(s).astimezone(timezone(timedelta(minutes=off))).isoformat(timespec="seconds")

    t = ep.tables
    ledger = [dict(r, timestamp=rx(r["timestamp"])) for r in t["ledger"]]
    invoices = [dict(d, issued_at=rx(d["issued_at"]), due_at=rx(d["due_at"])) for d in t["invoices"]]
    payments = [dict(d, timestamp=rx(d["timestamp"])) for d in t["payments"]]
    new = Episode(json.loads(json.dumps(ep.manifest)), ep.policy,
                  {"ledger": ledger, "invoices": invoices, "payments": payments, "fx": [dict(r) for r in t["fx"]]},
                  json.loads(json.dumps(ep.truth)) if ep.truth is not None else None,
                  {"reexpressed_from": ep.episode_id, "seed": seed})
    new.id_mapping = {}
    return new
