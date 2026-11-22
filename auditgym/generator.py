"""Episode generator: hidden history -> errors with causal record -> public records + truth."""

import copy
import hashlib
from datetime import timedelta

from . import money
from .config import canonical_json, config_hash, normalize_config, sample_range, sub_rng
from .constants import (
    ACC_AR, ACC_CASH, CHART_OF_ACCOUNTS, CURRENCY_EXPONENTS, ENV_VERSION, INTERACTIONS,
    ISSUE_TYPES, SCHEMA_VERSION,
)
from .config import MAX_ISSUES
from .episode import Episode
from .injectors import InjectionError, Injector
from .posting import PostingError, find_line, post_ledger
from .timeutil import iso, offset_str, tz
from .world import Builder

FX_HISTORY_DAYS = 50


class GenerationError(RuntimeError):
    pass


class InvariantError(RuntimeError):
    pass


def episode_id_for(seed, cfg) -> str:
    h = hashlib.sha256(("%s|%s|%s" % (ENV_VERSION, seed, config_hash(cfg))).encode()).hexdigest()
    return "ep-" + h[:12]


def world_config(cfg):
    """Part of the config that shapes the hidden world (ids/order are presentation only)."""
    c = dict(cfg)
    c.pop("id_seed", None)
    c.pop("order_seed", None)
    return c


def generate_episode(seed: int, config=None) -> Episode:
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise TypeError("seed must be an int")
    cfg = normalize_config(config)
    last = None
    for attempt in range(30):
        try:
            return _generate(seed, cfg, attempt)
        except (InjectionError, PostingError, InvariantError, KeyError) as e:
            last = e
    raise GenerationError("could not generate a valid episode for seed=%r: %s" % (seed, last))


# --------------------------------------------------------------------------- core
def _plan_counts(rng, cfg):
    counts = {t: sample_range(rng, cfg["errors"][t]) for t in ISSUE_TYPES}
    inter = {k: sample_range(rng, cfg["interactions"][k]) for k in INTERACTIONS}
    total = sum(counts.values()) + 2 * sum(inter.values())
    keys = [t for t in ISSUE_TYPES]
    while total > MAX_ISSUES:
        cand = [t for t in keys if counts[t] > cfg["errors"][t][0]]
        if not cand:
            break
        t = rng.choice(cand)
        counts[t] -= 1
        total -= 1
    return counts, inter


def _generate(seed, cfg, attempt):
    wcfg_hash = config_hash(world_config(cfg))
    rng = sub_rng("world", ENV_VERSION, seed, wcfg_hash, attempt)
    b = Builder(rng, cfg)
    w = b.build()

    counts, inter = _plan_counts(rng, cfg)
    inj = Injector(b)
    planned = []
    order = []
    for k in INTERACTIONS:
        order += [k] * inter[k]
    for t in ISSUE_TYPES:
        order += [t] * counts[t]
    for name in order:                       # interactions first: they need fresh objects
        planned += getattr(inj, name)()

    # ---- clean counterpart (same documents, mutations reverted) for invariant checks
    clean = copy.deepcopy(w)
    for iss in planned:
        _revert(clean, iss.story)
    clean_lines = post_ledger(clean)
    check_clean_invariants(clean, clean_lines)

    dirty_lines = post_ledger(w)
    check_journals_balanced(dirty_lines)
    check_declared_changes(clean, clean_lines, w, dirty_lines, planned)
    check_window(w, dirty_lines)

    return _render(seed, cfg, attempt, w, dirty_lines, planned, clean_lines)


def _revert(w, story):
    m = story["mutation"]
    if m == "duplicate_document_posted":
        k = story["duplicate"]
        w.invoices.pop(k, None)
        w.inv_post.pop(k, None)
    elif m == "allocation_not_applied":
        w.pay_post[story["payment"]].applied[story["ref_index"]] = True
    elif m == "wrong_rate_date":
        if story["document"] == "invoice":
            inv = w.invoices[story["invoice"]]
            w.inv_post[inv.key].rate_date = w.ldate(inv.issued_at)
        else:
            p = w.payments[story["payment"]]
            w.pay_post[p.key].rate_date = w.ldate(p.timestamp)
    elif m == "wrong_posting_period":
        inv = w.invoices[story["invoice"]]
        w.inv_post[inv.key].post_at = inv.issued_at
    else:
        raise InvariantError("unknown mutation %r" % m)


