"""Independent data checks on a generated episode, using PUBLIC records only
(plus the closed truth being checked).  Does not import the generator.

  * schema / format of public records (ISO-8601 with offset, integer minor units,
    decimal-string rates, explicit nulls, refs to existing invoices)
  * books balance: trial balance and every document's journal lines
  * each truth issue is (a) supported by every admissible evidence set on its own,
    (b) recomputed to exactly the declared amount
  * consistency: an independent public-data detector finds exactly the declared
    issues -- nothing undeclared is discoverable, nothing declared is unprovable
"""

import re
from datetime import datetime
from decimal import Decimal

from . import money
from .constants import ACC_AR, ACC_CASH, ACC_SUSPENSE, CURRENCY_EXPONENTS, ISSUE_TYPES
from .policies.base import Books, parse_offset

RATE_RE = re.compile(r"^\d+(\.\d+)?$")


class Report:
    def __init__(self):
        self.errors = []

    def fail(self, msg):
        self.errors.append(msg)

    @property
    def ok(self):
        return not self.errors


def _ts(rep, s, where):
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            rep.fail("%s: timestamp without offset" % where)
        return dt
    except Exception:
        rep.fail("%s: bad timestamp %r" % (where, s))
        return None


def check_schema(ep, rep):
    m = ep.manifest
    for k in ("schema_version", "episode_id", "base_currency", "period_start", "period_end", "timezone",
              "counts", "rounding", "currency_exponents"):
        if k not in m:
            rep.fail("manifest missing %s" % k)
    t = ep.tables
    c = m["counts"]
    if c["ledger_rows"] != len(t["ledger"]) or c["invoices"] != len(t["invoices"]) or \
            c["payments"] != len(t["payments"]) or c["fx_rates"] != len(t["fx"]):
        rep.fail("manifest counts do not match tables")
    for cur, e in m["currency_exponents"].items():
        if CURRENCY_EXPONENTS.get(cur) != e:
            rep.fail("bad exponent for %s" % cur)
    inv_ids = set()
    for d in t["invoices"]:
        _ts(rep, d["issued_at"], d["doc_id"])
        _ts(rep, d["due_at"], d["doc_id"])
        if d["currency"] not in m["currency_exponents"]:
            rep.fail("invoice currency not declared")
        if not isinstance(d["total_minor"], int) or d["total_minor"] != sum(l["amount_minor"] for l in d["line_items"]):
            rep.fail("invoice %s total != sum of lines" % d["invoice_id"])
        for l in d["line_items"]:
            if l["amount_minor"] != l["quantity"] * l["unit_price_minor"]:
                rep.fail("invoice %s line amount mismatch" % d["invoice_id"])
        inv_ids.add(d["invoice_id"])
    for d in t["payments"]:
        _ts(rep, d["timestamp"], d["doc_id"])
        if not isinstance(d["amount_minor"], int):
            rep.fail("payment amount not int")
        if d["invoice_refs"] is not None:
            for r in d["invoice_refs"]:
                if r["invoice_id"] not in inv_ids:
                    rep.fail("payment %s refers to unknown invoice" % d["payment_id"])
            if sum(r["amount_minor"] for r in d["invoice_refs"]) != d["amount_minor"]:
                rep.fail("payment %s refs do not sum to amount" % d["payment_id"])
    for r in t["fx"]:
        if not RATE_RE.match(r["rate"]) or Decimal(r["rate"]) <= 0:
            rep.fail("bad fx rate %r" % r["rate"])
        if r["target_currency"] != m["base_currency"]:
            rep.fail("fx target is not base currency")
    keys = set()
    for r in t["ledger"]:
        _ts(rep, r["timestamp"], r["row_id"])
        if r["currency"] != m["base_currency"]:
            rep.fail("ledger row not in base currency")
        d, cr = r["debit_minor"], r["credit_minor"]
        if not (isinstance(d, int) and isinstance(cr, int)) or d < 0 or cr < 0 or (d > 0) == (cr > 0):
            rep.fail("ledger row %s must have exactly one positive side" % r["row_id"])
        if r["invoice_id"] is not None and r["invoice_id"] not in inv_ids:
            rep.fail("ledger row refers to unknown invoice")
        if r["row_id"] in keys:
            rep.fail("duplicate row_id")
        keys.add(r["row_id"])


