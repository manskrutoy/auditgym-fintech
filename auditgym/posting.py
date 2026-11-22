"""Deterministic double-entry posting: documents + decisions -> ledger lines."""

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from . import money
from .constants import (
    ACC_ADVANCES, ACC_AR, ACC_CASH, ACC_FX, ACC_OPENING, ACC_REVENUE, ACC_SUSPENSE,
)
from .timeutil import tz


@dataclass
class Line:
    journal: int
    ts: datetime
    account: str
    debit: int
    credit: int
    entity: Optional[tuple]       # ("C", key) | ("V", key) | None
    inv: Optional[int]
    pay: Optional[int]
    role: tuple


class PostingError(RuntimeError):
    pass


def post_ledger(w) -> List[Line]:
    events = []
    for inv in w.invoices.values():
        d = w.inv_post[inv.key]
        events.append((d.post_at, 0 if d.opening else 1, inv.key, "inv"))
    for p in w.payments.values():
        events.append((w.pay_post[p.key].post_at, 2, p.key, "pay"))
    for e in w.expenses.values():
        events.append((e.timestamp, 3, e.key, "exp"))
    events.sort(key=lambda e: (e[0], e[1], e[2]))

    lines: List[Line] = []
    ar = {}
    advance_book = {}          # payment key -> base amount carried in 2300
    journal = 0
    ctz = tz(w.offset)

    def add(ts, account, debit, credit, entity, inv, pay, role):
        if debit < 0 or credit < 0:
            raise PostingError("negative amount on %s" % (role,))
        lines.append(Line(journal, ts.astimezone(ctz), account, debit, credit, entity, inv, pay, role))

    for ts, _, key, kind in events:
        journal += 1
        if kind == "inv":
            inv = w.invoices[key]
            d = w.inv_post[key]
            ent = ("C", inv.cust)
            base = w.to_base(inv.total, inv.currency, d.rate_date)
            add(ts, ACC_AR, base, 0, ent, key, None, ("ar_debit", key))
            if d.opening:
                add(ts, ACC_OPENING, 0, base, ent, key, None, ("opening", key))
            else:
                acc = 0
                for i, line in enumerate(inv.lines):
                    if i == len(inv.lines) - 1:
                        part = base - acc
                    else:
                        part = money.prorate(base, line["amount_minor"], inv.total, w.rounding)
                    acc += part
                    add(ts, ACC_REVENUE, 0, part, ent, key, None, ("revenue", key, i))
            ar[key] = {"base": base, "balance": base, "remaining": inv.total}
        elif kind == "pay":
            p = w.payments[key]
            pp = w.pay_post[key]
            ent = ("C", p.cust) if p.cust is not None else None
            cash = w.to_base(abs(p.amount), p.currency, pp.rate_date)
            if p.kind == "refund":
                carried = advance_book.pop(p.refund_of, cash) if p.refund_of is not None else cash
                add(ts, ACC_ADVANCES, carried, 0, ent, None, key, ("refund_advance", key))
                add(ts, ACC_CASH, 0, cash, ent, None, key, ("cash", key))
                if cash > carried:
                    add(ts, ACC_FX, cash - carried, 0, None, None, key, ("fx_gl", key))
                elif carried > cash:
                    add(ts, ACC_FX, 0, carried - cash, None, None, key, ("fx_gl", key))
                continue
            add(ts, ACC_CASH, cash, 0, ent, None, key, ("cash", key))
            if p.refs is None:
                if p.kind in ("advance", "duplicate"):
                    add(ts, ACC_ADVANCES, 0, cash, ent, None, key, ("advance", key))
                    advance_book[key] = cash
                else:
                    add(ts, ACC_SUSPENSE, 0, cash, None, None, key, ("suspense", key, None))
                continue
            credits = 0
            for j, (ik, amt) in enumerate(p.refs):
                if pp.applied[j] and ik in ar:
                    st = ar[ik]
                    if amt >= st["remaining"]:
                        relief = st["balance"]
                    else:
                        relief = money.prorate(st["base"], amt, w.invoices[ik].total, w.rounding)
                    st["balance"] -= relief
                    st["remaining"] -= amt
                    add(ts, ACC_AR, 0, relief, ent, ik, key, ("ar_credit", key, ik))
                    credits += relief
                else:
                    s = w.to_base(amt, p.currency, pp.rate_date)
                    add(ts, ACC_SUSPENSE, 0, s, None, None, key, ("suspense", key, ik))
                    credits += s
            diff = cash - credits
            if diff > 0:
                add(ts, ACC_FX, 0, diff, None, None, key, ("fx_gl", key))
            elif diff < 0:
                add(ts, ACC_FX, -diff, 0, None, None, key, ("fx_gl", key))
        else:
            e = w.expenses[key]
            ent = ("V", e.vendor)
            add(ts, e.account, e.amount, 0, ent, None, None, ("expense", key))
            add(ts, ACC_CASH, 0, e.amount, ent, None, None, ("expense_cash", key))
    return lines


def find_line(lines, role):
    hits = [l for l in lines if l.role == role]
    if len(hits) != 1:
        raise PostingError("expected exactly one line with role %r, found %d" % (role, len(hits)))
    return hits[0]
