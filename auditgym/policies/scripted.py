"""Baseline policies: random explorer, simple reconciler, flag-all attack, oracle, expert."""

import hashlib
import random

from .base import Books, Policy, Reader, finding


def _seeded(seed, episode_id):
    h = hashlib.sha256(("%s|%s" % (seed, episode_id)).encode()).hexdigest()
    return random.Random(int(h, 16))


# --------------------------------------------------------------------------- 1. random explorer
class RandomExplorer(Policy):
    """Random tool calls with a fixed seed, then a random (mostly wrong) answer."""
    name = "random"

    def __init__(self, seed=0):
        self.seed = seed

    def reset(self, obs):
        self.rng = _seeded(self.seed, obs["episode_id"])
        self.eid = obs["episode_id"]
        self.budget = self.rng.randint(3, 30)
        self.seen = []          # (kind, record)
        self.cursors = {}
        self.t = 0

    def act(self, obs):
        res = obs.get("result") or {}
        for r in res.get("records", []):
            self.seen.append(r)
        if "record" in res:
            self.seen.append(res["record"])
        if "next_cursor" in res and res.get("next_cursor"):
            self.cursors[res["table"]] = res["next_cursor"]
        self.t += 1
        if self.t > self.budget or obs.get("remaining_steps", 0) <= 1:
            return self._submit()
        rng = self.rng
        k = rng.random()
        if k < 0.55 or not self.seen:
            t = rng.choice(["ledger", "invoices", "payments", "fx"])
            return {"action": "list_records", "table": t,
                    "cursor": self.cursors.get(t) if rng.random() < 0.5 else None, "limit": rng.randint(1, 50)}
        rec = rng.choice(self.seen)
        if k < 0.75 and "doc_id" in rec:
            return {"action": "get_document", "doc_id": rec["doc_id"]}
        if k < 0.9:
            return {"action": "calculator", "expression": "%d + %d" % (rng.randint(0, 999), rng.randint(0, 999))}
        return {"action": "get_record", "table": "ledger", "id": rng.choice(["ROW-00000000", rec.get("row_id") or "x"])}

    def _submit(self):
        rng = self.rng
        fs = []
        if self.seen and rng.random() < 0.6:
            ids = [v for r in self.seen for k, v in r.items() if k.endswith("_id") and isinstance(v, str)]
            for _ in range(rng.randint(1, 3)):
                t = rng.choice(["duplicate_invoice", "unallocated_payment", "fx_misconversion", "period_cutoff"])
                fs.append(finding(t, [rng.choice(ids)], rng.randint(1, 100000),
                                  rng.choice(["USD", "EUR", "KZT"]), rng.sample(ids, min(3, len(ids))), "random guess"))
        return {"action": "submit", "findings": {"episode_id": self.eid, "findings": fs}}


# --------------------------------------------------------------------------- reading helper
class _ReadingPolicy(Policy):
    reserve = 1

    def reset(self, obs):
        self.reader = Reader(obs, reserve=self.reserve)
        self.eid = obs["episode_id"]

    def act(self, obs):
        self.reader.feed(obs)
        a = self.reader.next_action(obs.get("remaining_steps", 0))
        if a is not None:
            return a
        books = Books(self.reader)
        return {"action": "submit", "findings": {"episode_id": self.eid, "findings": self.analyse(books)[:30]}}

    def analyse(self, books):
        raise NotImplementedError