def check_balances(ep, rep):
    led = ep.tables["ledger"]
    if sum(r["debit_minor"] for r in led) != sum(r["credit_minor"] for r in led):
        rep.fail("trial balance does not balance")
    groups = {}
    for r in led:
        if r["payment_id"]:
            k = ("pay", r["payment_id"])
        elif r["invoice_id"]:
            k = ("inv", r["invoice_id"])
        else:
            k = ("other", datetime.fromisoformat(r["timestamp"]).timestamp(), r["entity_id"])   # by instant
        d, c = groups.get(k, (0, 0))
        groups[k] = (d + r["debit_minor"], c + r["credit_minor"])
    for k, (d, c) in groups.items():
        if d != c:
            rep.fail("journal %s unbalanced" % (k,))


# ------------------------------------------------------------------------- per issue
def _idx(ep):
    docs = {d["doc_id"]: ("invoice", d) for d in ep.tables["invoices"]}
    docs.update({d["doc_id"]: ("payment", d) for d in ep.tables["payments"]})
    docs.update({d["invoice_id"]: ("invoice", d) for d in ep.tables["invoices"]})   # business-id citations
    docs.update({d["payment_id"]: ("payment", d) for d in ep.tables["payments"]})
    rows = {r["row_id"]: r for r in ep.tables["ledger"]}
    fx = {r["fx_id"]: r for r in ep.tables["fx"]}
    return docs, rows, fx


def _local(ep, ts):
    return datetime.fromisoformat(ts).astimezone(parse_offset(ep.manifest["timezone"])).date().isoformat()


def _in_period(ep, d):
    return ep.manifest["period_start"] <= d <= ep.manifest["period_end"]