# --------------------------------------------------------------------------- invariants
def check_journals_balanced(lines):
    tot = {}
    for l in lines:
        d, c = tot.get(l.journal, (0, 0))
        tot[l.journal] = (d + l.debit, c + l.credit)
        if (l.debit == 0) == (l.credit == 0):
            raise InvariantError("line must have exactly one of debit/credit: %r" % (l.role,))
    for j, (d, c) in tot.items():
        if d != c:
            raise InvariantError("journal %d unbalanced: %d != %d" % (j, d, c))


def check_clean_invariants(w, lines):
    """Accounting equalities that must hold in the books BEFORE any error is injected."""
    check_journals_balanced(lines)
    by_role = {}
    for l in lines:
        if l.role in by_role:
            raise InvariantError("duplicate role %r" % (l.role,))
        by_role[l.role] = l
    # every document posted exactly once, in its own period, at the policy rate
    for inv in w.invoices.values():
        if inv.dup_of is not None:
            raise InvariantError("duplicate document in clean world")
        l = by_role.get(("ar_debit", inv.key))
        if l is None:
            raise InvariantError("invoice not posted")
        if l.debit != w.to_base(inv.total, inv.currency, w.ldate(inv.issued_at)):
            raise InvariantError("invoice not at policy rate")
        if inv.kind != "opening" and w.ldate(l.ts) != w.ldate(inv.issued_at):
            raise InvariantError("invoice posted on another local date")
        if inv.kind == "opening" and w.ldate(inv.issued_at) >= w.period_start:
            raise InvariantError("opening invoice inside period")
    ar_bal = {}
    for l in lines:
        if l.account == ACC_AR:
            ar_bal[l.inv] = ar_bal.get(l.inv, 0) + l.debit - l.credit
    for inv in w.invoices.values():
        paid = sum(r[1] for p in w.payments.values() for r in (p.refs or []) if r[0] == inv.key)
        if paid > inv.total:
            raise InvariantError("overpaid invoice")
        if paid == inv.total and ar_bal.get(inv.key, 0) != 0:
            raise InvariantError("fully paid invoice keeps AR balance")
        if ar_bal.get(inv.key, 0) < 0:
            raise InvariantError("negative AR")
    for p in w.payments.values():
        cash = by_role[("cash", p.key)]
        exp = w.to_base(abs(p.amount), p.currency, w.ldate(p.timestamp))
        if (cash.debit or cash.credit) != exp:
            raise InvariantError("payment cash not at policy rate")
        if w.ldate(cash.ts) != w.ldate(p.timestamp):
            raise InvariantError("payment posted on another local date")
        if p.refs is not None:
            if sum(r[1] for r in p.refs) != p.amount:
                raise InvariantError("refs do not sum to payment")
            for ik, _ in p.refs:
                if ("ar_credit", p.key, ik) not in by_role:
                    raise InvariantError("clean allocation missing")
                if w.inv_post[ik].post_at >= w.pay_post[p.key].post_at:
                    raise InvariantError("payment before invoice")
                if w.invoices[ik].currency != p.currency:
                    raise InvariantError("currency mismatch in refs")
    # trial balance
    if sum(l.debit for l in lines) != sum(l.credit for l in lines):
        raise InvariantError("trial balance does not balance")


def _doc_keys_of_role(role):
    kind = role[0]
    if kind in ("ar_debit", "revenue", "opening"):
        return {("inv", role[1])}
    if kind in ("cash", "fx_gl", "advance", "refund_advance"):
        return {("pay", role[1])}
    if kind == "ar_credit":
        return {("pay", role[1]), ("inv", role[2])}
    if kind == "suspense":
        s = {("pay", role[1])}
        if role[2] is not None:
            s.add(("inv", role[2]))
        return s
    return {("exp", role[1])}


