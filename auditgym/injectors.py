"""Error injection with recorded causal changes.

Every injector changes the hidden history in exactly one documented way
(a bogus duplicate document, an allocation that was not applied, a wrong FX
rate date, a wrong posting date) and returns a PlannedIssue that says how the
resulting discrepancy is measured and which public records prove it.
"""

import copy
from dataclasses import dataclass, field
from datetime import timedelta
from typing import List, Optional

from .constants import CURRENCY_EXPONENTS, DOC_OFFSETS
from .timeutil import iso, tz


class InjectionError(RuntimeError):
    pass


@dataclass
class PlannedIssue:
    type: str
    affected: List[tuple]          # ("inv", key) / ("pay", key)
    currency: str
    amount_rule: tuple             # ("fixed", n) | ("fx_inv", k) | ("fx_pay", k) | ("ar_base", k)
    evidence: List[List[tuple]]    # alternative complete evidence sets
    story: dict
    group: Optional[str] = None
    tolerance: int = 0


@dataclass
class Injector:
    b: object                       # world.Builder (gives rng, world, document factories)
    used_inv: set = field(default_factory=set)
    used_pay: set = field(default_factory=set)

    @property
    def w(self):
        return self.b.w

    @property
    def rng(self):
        return self.b.rng

    # ------------------------------------------------------------------ helpers
    def payments_for(self, inv_key):
        return [p for p in self.w.payments.values() if p.refs and any(r[0] == inv_key for r in p.refs)]

    def posted_date(self, inv_key):
        return self.w.ldate(self.w.inv_post[inv_key].post_at)

    def free_period_invoices(self, foreign=None, unpaid=False):
        w = self.w
        out = []
        for inv in w.invoices.values():
            if inv.kind != "period" or inv.dup_of is not None or inv.key in self.used_inv:
                continue
            if "boundary" in inv.tags:
                continue
            if not w.in_period(self.posted_date(inv.key)):
                continue
            if foreign is True and inv.currency == w.base:
                continue
            if foreign is False and inv.currency != w.base:
                continue
            if unpaid and self.payments_for(inv.key):
                continue
            out.append(inv)
        out.sort(key=lambda i: i.key)
        return out

    def new_invoice(self, cust, local_dt, kind, tags):
        inv = self.b.add_invoice(cust, local_dt, kind, tags=tags)
        self.w.inv_post[inv.key] = self.b.clean_invoice_decision(inv)
        return inv

    def new_payment(self, cust, local_dt, amount, refs, tags):
        p = self.b.add_payment(cust, local_dt, cust.currency, amount, refs, "settlement", tags)
        self.w.pay_post[p.key] = self.b.clean_payment_decision(p)
        return p

    def pick_customer(self, foreign=None):
        cs = [c for c in self.w.customers.values()
              if foreign is None or (c.currency != self.w.base) == foreign]
        if not cs:
            raise InjectionError("no customer with foreign=%r" % foreign)
        return self.rng.choice(sorted(cs, key=lambda c: c.key))

    def wrong_rate_date(self, cur, amount, correct_date, candidates):
        """First candidate date whose published rate differs enough to move the base amount."""
        w = self.w
        correct_pub = w.published(cur, correct_date)
        correct_val = w.to_base(amount, cur, correct_date)
        exp = CURRENCY_EXPONENTS[w.base]
        min_diff = 2 if exp == 0 else 2
        for label, d in candidates:
            try:
                pub = w.published(cur, d)
            except KeyError:
                continue
            if pub == correct_pub:
                continue
            if abs(w.to_base(amount, cur, d) - correct_val) >= min_diff:
                return label, d
        return None

    def fx_candidates(self, instant, correct_date, due=None):
        rng, w = self.rng, self.w
        cands = [
            ("utc_calendar_date", instant.astimezone(tz(0)).date()),
            ("previous_day", correct_date - timedelta(days=1)),
            ("next_day_value_date", correct_date + timedelta(days=1)),
            ("stale_rate_%dd" % 0, correct_date - timedelta(days=rng.randint(2, 7))),
            ("period_end_rate", w.period_end),
        ]
        if due is not None:
            cands.append(("due_date", w.ldate(due)))
        head, tail = cands[:1], cands[1:]
        rng.shuffle(tail)
        return head + tail if rng.random() < 0.5 else tail + head

    # ------------------------------------------------------------------ 1. duplicates
    def duplicate_invoice(self):
        rng, w = self.rng, self.w
        cands = [i for i in self.free_period_invoices()
                 if self.posted_date(i.key) <= w.period_end - timedelta(days=1)]
        if not cands or rng.random() < 0.15:
            c = self.pick_customer()
            d = w.period_start + timedelta(days=rng.randint(0, max(0, (w.period_end - w.period_start).days - 3)))
            cands = [self.new_invoice(c, w.local_dt(d, rng.randint(8, 18), rng.randint(0, 59)), "period", [])]
        orig = rng.choice(cands)
        delta = timedelta(minutes=rng.choice([0, rng.randint(1, 600), rng.randint(600, 2880)]))
        if not w.in_period(w.ldate(orig.issued_at + delta)):
            delta = timedelta(0)
        k = w.new_key()
        dup = copy.deepcopy(orig)
        dup.key, dup.dup_of, dup.tags = k, orig.key, ["duplicate"]
        dup.issued_at = orig.issued_at + delta
        dup.due_at = orig.due_at + delta
        w.invoices[k] = dup
        w.inv_post[k] = self.b.clean_invoice_decision(dup)
        self.used_inv.update([orig.key, k])
        return [PlannedIssue(
            "duplicate_invoice", [("inv", orig.key), ("inv", k)], orig.currency, ("fixed", orig.total),
            [[("doc_inv", orig.key), ("doc_inv", k), ("line", ("ar_debit", orig.key)), ("line", ("ar_debit", k))]],
            {"mutation": "duplicate_document_posted", "original": orig.key, "duplicate": k,
             "issued_delta_minutes": int(delta.total_seconds() // 60)},
        )]

    # ------------------------------------------------------------------ 2. allocation
    def _alloc_candidates(self, multi):
        w = self.w
        out = []
        for p in w.payments.values():
            if p.kind != "settlement" or not p.refs or p.key in self.used_pay:
                continue
            if (len(p.refs) >= 2) != multi or "split" in p.tags or "partial_open" in p.tags or "was_duplicated" in p.tags:
                continue
            if not w.in_period(w.ldate(w.pay_post[p.key].post_at)):
                continue
            ok = all(r[0] not in self.used_inv and len(self.payments_for(r[0])) == 1
                     and w.invoices[r[0]].kind != "subsequent" for r in p.refs)
            if ok:
                out.append(p)
        out.sort(key=lambda p: p.key)
        return out

    def _fresh_payment(self, cust, n_invoices, pay_day=None, early_days=None):
        rng, w = self.rng, self.w
        span = (w.period_end - w.period_start).days
        invs = []
        for _ in range(n_invoices):
            d = w.period_start + timedelta(days=rng.randint(0, early_days if early_days is not None else max(0, span - 8)))
            invs.append(self.new_invoice(cust, w.local_dt(d, rng.randint(8, 18), rng.randint(0, 59)), "period", []))
        last = max(w.ldate(i.issued_at) for i in invs)
        if pay_day is None:
            pay_day = min(w.period_end, last + timedelta(days=rng.randint(1, 7)))
        when = w.local_dt(pay_day, rng.randint(9, 19), rng.randint(0, 59))
        refs = sorted([[i.key, i.total] for i in invs], key=lambda r: (w.invoices[r[0]].issued_at, r[0]))
        p = self.new_payment(cust, when, sum(r[1] for r in refs), refs, ["multi"] if n_invoices > 1 else [])
        return p

    def unallocated_payment(self):
        rng, w = self.rng, self.w
        variant = rng.choice(["missing", "partial"])
        cands = self._alloc_candidates(multi=(variant == "partial"))
        if not cands or rng.random() < 0.15:
            cands = [self._fresh_payment(self.pick_customer(), 2 if variant == "partial" else 1)]
        p = rng.choice(cands)
        j = rng.randrange(len(p.refs))
        w.pay_post[p.key].applied[j] = False
        inv_key, amt = p.refs[j]
        self.used_pay.add(p.key)
        self.used_inv.update(r[0] for r in p.refs)
        return [self._alloc_issue(p, j, variant)]

    def _alloc_issue(self, p, j, variant, group=None):
        inv_key, amt = p.refs[j]
        return PlannedIssue(
            "unallocated_payment", [("pay", p.key), ("inv", inv_key)], p.currency, ("fixed", amt),
            [[("doc_pay", p.key), ("line", ("suspense", p.key, inv_key))]],
            {"mutation": "allocation_not_applied", "variant": variant, "payment": p.key,
             "invoice": inv_key, "ref_index": j},
            group=group,
        )

    # ------------------------------------------------------------------ 3. FX
    def fx_misconversion(self):
        rng, w = self.rng, self.w
        target = "invoice" if rng.random() < 0.6 else "payment"
        for _attempt in range(6):
            if target == "invoice":
                cands = self.free_period_invoices(foreign=True)
                rng.shuffle(cands)
                if _attempt >= 3 or not cands:
                    c = self.pick_customer(foreign=True)
                    d = w.period_start + timedelta(days=rng.randint(0, (w.period_end - w.period_start).days - 1))
                    cands = [self.new_invoice(c, w.local_dt(d, rng.randint(8, 18), rng.randint(0, 59)), "period", [])]
                for inv in cands[:8]:
                    correct = w.ldate(inv.issued_at)
                    choice = self.wrong_rate_date(inv.currency, inv.total, correct,
                                                  self.fx_candidates(inv.issued_at, correct, inv.due_at))
                    if choice:
                        label, d = choice
                        w.inv_post[inv.key].rate_date = d
                        self.used_inv.add(inv.key)
                        return [self._fx_inv_issue(inv, label, d)]
            else:
                cands = [p for p in self._alloc_candidates(False) + self._alloc_candidates(True)
                         if p.currency != w.base]
                rng.shuffle(cands)
                if _attempt >= 3 or not cands:
                    cands = [self._fresh_payment(self.pick_customer(foreign=True), 1)]
                for p in cands[:8]:
                    correct = w.ldate(p.timestamp)
                    choice = self.wrong_rate_date(p.currency, p.amount, correct,
                                                  self.fx_candidates(p.timestamp, correct))
                    if choice:
                        label, d = choice
                        w.pay_post[p.key].rate_date = d
                        self.used_pay.add(p.key)
                        self.used_inv.update(r[0] for r in p.refs)
                        return [self._fx_pay_issue(p, label, d)]
        raise InjectionError("could not find an FX target with a distinguishable wrong rate")

    def _fx_inv_issue(self, inv, label, d, group=None):
        w = self.w
        correct = w.ldate(inv.issued_at)
        return PlannedIssue(
            "fx_misconversion", [("inv", inv.key)], w.base, ("fx_inv", inv.key),
            [[("doc_inv", inv.key), ("line", ("ar_debit", inv.key)), ("fx", inv.currency, w.published(inv.currency, correct))]],
            {"mutation": "wrong_rate_date", "document": "invoice", "invoice": inv.key, "wrong_date_rule": label,
             "used_rate_date": d.isoformat(), "correct_rate_date": w.published(inv.currency, correct).isoformat()},
            group=group, tolerance=1,
        )

    def _fx_pay_issue(self, p, label, d, group=None):
        w = self.w
        correct = w.ldate(p.timestamp)
        return PlannedIssue(
            "fx_misconversion", [("pay", p.key)], w.base, ("fx_pay", p.key),
            [[("doc_pay", p.key), ("line", ("cash", p.key)), ("fx", p.currency, w.published(p.currency, correct))]],
            {"mutation": "wrong_rate_date", "document": "payment", "payment": p.key, "wrong_date_rule": label,
             "used_rate_date": d.isoformat(), "correct_rate_date": w.published(p.currency, correct).isoformat()},
            group=group, tolerance=1,
        )

    # ------------------------------------------------------------------ 4. cut-off
    def _boundary_invoice(self, cust, day, early_h, late_h, tz_trick):
        rng, w = self.rng, self.w
        local = w.local_dt(day, rng.randint(early_h, late_h), rng.randint(5, 55), rng.randint(0, 59))
        inv = self.new_invoice(cust, local, self.b.kind_of(local), [])
        if tz_trick:
            # show the timestamp in a far-west offset: its printed calendar date looks in-period
            west = [o for o in DOC_OFFSETS if o <= w.offset - 240]
            if west:
                o = rng.choice(west)
                inv.issued_at = inv.issued_at.astimezone(tz(o))
                inv.due_at = inv.due_at.astimezone(tz(o))
        return inv

    def period_cutoff(self):
        rng, w = self.rng, self.w
        variant = rng.choice(["early", "late"])
        if variant == "early":
            cands = [i for i in w.invoices.values() if i.kind == "subsequent" and i.dup_of is None
                     and i.key not in self.used_inv and "boundary" not in i.tags
                     and w.ldate(i.issued_at) <= w.period_end + timedelta(days=2)]
            cands.sort(key=lambda i: i.key)
            if not cands or rng.random() < 0.5:
                cands = [self._boundary_invoice(self.pick_customer(), w.period_end + timedelta(days=rng.choice([1, 1, 2])),
                                                0, 9, rng.random() < 0.5)]
            inv = rng.choice(cands)
            post = w.local_dt(w.period_end, rng.randint(17, 23), rng.randint(0, 58), rng.randint(0, 59))
        else:
            cands = [i for i in self.free_period_invoices(unpaid=True)
                     if w.ldate(i.issued_at) >= w.period_end - timedelta(days=2)]
            if not cands or rng.random() < 0.4:
                cands = [self._boundary_invoice(self.pick_customer(), w.period_end - timedelta(days=rng.randint(0, 1)),
                                                9, 22, False)]
            inv = rng.choice(cands)
            pd = w.period_end + timedelta(days=rng.randint(1, max(1, (w.window_end - w.period_end).days - 1)))
            post = w.local_dt(pd, rng.randint(8, 18), rng.randint(0, 59), rng.randint(0, 59))
            for p in self.payments_for(inv.key):       # never let a payment precede the late posting
                if w.pay_post[p.key].post_at <= post:
                    raise InjectionError("late cut-off target has an earlier payment")
        w.inv_post[inv.key].post_at = post
        self.used_inv.add(inv.key)
        return [self._cutoff_issue(inv, variant, post)]

    def _cutoff_issue(self, inv, variant, post, group=None):
        w = self.w
        return PlannedIssue(
            "period_cutoff", [("inv", inv.key)], w.base, ("ar_base", inv.key),
            [[("doc_inv", inv.key), ("line", ("ar_debit", inv.key))]],
            {"mutation": "wrong_posting_period", "variant": variant, "invoice": inv.key,
             "document_local_date": w.ldate(inv.issued_at).isoformat(), "posted_at": iso(post)},
            group=group,
        )

    # ------------------------------------------------------------------ interactions
    def fx_partial_payment(self):
        """Foreign payment received on the last day of the period, covering two invoices:
        one allocation was not applied AND the cash line used the next day's (value-date) rate."""
        rng, w = self.rng, self.w
        for _attempt in range(10):
            c = self.pick_customer(foreign=True)
            p = self._fresh_payment(c, 2, pay_day=w.period_end, early_days=max(0, (w.period_end - w.period_start).days - 6))
            correct = w.ldate(p.timestamp)
            cands = [("next_day_value_date", correct + timedelta(days=1)),
                     ("utc_calendar_date", p.timestamp.astimezone(tz(0)).date()),
                     ("value_date_plus_2", correct + timedelta(days=2)),
                     ("previous_day", correct - timedelta(days=1)),
                     ("stale_rate", correct - timedelta(days=3))]
            choice = self.wrong_rate_date(p.currency, p.amount, correct, cands)
            if not choice:
                continue
            label, d = choice
            j = rng.randrange(2)
            w.pay_post[p.key].applied[j] = False
            w.pay_post[p.key].rate_date = d
            self.used_pay.add(p.key)
            self.used_inv.update(r[0] for r in p.refs)
            g = "fx_partial_payment"
            return [self._alloc_issue(p, j, "partial", group=g), self._fx_pay_issue(p, label, d, group=g)]
        raise InjectionError("fx_partial_payment: no distinguishable rate")

    def cutoff_fx_boundary(self):
        """Foreign invoice issued just after period end (local time) but booked on the
        last day of the period at that day's rate instead of the document date's rate."""
        rng, w = self.rng, self.w
        for _attempt in range(10):
            c = self.pick_customer(foreign=True)
            inv = self._boundary_invoice(c, w.period_end + timedelta(days=1), 0, 6, rng.random() < 0.6)
            post = w.local_dt(w.period_end, rng.randint(18, 23), rng.randint(0, 58), rng.randint(0, 59))
            correct = w.ldate(inv.issued_at)
            cands = [("posting_date", w.period_end)] + [
                ("posting_date_minus_%d" % k, w.period_end - timedelta(days=k)) for k in range(1, 6)]
            choice = self.wrong_rate_date(inv.currency, inv.total, correct, cands)
            if not choice:
                del w.invoices[inv.key]
                del w.inv_post[inv.key]
                continue
            label, d = choice
            w.inv_post[inv.key].post_at = post
            w.inv_post[inv.key].rate_date = d
            self.used_inv.add(inv.key)
            g = "cutoff_fx_boundary"
            return [self._cutoff_issue(inv, "early", post, group=g), self._fx_inv_issue(inv, label, d, group=g)]
        raise InjectionError("cutoff_fx_boundary: no distinguishable rate")