# --------------------------------------------------------------------------- 2. simple reconciler
class SimpleReconciler(_ReadingPolicy):
    """Typical naive reconciliation script: reads everything, then applies simple rules.
    Deliberately naive: equal (customer, amount) => duplicate; UTC calendar dates."""
    name = "reconciler"

    def analyse(self, b):
        out = []
        groups = {}
        for inv in b.invoices:
            groups.setdefault((inv["entity_id"], inv["currency"], inv["total_minor"]), []).append(inv)
        for g in groups.values():
            if len(g) >= 2:
                a, c = g[0], g[1]
                ev = [a["doc_id"], c["doc_id"]] + [r["row_id"] for r in b.ar_debit.get(a["invoice_id"], [])[:1]
                                                   + b.ar_debit.get(c["invoice_id"], [])[:1]]
                out.append(finding("duplicate_invoice", [a["invoice_id"], c["invoice_id"]], c["total_minor"],
                                   c["currency"], ev, "same customer and amount"))
        for p in b.payments:
            for ref in p["invoice_refs"] or []:
                if (p["payment_id"], ref["invoice_id"]) not in b.ar_credit:
                    ev = [p["doc_id"]] + [r["row_id"] for r in b.suspense.get(p["payment_id"], [])]
                    out.append(finding("unallocated_payment", [p["payment_id"], ref["invoice_id"]],
                                       ref["amount_minor"], p["currency"], ev, "ref not applied in ledger"))
        for inv in b.invoices:
            rows = b.ar_debit.get(inv["invoice_id"], [])
            if inv["currency"] == b.base or not rows:
                continue
            utc_day = inv["issued_at"][:10]                         # naive: printed date
            exp, fid = b.to_base(inv["total_minor"], inv["currency"], utc_day)
            if exp is not None and abs(rows[0]["debit_minor"] - exp) > 1:
                out.append(finding("fx_misconversion", [inv["invoice_id"]], abs(rows[0]["debit_minor"] - exp),
                                   b.base, [inv["doc_id"], rows[0]["row_id"], fid], "rate mismatch"))
        for inv in b.invoices:
            rows = b.ar_debit.get(inv["invoice_id"], [])
            if not rows:
                continue
            doc_in = b.in_period(inv["issued_at"][:10])
            row_in = b.in_period(rows[0]["timestamp"][:10])
            if inv["issued_at"][:10] >= b.pstart and doc_in != row_in:
                out.append(finding("period_cutoff", [inv["invoice_id"]], rows[0]["debit_minor"], b.base,
                                   [inv["doc_id"], rows[0]["row_id"]], "posted in other period"))
        return out


# --------------------------------------------------------------------------- 3. flag-all attack
class FlagAll(_ReadingPolicy):
    """Attack: accuse as many records as the limits allow, with every type."""
    name = "flag_all"

    def reset(self, obs):
        super().reset(obs)
        self.reader.queue = ["invoices", "payments"]

    def analyse(self, b):
        out = []
        types = ["duplicate_invoice", "fx_misconversion", "period_cutoff"]
        pay = list(b.payments)
        i = 0
        for inv in b.invoices:
            for t in types:
                out.append(finding(t, [inv["invoice_id"]], inv["total_minor"], inv["currency"],
                                   [inv["doc_id"]] + [r["doc_id"] for r in b.invoices[i:i + 9]], "flag everything"))
            if pay:
                p = pay[i % len(pay)]
                refs = p["invoice_refs"] or [{"invoice_id": inv["invoice_id"], "amount_minor": p["amount_minor"]}]
                out.append(finding("unallocated_payment", [p["payment_id"], refs[0]["invoice_id"]],
                                   refs[0]["amount_minor"], p["currency"], [p["doc_id"], inv["doc_id"]], "flag"))
            i += 1
            if len(out) >= 30:
                break
        return out[:30]


# --------------------------------------------------------------------------- 4. oracle
class Oracle(Policy):
    """Evaluator-only policy: reads the CLOSED truth and submits it with evidence.
    Measures the maximum attainable reward, not agent capability.  Never run this
    policy in an agent process."""
    name = "oracle"

    def __init__(self, truth):
        self.truth = truth

    def reset(self, obs):
        self.eid = obs["episode_id"]

    def act(self, obs):
        fs = [finding(i["type"], i["affected_ids"], i["expected_amount_minor"], i["currency"],
                      i["evidence_sets"][0], "oracle") for i in self.truth["issues"]]
        eid = obs.get("episode_id") or self.eid
        return {"action": "submit", "findings": {"episode_id": eid, "findings": fs}}