def check_declared_changes(clean, clean_lines, w, dirty_lines, planned):
    """Clean and dirty books may differ only on lines tied to declared, affected documents
    (including payment journals whose AR relief propagates a declared change)."""
    affected = set()
    for iss in planned:
        affected.update(iss.affected)
    # payments that settle an affected invoice may legitimately change (relief/FX line)
    for p in w.payments.values():
        if p.refs and any(("inv", r[0]) in affected for r in p.refs):
            affected.add(("pay", p.key))

    def sig(lines):
        return {l.role: (l.account, l.debit, l.credit, l.ts) for l in lines}

    a, b = sig(clean_lines), sig(dirty_lines)
    for role in set(a) | set(b):
        if a.get(role) != b.get(role):
            if not (_doc_keys_of_role(role) & affected):
                raise InvariantError("undeclared change on %r" % (role,))
    if not planned and a != b:
        raise InvariantError("clean episode differs from its clean counterpart")


def check_window(w, lines):
    for l in lines:
        d = w.ldate(l.ts)
        if not (w.period_start <= d <= w.window_end):
            raise InvariantError("ledger line outside window: %s" % d)


# --------------------------------------------------------------------------- rendering
class _Ids:
    def __init__(self, rng):
        self.rng = rng
        self.used = set()

    def new(self, prefix, n, alphabet="0123456789"):
        while True:
            s = "%s-%s" % (prefix, "".join(self.rng.choice(alphabet) for _ in range(n)))
            if s not in self.used:
                self.used.add(s)
                return s


def _fx_id(date, src, dst):
    return "FX-%s-%s-%s" % (date.isoformat(), src, dst)