def verify_issue(ep, issue, evidence, idx=None):
    """Recompute the issue from ONE evidence set.  Returns (ok, message)."""
    docs, rows, fx = idx or _idx(ep)
    m = ep.manifest
    base = m["base_currency"]
    rounding = ep.policy["fx"]["rounding"]
    E_docs = [docs[e] for e in evidence if e in docs]
    E_rows = [rows[e] for e in evidence if e in rows]
    E_fx = [fx[e] for e in evidence if e in fx]
    if len(E_docs) + len(E_rows) + len(E_fx) != len(evidence):
        return False, "evidence id not found in public records"
    t, aff, amt, tol = issue["type"], set(issue["affected_ids"]), issue["expected_amount_minor"], issue.get("amount_tolerance_minor", 0)

    if t == "duplicate_invoice":
        invs = [d for k, d in E_docs if k == "invoice"]
        if len(invs) != 2 or len(E_rows) != 2:
            return False, "need two invoice documents and two ledger rows"
        a, b = invs
        if {a["invoice_id"], b["invoice_id"]} != aff:
            return False, "affected ids are not the two invoices"
        sig = lambda d: (d["entity_id"], d["currency"], d["total_minor"],
                         [(l["description"], l["quantity"], l["unit_price_minor"]) for l in d["line_items"]])
        if sig(a) != sig(b):
            return False, "documents are not identical"
        gap = abs((datetime.fromisoformat(a["issued_at"]) - datetime.fromisoformat(b["issued_at"])).total_seconds())
        if gap > 3 * 86400:
            return False, "documents too far apart"
        if {r["invoice_id"] for r in E_rows} != aff or any(r["account"] != ACC_AR or r["debit_minor"] <= 0 for r in E_rows):
            return False, "rows are not the AR debits of both invoices"
        if abs(b["total_minor"] - amt) > tol or issue["currency"] != b["currency"]:
            return False, "amount/currency mismatch"
        return True, "ok"

    if t == "unallocated_payment":
        pays = [d for k, d in E_docs if k == "payment"]
        if len(pays) != 1 or not E_rows:
            return False, "need the payment document and its suspense row"
        p = pays[0]
        others = aff - {p["payment_id"]}
        if p["payment_id"] not in aff or len(others) != 1:
            return False, "affected ids must be payment + invoice"
        inv = others.pop()
        refs = [r for r in (p["invoice_refs"] or []) if r["invoice_id"] == inv]
        if len(refs) != 1:
            return False, "payment does not reference the invoice"
        if abs(refs[0]["amount_minor"] - amt) > tol or issue["currency"] != p["currency"]:
            return False, "amount/currency mismatch"
        if not any(r["account"] == ACC_SUSPENSE and r["payment_id"] == p["payment_id"] and r["credit_minor"] > 0 for r in E_rows):
            return False, "no suspense row for the payment"
        # every OTHER ref must be shown applied by an AR credit row inside the evidence
        applied = {r["invoice_id"] for r in E_rows if r["account"] == ACC_AR and r["credit_minor"] > 0
                   and r["payment_id"] == p["payment_id"]}
        others_refs = [r["invoice_id"] for r in (p["invoice_refs"] or []) if r["invoice_id"] != inv]
        if set(others_refs) - applied or inv in applied:
            return False, "evidence does not show which refs were applied"
        for r in ep.tables["ledger"]:
            if r["account"] == ACC_AR and r["payment_id"] == p["payment_id"] and r["invoice_id"] == inv:
                return False, "allocation IS applied in the ledger"
        return True, "ok"

    if t == "fx_misconversion":
        if len(E_docs) != 1 or len(E_rows) != 1 or len(E_fx) != 1:
            return False, "need doc + converted row + fx rate"
        kind, d = E_docs[0]
        row, rate = E_rows[0], E_fx[0]
        if kind == "invoice":
            ok_row = row["account"] == ACC_AR and row["debit_minor"] > 0 and row["invoice_id"] == d["invoice_id"]
            ts, amount, key = d["issued_at"], d["total_minor"], d["invoice_id"]
            rec = row["debit_minor"]
        else:
            ok_row = row["account"] == ACC_CASH and row["payment_id"] == d["payment_id"]
            ts, amount, key = d["timestamp"], abs(d["amount_minor"]), d["payment_id"]
            rec = row["debit_minor"] or row["credit_minor"]
        if not ok_row or aff != {key}:
            return False, "row/affected id do not belong to the document"
        ld = _local(ep, ts)
        pubs = sorted(r["date"] for r in ep.tables["fx"] if r["source_currency"] == d["currency"] and r["date"] <= ld)
        if not pubs or rate["date"] != pubs[-1] or rate["source_currency"] != d["currency"]:
            return False, "fx row is not the rate required by policy"
        exp = money.convert_minor(amount, d["currency"], base, rate["rate"], rounding)
        if abs(abs(rec - exp) - amt) > tol or issue["currency"] != base:
            return False, "recomputed difference %d != declared %d" % (abs(rec - exp), amt)
        if abs(rec - exp) == 0:
            return False, "no difference"
        return True, "ok"

    if t == "period_cutoff":
        invs = [d for k, d in E_docs if k == "invoice"]
        if len(invs) != 1 or len(E_rows) != 1:
            return False, "need invoice + AR row"
        d, row = invs[0], E_rows[0]
        if aff != {d["invoice_id"]} or row["invoice_id"] != d["invoice_id"] or row["account"] != ACC_AR or row["debit_minor"] <= 0:
            return False, "row does not belong to invoice"
        if _in_period(ep, _local(ep, d["issued_at"])) == _in_period(ep, _local(ep, row["timestamp"])):
            return False, "document and posting are in the same period"
        if abs(row["debit_minor"] - amt) > tol or issue["currency"] != base:
            return False, "amount/currency mismatch"
        return True, "ok"
    return False, "unknown type"