# --------------------------------------------------------------------------- 5. expert (demo)
class ExpertAuditor(_ReadingPolicy):
    """Scripted demo agent that applies the published policy correctly from public records
    only (local calendar dates, line-item comparison, FX publication rule).  Shows that the
    tasks are solvable within the step budget without access to the truth."""
    name = "expert"

    def analyse(self, b):
        out = []
        # duplicates: same customer, currency, identical line items, issued within 3 days
        groups = {}
        for inv in b.invoices:
            sig = (inv["entity_id"], inv["currency"], inv["total_minor"],
                   tuple((l["description"], l["quantity"], l["unit_price_minor"]) for l in inv["line_items"]))
            groups.setdefault(sig, []).append(inv)
        for g in groups.values():
            g.sort(key=lambda i: i["issued_at"])
            for a, c in zip(g, g[1:]):
                from datetime import datetime
                gap = abs((datetime.fromisoformat(c["issued_at"]) - datetime.fromisoformat(a["issued_at"])).total_seconds())
                if gap <= 3 * 86400 and b.ar_debit.get(a["invoice_id"]) and b.ar_debit.get(c["invoice_id"]):
                    ev = [a["doc_id"], c["doc_id"], b.ar_debit[a["invoice_id"]][0]["row_id"],
                          b.ar_debit[c["invoice_id"]][0]["row_id"]]
                    out.append(finding("duplicate_invoice", [a["invoice_id"], c["invoice_id"]], c["total_minor"],
                                       c["currency"], ev, "identical line items, same customer, both posted"))
        # allocations named in remittance but not applied in the ledger
        for p in b.payments:
            for ref in p["invoice_refs"] or []:
                if (p["payment_id"], ref["invoice_id"]) not in b.ar_credit and b.suspense.get(p["payment_id"]):
                    ev = [p["doc_id"]] + [r["row_id"] for r in b.suspense[p["payment_id"]]]
                    out.append(finding("unallocated_payment", [p["payment_id"], ref["invoice_id"]],
                                       ref["amount_minor"], p["currency"], ev,
                                       "remittance allocates to invoice; ledger parked it in 1190"))
        # FX: recompute with the policy rate date (local calendar date, latest published)
        for inv in b.invoices:
            rows = b.ar_debit.get(inv["invoice_id"], [])
            if inv["currency"] == b.base or len(rows) != 1:
                continue
            exp, fid = b.to_base(inv["total_minor"], inv["currency"], b.local_date(inv["issued_at"]))
            if exp is not None and abs(rows[0]["debit_minor"] - exp) >= 1:
                out.append(finding("fx_misconversion", [inv["invoice_id"]], abs(rows[0]["debit_minor"] - exp),
                                   b.base, [inv["doc_id"], rows[0]["row_id"], fid], "AR debit not at policy rate"))
        for p in b.payments:
            rows = b.cash.get(p["payment_id"], [])
            if p["currency"] == b.base or len(rows) != 1:
                continue
            rec = rows[0]["debit_minor"] or rows[0]["credit_minor"]
            exp, fid = b.to_base(abs(p["amount_minor"]), p["currency"], b.local_date(p["timestamp"]))
            if exp is not None and abs(rec - exp) >= 1:
                out.append(finding("fx_misconversion", [p["payment_id"]], abs(rec - exp), b.base,
                                   [p["doc_id"], rows[0]["row_id"], fid], "cash row not at policy rate"))
        # cut-off: document local date vs posting local date, period membership differs
        for inv in b.invoices:
            rows = b.ar_debit.get(inv["invoice_id"], [])
            if len(rows) != 1:
                continue
            dd = b.local_date(inv["issued_at"])
            if dd < b.pstart:
                continue                                       # opening balance
            if b.in_period(dd) != b.in_period(b.local_date(rows[0]["timestamp"])):
                out.append(finding("period_cutoff", [inv["invoice_id"]], rows[0]["debit_minor"], b.base,
                                   [inv["doc_id"], rows[0]["row_id"]], "posted outside the document's period"))
        return out


POLICIES = {
    "random": RandomExplorer,
    "reconciler": SimpleReconciler,
    "flag_all": FlagAll,
    "expert": ExpertAuditor,
}