def _render(seed, cfg, attempt, w, lines, planned, clean_lines):
    id_seed = cfg["id_seed"] if cfg["id_seed"] is not None else seed
    ids = _Ids(sub_rng("ids", ENV_VERSION, id_seed))
    hexa = "0123456789abcdef"
    cust_id = {k: ids.new("CUST", 5) for k in sorted(w.customers)}
    vend_id = {k: ids.new("VEND", 5) for k in sorted(w.vendors)}
    inv_id = {k: ids.new("INV", 6) for k in sorted(w.invoices)}
    inv_doc = {k: ids.new("DOC", 8, hexa) for k in sorted(w.invoices)}
    pay_id = {k: ids.new("PAY", 6) for k in sorted(w.payments)}
    pay_doc = {k: ids.new("DOC", 8, hexa) for k in sorted(w.payments)}
    row_id = [ids.new("ROW", 8, hexa) for _ in lines]

    def ent(e):
        if e is None:
            return None
        return cust_id[e[1]] if e[0] == "C" else vend_id[e[1]]

    ledger = []
    for l, rid in zip(lines, row_id):
        ledger.append({
            "row_id": rid, "timestamp": iso(l.ts), "account": l.account,
            "debit_minor": l.debit, "credit_minor": l.credit, "currency": w.base,
            "entity_id": ent(l.entity),
            "invoice_id": inv_id[l.inv] if l.inv is not None else None,
            "payment_id": pay_id[l.pay] if l.pay is not None else None,
            "_k": (l.ts, l.journal),
        })
    ledger.sort(key=lambda r: (r.pop("_k")))  # chronological; stable within a journal

    invoices = []
    for k, inv in w.invoices.items():
        invoices.append({
            "doc_id": inv_doc[k], "invoice_id": inv_id[k], "entity_id": cust_id[inv.cust],
            "issued_at": iso(inv.issued_at), "due_at": iso(inv.due_at), "currency": inv.currency,
            "total_minor": inv.total,
            "line_items": [dict(l, line_no=i + 1) for i, l in enumerate(inv.lines)],
            "_k": (inv.issued_at, inv_id[k]),
        })
    invoices.sort(key=lambda r: r.pop("_k"))
    payments = []
    for k, p in w.payments.items():
        payments.append({
            "doc_id": pay_doc[k], "payment_id": pay_id[k], "timestamp": iso(p.timestamp),
            "currency": p.currency, "amount_minor": p.amount,
            "invoice_refs": None if p.refs is None else [
                {"invoice_id": inv_id[r[0]], "amount_minor": r[1]} for r in p.refs],
            "_k": (p.timestamp, pay_id[k]),
        })
    payments.sort(key=lambda r: r.pop("_k"))
    fx = []
    lo = w.period_start - timedelta(days=FX_HISTORY_DAYS)
    for cur in sorted(w.rates):
        for d in sorted(w.rates[cur]):
            if lo <= d <= w.window_end:
                fx.append({"fx_id": _fx_id(d, cur, w.base), "date": d.isoformat(),
                           "source_currency": cur, "target_currency": w.base, "rate": w.rates[cur][d]})
    fx.sort(key=lambda r: (r["date"], r["source_currency"]))
    fx_ids = {r["fx_id"] for r in fx}

    if cfg["order_seed"] is not None:
        for name, lst in (("ledger", ledger), ("invoices", invoices), ("payments", payments), ("fx", fx)):
            sub_rng("order", ENV_VERSION, cfg["order_seed"], name).shuffle(lst)

    # ---- truth
    def ext(a):
        return inv_id[a[1]] if a[0] == "inv" else pay_id[a[1]]

    def ev(ref):
        if ref[0] == "doc_inv":
            return inv_doc[ref[1]]
        if ref[0] == "doc_pay":
            return pay_doc[ref[1]]
        if ref[0] == "line":
            return row_id[lines.index(find_line(lines, ref[1]))]
        if ref[0] == "fx":
            fid = _fx_id(ref[2], ref[1], w.base)
            if fid not in fx_ids:
                raise InvariantError("evidence FX row not published: %s" % fid)
            return fid
        raise InvariantError("bad evidence ref %r" % (ref,))

    issues = []
    for n, iss in enumerate(planned):
        amount = _amount(w, lines, iss.amount_rule)
        if amount <= 0:
            raise InvariantError("non-positive discrepancy for %s" % iss.type)
        issues.append({
            "type": iss.type,
            "affected_ids": sorted(ext(a) for a in iss.affected),
            "expected_amount_minor": amount,
            "currency": iss.currency,
            "amount_tolerance_minor": iss.tolerance,
            "evidence_sets": [sorted(ev(r) for r in s) for s in iss.evidence],
            "interaction_group": iss.group,
            "_story": iss.story,
        })
    issues.sort(key=lambda i: (i["type"], i["affected_ids"]))
    eid = episode_id_for(seed, cfg)
    mutations = []
    for i, iss in enumerate(issues):
        iss["issue_id"] = "%s-I%02d" % (eid, i + 1)
        story = iss.pop("_story")
        mutations.append(_render_story(story, inv_id, pay_id, w, iss["issue_id"]))

    used_cur = sorted({w.base} | {i["currency"] for i in invoices} | {p["currency"] for p in payments})
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "env_version": ENV_VERSION,
        "episode_id": eid,
        "company_name": w.company_name,
        "base_currency": w.base,
        "currency_exponents": {c: CURRENCY_EXPONENTS[c] for c in used_cur},
        "timezone": offset_str(w.offset),
        "period_start": w.period_start.isoformat(),
        "period_end": w.period_end.isoformat(),
        "ledger_window_end": w.window_end.isoformat(),
        "counts": {
            "ledger_rows": len(ledger), "invoices": len(invoices), "payments": len(payments),
            "documents": len(invoices) + len(payments), "fx_rates": len(fx),
        },
        "rounding": {
            "money": "integer minor units; exponent per currency in currency_exponents",
            "fx_conversion": w.rounding,
            "fx_rate_format": "decimal string",
        },
    }
    policy = make_policy(w)
    truth = {"episode_id": eid, "schema_version": SCHEMA_VERSION, "issues": issues}
    tags = {}
    for inv in w.invoices.values():
        for t in inv.tags:
            tags["invoice:" + t] = tags.get("invoice:" + t, 0) + 1
    for p in w.payments.values():
        for t in p.tags:
            tags["payment:" + t] = tags.get("payment:" + t, 0) + 1
    provenance = {
        "env_version": ENV_VERSION,
        "seed": seed,
        "config": cfg,
        "generation_attempt": attempt,
        "world": {"base": w.base, "offset": offset_str(w.offset), "rounding": w.rounding,
                  "foreign_currencies": w.foreign, "customers": len(w.customers),
                  "period": [w.period_start.isoformat(), w.period_end.isoformat()]},
        "mutations": mutations,
        "distractor_tags": dict(sorted(tags.items())),
        "clean_ledger_lines": len(clean_lines),
        "dirty_ledger_lines": len(lines),
    }
    return Episode(manifest, policy, {"ledger": ledger, "invoices": invoices, "payments": payments, "fx": fx},
                   truth, provenance)


