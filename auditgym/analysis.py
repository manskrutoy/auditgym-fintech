"""Measured failure analysis: attribute every false positive / false negative of a policy
to the concrete trap that caused it (evaluator-side; uses truth and provenance)."""

from datetime import datetime

from .matcher import SchemaError, compatible, validate_submission
from .policies.base import parse_offset


def _local(ep, ts):
    return datetime.fromisoformat(ts).astimezone(parse_offset(ep.manifest["timezone"])).date().isoformat()


def _in(ep, d):
    return ep.manifest["period_start"] <= d <= ep.manifest["period_end"]


def _published(ep, cur, d):
    ds = [r["date"] for r in ep.tables["fx"] if r["source_currency"] == cur and r["date"] <= d]
    return ds[-1] if ds else None


def fp_cause(ep, f, idx):
    inv, pay, tags = idx
    t = f["type"]
    aff = set(f["affected"])
    # right document(s) but something else wrong
    for iss in ep.truth["issues"]:
        if set(iss["affected_ids"]) == aff:
            if iss["type"] != t:
                return "right documents, wrong type"
            if f["currency"] != iss["currency"]:
                return "right issue, wrong currency"
            if abs(f["amount"] - iss["expected_amount_minor"]) > iss.get("amount_tolerance_minor", 0):
                return "right issue, wrong amount"
            return "right issue, incomplete evidence"
        if aff & set(iss["affected_ids"]) and iss["type"] == t:
            return "partially right ids (guessed/incomplete affected_ids)"
    doc_tags = set()
    for x in aff:
        doc_tags.update(tags.get(x, []))
    if t == "duplicate_invoice":
        docs = [inv[x] for x in aff if x in inv]
        if "recurring" in doc_tags or "repeated_amount" in doc_tags:
            return "trap: legitimate recurring / repeated amount"
        if len(docs) == 2 and docs[0]["line_items"] != docs[1]["line_items"]:
            return "trap: same customer and amount, different line items"
        return "duplicate claim without identical documents"
    if t == "fx_misconversion":
        d = inv.get(next(iter(aff)), None) or pay.get(next(iter(aff)), None)
        if d is None:
            return "unknown document"
        ts = d.get("issued_at") or d.get("timestamp")
        printed, local = ts[:10], _local(ep, ts)
        if printed != local:
            return "trap: printed/UTC date differs from company-local date"
        if _published(ep, d["currency"], printed) != printed:
            return "trap: no rate that day (weekend/holiday) -> previous business day"
        return "fx claim on a correctly converted document"
    if t == "period_cutoff":
        d = inv.get(next(iter(aff)), None)
        if d is not None:
            if "boundary" in doc_tags or _in(ep, d["issued_at"][:10]) != _in(ep, _local(ep, d["issued_at"])):
                return "trap: period boundary in another time zone"
        return "cut-off claim on a correctly dated posting"
    if t == "unallocated_payment":
        if doc_tags & {"advance", "unidentified", "dup_payment", "refund"}:
            return "trap: legitimate unapplied receipt / advance / refund"
        return "allocation claim on an applied payment"
    return "other"


def fn_cause(ep, iss):
    mut = {m["issue_id"]: m for m in ep.provenance.get("mutations", [])}.get(iss["issue_id"], {})
    parts = [iss["type"]]
    for k in ("variant", "wrong_date_rule", "document"):
        if k in mut:
            parts.append("%s=%s" % (k, mut[k]))
    if iss.get("interaction_group"):
        parts.append("interaction=%s" % iss["interaction_group"])
    return " | ".join(parts)


def analyse(episodes, rows):
    """rows: evaluator grades (with 'submission').  Returns {policy: {...}}."""
    by_id = {ep.episode_id: ep for ep in episodes}
    out = {}
    for g in rows:
        ep = by_id.get(g["episode_id"])
        if ep is None:
            continue
        pol = out.setdefault(g["policy"], {"fp": {}, "fn": {}, "invalid": 0, "truncated": 0, "examples": {}})
        if not g["valid"]:
            pol["invalid"] += 1
        if g["terminated_by"] != "submit":
            pol["truncated"] += 1
        inv = {d["invoice_id"]: d for d in ep.tables["invoices"]}
        pay = {d["payment_id"]: d for d in ep.tables["payments"]}
        idx = (inv, pay, ep.provenance.get("document_tags", {}))
        findings = []
        if g.get("submission") and g["valid"]:
            try:
                findings = validate_submission(g["submission"], ep.episode_id)
            except SchemaError:
                findings = []
        for i in g.get("false_positive_findings", []):
            c = fp_cause(ep, findings[i], idx)
            pol["fp"][c] = pol["fp"].get(c, 0) + 1
            pol["examples"].setdefault(c, "%s: %s %s" % (ep.episode_id, findings[i]["type"], sorted(findings[i]["affected"])))
        missed = set(g.get("missed_issue_ids", []))
        for iss in ep.truth["issues"]:
            if iss["issue_id"] in missed:
                c = fn_cause(ep, iss)
                pol["fn"][c] = pol["fn"].get(c, 0) + 1
    for p in out.values():
        p["fp"] = dict(sorted(p["fp"].items(), key=lambda kv: -kv[1]))
        p["fn"] = dict(sorted(p["fn"].items(), key=lambda kv: -kv[1]))
    return out


def render(analysis, title):
    L = ["# Measured failure analysis — %s" % title, "",
         "Every false positive and false negative of each baseline is attributed to the concrete cause "
         "(evaluator-side, using truth, provenance mutations and per-document distractor tags).", ""]
    for pol, a in analysis.items():
        L += ["## %s" % pol, ""]
        if not a["fp"] and not a["fn"]:
            L += ["No false positives, no misses.", ""]
            continue
        if a["fp"]:
            L += ["| false positive cause | count | example |", "|---|---|---|"]
            for c, n in a["fp"].items():
                L.append("| %s | %d | `%s` |" % (c, n, a["examples"].get(c, "")))
            L.append("")
        if a["fn"]:
            L += ["| missed issue (type, injected variant) | count |", "|---|---|"]
            for c, n in a["fn"].items():
                L.append("| %s | %d |" % (c, n))
            L.append("")
        if a["invalid"] or a["truncated"]:
            L += ["invalid submissions: %d, truncated episodes: %d" % (a["invalid"], a["truncated"]), ""]
    return "\n".join(L) + "\n"