def check_clean_ledger(ep, rep):
    """Equalities of the books BEFORE error injection (closed clean_ledger.csv) and that
    the recorded books differ from them only on rows tied to declared issues."""
    cl = getattr(ep, "clean_ledger", None)
    if cl is None:
        return
    if sum(r["debit_minor"] for r in cl) != sum(r["credit_minor"] for r in cl):
        rep.fail("clean books: trial balance does not balance")
    base = ep.manifest["base_currency"]
    rnd = ep.policy["fx"]["rounding"]
    fx = {}
    for r in ep.tables["fx"]:
        fx.setdefault(r["source_currency"], []).append((r["date"], r["rate"]))
    for v in fx.values():
        v.sort()

    def conv(amount, cur, d):
        if cur == base:
            return amount
        rate = [x for x in fx.get(cur, []) if x[0] <= d][-1][1]
        return money.convert_minor(amount, cur, base, rate, rnd)

    dup_ids = {i for iss in ep.truth["issues"] if iss["type"] == "duplicate_invoice" for i in iss["affected_ids"]}
    ar_debit, ar_credit, cash = {}, set(), {}
    for r in cl:
        if r["account"] == ACC_AR and r["debit_minor"] > 0:
            ar_debit.setdefault(r["invoice_id"], []).append(r)
        if r["account"] == ACC_AR and r["credit_minor"] > 0:
            ar_credit.add((r["payment_id"], r["invoice_id"]))
        if r["account"] == ACC_CASH and r["payment_id"]:
            cash[r["payment_id"]] = r
    n_inv_clean = 0
    for d in ep.tables["invoices"]:
        rows = ar_debit.get(d["invoice_id"], [])
        if not rows:
            if d["invoice_id"] in dup_ids:      # the bogus duplicate does not exist in clean books
                continue
            rep.fail("clean books: invoice %s not posted" % d["invoice_id"])
            continue
        n_inv_clean += 1
        if len(rows) != 1:
            rep.fail("clean books: invoice posted twice")
        ld = _local(ep, d["issued_at"])
        if rows[0]["debit_minor"] != conv(d["total_minor"], d["currency"], ld):
            rep.fail("clean books: invoice %s not at policy rate" % d["invoice_id"])
        if ld >= ep.manifest["period_start"] and _local(ep, rows[0]["timestamp"]) != ld:
            rep.fail("clean books: invoice %s posted on another date" % d["invoice_id"])
    if n_inv_clean != len(ep.tables["invoices"]) - sum(1 for iss in ep.truth["issues"] if iss["type"] == "duplicate_invoice"):
        rep.fail("clean books: unexpected number of posted invoices")
    for p in ep.tables["payments"]:
        c = cash.get(p["payment_id"])
        if c is None or (c["debit_minor"] or c["credit_minor"]) != conv(abs(p["amount_minor"]), p["currency"], _local(ep, p["timestamp"])):
            rep.fail("clean books: payment %s cash not at policy rate" % p["payment_id"])
        for ref in p["invoice_refs"] or []:
            if (p["payment_id"], ref["invoice_id"]) not in ar_credit:
                rep.fail("clean books: allocation not applied")
    # recorded vs clean: differences only on declared documents (and payments settling them)
    affected = {i for iss in ep.truth["issues"] for i in iss["affected_ids"]}
    for p in ep.tables["payments"]:
        if any(r["invoice_id"] in affected for r in p["invoice_refs"] or []):
            affected.add(p["payment_id"])
    key = lambda r: (r["row_id"], r["timestamp"], r["account"], r["debit_minor"], r["credit_minor"])
    a = {key(r): r for r in cl}
    b = {key(r): r for r in ep.tables["ledger"]}
    for k in set(a) ^ set(b):
        r = a.get(k) or b.get(k)
        if not ({r["invoice_id"], r["payment_id"]} & affected):
            rep.fail("recorded books differ from clean books on an undeclared row %s" % r["row_id"])


def detect_public(ep):
    """Independent detector over public data (same rules an expert auditor applies)."""
    from .policies.base import Reader
    from .policies.scripted import ExpertAuditor
    obs = {"episode_id": ep.episode_id, "manifest": ep.manifest, "policy": ep.policy}
    r = Reader(obs)
    r.data = {k: ep.tables[k] for k in ("invoices", "payments", "fx", "ledger")}
    return ExpertAuditor().analyse(Books(r))


def verify_episode(ep, consistency=True):
    rep = Report()
    check_schema(ep, rep)
    check_balances(ep, rep)
    if ep.truth is None:
        rep.fail("no truth")
        return rep
    if ep.truth["episode_id"] != ep.episode_id:
        rep.fail("truth episode_id mismatch")
    check_clean_ledger(ep, rep)
    idx = _idx(ep)
    seen = set()
    for iss in ep.truth["issues"]:
        if iss["type"] not in ISSUE_TYPES:
            rep.fail("unknown issue type")
        key = (iss["type"], tuple(iss["affected_ids"]))
        if key in seen:
            rep.fail("two truth issues with identical type+affected ids")
        seen.add(key)
        if not iss["evidence_sets"]:
            rep.fail("%s: no evidence set" % iss["issue_id"])
        for s in iss["evidence_sets"]:
            ok, msg = verify_issue(ep, iss, s, idx)
            if not ok:
                rep.fail("%s (%s): %s" % (iss["issue_id"], iss["type"], msg))
    if consistency:
        found = {(f["type"], tuple(sorted(f["affected_ids"])), f["claimed_amount_minor"]) for f in detect_public(ep)}
        declared = {(i["type"], tuple(i["affected_ids"]), i["expected_amount_minor"]) for i in ep.truth["issues"]}
        if found != declared:
            rep.fail("detector/truth mismatch: undeclared=%s unproven=%s" % (sorted(found - declared)[:3], sorted(declared - found)[:3]))
    return rep