def _amount(w, lines, rule):
    kind, k = rule
    if kind == "fixed":
        return int(k)
    if kind == "ar_base":
        return find_line(lines, ("ar_debit", k)).debit
    if kind == "fx_inv":
        inv = w.invoices[k]
        rec = find_line(lines, ("ar_debit", k)).debit
        return abs(rec - w.to_base(inv.total, inv.currency, w.ldate(inv.issued_at)))
    if kind == "fx_pay":
        p = w.payments[k]
        rec = find_line(lines, ("cash", k))
        rec_v = rec.debit or rec.credit
        return abs(rec_v - w.to_base(abs(p.amount), p.currency, w.ldate(p.timestamp)))
    raise InvariantError("bad amount rule %r" % (rule,))


def _render_story(story, inv_id, pay_id, w, issue_id):
    out = {"issue_id": issue_id}
    for k, v in story.items():
        if k in ("original", "duplicate", "invoice"):
            out[k] = inv_id[v]
        elif k == "payment":
            out[k] = pay_id[v]
        else:
            out[k] = v
    return out


def make_policy(w):
    return {
        "policy_version": "1.0",
        "period": {
            "rule": "A record belongs to the reporting period when its calendar date in manifest.timezone "
                    "is between period_start and period_end inclusive. Invoices are dated by issued_at, "
                    "payments by timestamp, ledger rows by timestamp. Timestamps carry their own UTC offset; "
                    "convert to manifest.timezone before taking the date.",
            "ledger_window": "ledger.csv holds rows dated period_start..ledger_window_end; rows after "
                             "period_end are subsequent-period postings shown for cut-off testing. "
                             "Invoices issued before period_start appear as opening balances (account 3900) "
                             "posted at period_start.",
        },
        "fx": {
            "quote": "rate = units of target_currency for 1 major unit of source_currency",
            "rate_date": "calendar date of the document timestamp in manifest.timezone; if no rate is "
                         "published for that date, use the latest earlier published date",
            "conversion": "base_minor = round(amount_minor / 10^exp(source) * rate * 10^exp(base))",
            "rounding": w.rounding,
            "ar_relief": "AR is relieved at the invoice's recorded base amount (pro rata for partial "
                         "allocations, remaining balance on the allocation that completes the invoice); "
                         "the difference to the cash line goes to 7900",
        },
        "posting": {
            "invoice": "Dr 1100 AR (base amount at invoice rate) / Cr 4000 revenue per line item",
            "payment_with_refs": "Dr 1000 cash at payment rate / Cr 1100 for each applied invoice_ref; "
                                 "a ref that is not applied sits in 1190; difference to 7900",
            "payment_without_refs_known_customer": "Dr 1000 / Cr 2300 customer advance",
            "payment_without_refs_unknown_payer": "Dr 1000 / Cr 1190 unapplied receipt",
            "refund": "negative amount_minor; Dr 2300 / Cr 1000",
            "expense": "Dr 6xxx / Cr 1000, no documents in this extract",
        },
        "accounts": CHART_OF_ACCOUNTS,
        "findings": {
            "types": list(ISSUE_TYPES),
            "affected_ids": {
                "duplicate_invoice": "invoice_id of the original AND of the duplicate (order irrelevant)",
                "unallocated_payment": "payment_id and the invoice_id whose allocation was not applied",
                "fx_misconversion": "the invoice_id or payment_id whose base amount used a wrong rate",
                "period_cutoff": "invoice_id posted in the wrong period",
            },
            "amount": {
                "duplicate_invoice": "total_minor of the duplicate invoice, invoice currency",
                "unallocated_payment": "amount_minor of the unapplied invoice_ref, payment currency",
                "fx_misconversion": "|recorded base amount - correctly converted base amount| of the AR "
                                    "debit row (invoice) or cash row (payment), base currency",
                "period_cutoff": "base amount of the AR debit row posted in the wrong period, base currency",
            },
            "evidence": {
                "duplicate_invoice": "doc_id of both invoices + row_id of both AR (1100) debit rows",
                "unallocated_payment": "doc_id of the payment + row_id of its 1190 suspense row",
                "fx_misconversion": "doc_id + row_id of the converted row (AR debit or cash) + fx_id of the "
                                    "rate the policy requires",
                "period_cutoff": "doc_id of the invoice + row_id of its AR (1100) debit row",
            },
            "amount_tolerance_minor": {"fx_misconversion": 1, "duplicate_invoice": 0,
                                       "unallocated_payment": 0, "period_cutoff": 0},
        },
    }
