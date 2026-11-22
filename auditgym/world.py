"""Hidden company history ("world") and the clean bookkeeping decisions.

The world is generated first and is internally consistent.  Documents are
facts; ledger lines are *derived* from documents plus bookkeeping decisions
(posting time, FX rate date, which allocations were applied).  Errors are
injected later by changing decisions or adding bogus documents, so every
discrepancy has a recorded causal change (see injectors.py).
"""

import bisect
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

from . import money
from .config import sample_range
from .constants import (
    BASE_CURRENCIES,
    COMPANY_OFFSETS,
    CURRENCY_EXPONENTS,
    DOC_OFFSETS,
    EXPENSE_ACCOUNTS,
    USD_VALUE,
)
from .timeutil import at_local, last_day_of_month, local_date, tz


# --------------------------------------------------------------------------- data model
@dataclass
class Customer:
    key: int
    name: str
    currency: str
    doc_offset: int
    recurring: Optional[dict] = None


@dataclass
class Invoice:
    key: int
    cust: int
    issued_at: datetime
    due_at: datetime
    currency: str
    lines: List[dict]
    total: int
    kind: str                      # opening | period | subsequent
    dup_of: Optional[int] = None
    tags: List[str] = field(default_factory=list)


@dataclass
class Payment:
    key: int
    cust: Optional[int]
    timestamp: datetime
    currency: str
    amount: int
    refs: Optional[List[list]]     # [[invoice_key, amount_minor], ...] or None
    kind: str                      # settlement | advance | unidentified | duplicate | refund
    tags: List[str] = field(default_factory=list)


@dataclass
class Expense:
    key: int
    timestamp: datetime
    account: str
    amount: int
    vendor: int


@dataclass
class InvPost:
    post_at: datetime
    rate_date: date
    opening: bool = False


@dataclass
class PayPost:
    post_at: datetime
    rate_date: date
    applied: List[bool]


@dataclass
class World:
    company_name: str
    base: str
    offset: int
    period_start: date
    period_end: date
    window_end: date
    rounding: str
    foreign: List[str]
    rates: Dict[str, Dict[date, str]]
    customers: Dict[int, Customer] = field(default_factory=dict)
    vendors: Dict[int, str] = field(default_factory=dict)
    invoices: Dict[int, Invoice] = field(default_factory=dict)
    payments: Dict[int, Payment] = field(default_factory=dict)
    expenses: Dict[int, Expense] = field(default_factory=dict)
    inv_post: Dict[int, InvPost] = field(default_factory=dict)
    pay_post: Dict[int, PayPost] = field(default_factory=dict)
    next_key: int = 1
    _rate_dates: Dict[str, List[date]] = field(default_factory=dict)

    # ---- helpers
    def new_key(self) -> int:
        k = self.next_key
        self.next_key += 1
        return k

    def ldate(self, dt: datetime) -> date:
        return local_date(dt, self.offset)

    def in_period(self, d: date) -> bool:
        return self.period_start <= d <= self.period_end

    def published(self, cur: str, d: date) -> Optional[date]:
        """Latest publication date <= d (policy rule), or None."""
        if cur == self.base:
            return None
        ds = self._rate_dates.get(cur)
        if ds is None:
            ds = sorted(self.rates[cur])
            self._rate_dates[cur] = ds
        i = bisect.bisect_right(ds, d)
        if i == 0:
            raise KeyError("no FX rate for %s on or before %s" % (cur, d))
        return ds[i - 1]

    def rate(self, cur: str, d: date) -> str:
        if cur == self.base:
            return "1"
        return self.rates[cur][self.published(cur, d)]

    def to_base(self, amount: int, cur: str, rate_date: date) -> int:
        return money.convert_minor(amount, cur, self.base, self.rate(cur, rate_date), self.rounding)

    def local_dt(self, d: date, h: int, m: int, s: int = 0) -> datetime:
        return at_local(d, h, m, s, self.offset)

    def same_day_delay(self, instant: datetime, rng, max_minutes: int = 180) -> datetime:
        """instant + random delay that never crosses local midnight."""
        loc = instant.astimezone(tz(self.offset))
        midnight = datetime(loc.year, loc.month, loc.day, tzinfo=loc.tzinfo) + timedelta(days=1)
        room = int((midnight - loc).total_seconds()) - 120
        delay = rng.randint(0, max(0, min(max_minutes * 60, room)))      # seconds: no timestamp tells
        return (loc + timedelta(seconds=delay)).replace(microsecond=0)


# --------------------------------------------------------------------------- vocab (fictional)
_NAME_A = ["Altyn", "Nomad", "Steppe", "Aurora", "Baikonur", "Caspian", "Dala", "Esil",
           "Falcon", "Granite", "Horizon", "Irtysh", "Jade", "Koktem", "Lumen", "Meridian",
           "Nova", "Orbit", "Polar", "Quartz", "Riverbend", "Saryarka", "Tengri", "Ural",
           "Vertex", "Willow", "Zenith", "Borealis", "Cobalt", "Delta"]
_NAME_B = ["Logistics", "Foods", "Robotics", "Textiles", "Pharma", "Energy", "Media", "Mining",
           "Software", "Agro", "Retail", "Labs", "Freight", "Optics", "Studios", "Systems"]
_NAME_C = ["LLP", "Ltd", "GmbH", "LLC", "SA", "Co", "BV", "JSC"]
_VENDORS = ["City Property Mgmt", "Payroll Bureau", "Grid Utilities", "CloudSoft", "AirTravel Desk",
            "Ledger & Partners", "Office Supplies Hub", "Telecom One"]
_PRODUCTS = ["Sensor module", "Consulting hours", "Freight handling", "Maintenance visit",
             "Training session", "Data licence", "Spare parts kit", "Installation", "Calibration",
             "Custom firmware", "Warehouse storage", "Inspection report", "Cable assembly",
             "Field support", "Design review", "API usage block"]
_RECURRING = ["Platform subscription", "Support retainer", "Hosting plan", "Monitoring service",
              "Equipment lease"]


# --------------------------------------------------------------------------- builder
def _gen_rates(rng, base, foreign, start: date, end: date):
    """Synthetic random-walk FX rates published on business days only."""
    rates = {}
    holidays = set()
    span = (end - start).days
    for _ in range(rng.randint(0, 2)):
        holidays.add(start + timedelta(days=rng.randint(0, span)))
    for cur in foreign:
        level = USD_VALUE[cur] / USD_VALUE[base]
        level *= rng.uniform(0.9, 1.1)
        series = {}
        d = start
        while d <= end:
            level *= 1.0 + rng.gauss(0.0, 0.004)
            if d.weekday() < 5 and d not in holidays:
                series[d] = money.format_rate(level)
            d += timedelta(days=1)
        # guarantee day-to-day changes (identical consecutive rates would hide FX errors)
        prev = None
        for dd in sorted(series):
            if series[dd] == prev:
                level_v = float(series[dd]) * (1.0007 if rng.random() < 0.5 else 0.9993)
                series[dd] = money.format_rate(level_v)
            prev = series[dd]
        rates[cur] = series
    return rates


def _unique_name(rng, used):
    for _ in range(200):
        n = "%s %s %s" % (rng.choice(_NAME_A), rng.choice(_NAME_B), rng.choice(_NAME_C))
        if n not in used:
            used.add(n)
            return n
    n = "Entity %d" % (len(used) + 1)
    used.add(n)
    return n


def _price_minor(rng, cur, usd_lo, usd_hi):
    usd = rng.uniform(usd_lo, usd_hi)
    major = usd / USD_VALUE[cur]
    exp = CURRENCY_EXPONENTS[cur]
    # round to "nice" prices: 2-3 significant digits
    mag = 10 ** max(0, len(str(int(major))) - 3)
    major = max(1, int(round(major / mag)) * mag) if major >= 1 else major
    minor = int(round(major * (10 ** exp)))
    if exp > 0 and rng.random() < 0.4:
        minor += rng.choice([10 ** exp // 2, 10 ** exp * 99 // 100]) if exp >= 2 else 0
    return max(1, minor)


def _random_local_time(rng, w: World, d: date, early=8, late=19) -> datetime:
    return w.local_dt(d, rng.randint(early, late), rng.randint(0, 59), rng.randint(0, 59))


class Builder:
    """Builds a clean world.  All randomness comes from the given rng."""

    def __init__(self, rng, cfg):
        self.rng = rng
        self.cfg = cfg
        self.used_names = set()

    # ---------------------------------------------------------------- top level
    def build(self) -> World:
        rng, cfg = self.rng, self.cfg
        base = cfg["base_currency"] or rng.choice(BASE_CURRENCIES)
        offset = rng.choice(COMPANY_OFFSETS)
        year = rng.choice([2025, 2026])
        month = rng.randint(1, 12)
        pstart = date(year, month, 1)
        pend = last_day_of_month(year, month)
        wend = pend + timedelta(days=cfg["subsequent_days"])
        pool = [c for c in CURRENCY_EXPONENTS if c != base]
        foreign = sorted(rng.sample(pool, rng.randint(1, 3)))
        rates = _gen_rates(rng, base, foreign, pstart - timedelta(days=90), wend + timedelta(days=40))
        w = World(
            company_name=_unique_name(rng, self.used_names),
            base=base, offset=offset, period_start=pstart, period_end=pend, window_end=wend,
            rounding=rng.choice(["half_even", "half_up"]), foreign=foreign, rates=rates,
        )
        self.w = w
        self._customers()
        self._vendors()
        self._invoices()
        self._payments()
        self._distractor_payments()
        self._clean_decisions_all()
        self._expenses()
        return w

    # ---------------------------------------------------------------- parties
    def _customers(self):
        rng, w = self.rng, self.w
        n = sample_range(rng, self.cfg["n_customers"])
        for _ in range(n):
            k = w.new_key()
            cur = rng.choice(w.foreign) if rng.random() < self.cfg["foreign_share"] else w.base
            off = w.offset if rng.random() < 0.5 else rng.choice(DOC_OFFSETS)
            w.customers[k] = Customer(k, _unique_name(rng, self.used_names), cur, off)
        # at least one foreign and one base customer when possible
        custs = list(w.customers.values())
        if all(c.currency == w.base for c in custs):
            custs[0].currency = w.foreign[0]
        if all(c.currency != w.base for c in custs):
            custs[-1].currency = w.base
        nrec = min(len(custs), sample_range(rng, self.cfg["distractors"]["recurring_customers"]))
        for c in rng.sample(custs, nrec):
            c.recurring = {
                "description": rng.choice(_RECURRING),
                "unit_price_minor": _price_minor(rng, c.currency, 200, 2500),
                "day": rng.randint(1, 26),
            }

    def _vendors(self):
        for name in _VENDORS:
            self.w.vendors[self.w.new_key()] = name

    # ---------------------------------------------------------------- invoices
    def make_lines(self, cur, n_lines=None):
        rng = self.rng
        n_lines = n_lines or rng.choice([1, 1, 2, 2, 3, 4])
        lines = []
        for prod in rng.sample(_PRODUCTS, n_lines):
            qty = rng.choice([1, 1, 1, 2, 3, 4, 5, 8, 10, 12])
            unit = _price_minor(rng, cur, 30, 1800)
            lines.append({"description": prod, "quantity": qty, "unit_price_minor": unit,
                          "amount_minor": qty * unit})
        return lines

    def add_invoice(self, cust: Customer, issued_local: datetime, kind: str, lines=None, tags=None) -> Invoice:
        rng, w = self.rng, self.w
        lines = lines or self.make_lines(cust.currency)
        k = w.new_key()
        issued = issued_local.astimezone(tz(cust.doc_offset))
        due = issued + timedelta(days=rng.choice([14, 30, 30, 45]))
        inv = Invoice(k, cust.key, issued, due, cust.currency, lines,
                      sum(l["amount_minor"] for l in lines), kind, tags=list(tags or []))
        self._dedupe_lines(inv)
        w.invoices[k] = inv
        return inv

    def _dedupe_lines(self, inv: Invoice):
        """No two genuine invoices of a customer may look like duplicates (same lines within 3 days)."""
        sig = lambda i: (i.cust, i.currency, tuple((l["description"], l["quantity"], l["unit_price_minor"]) for l in i.lines))
        for other in self.w.invoices.values():
            if other.dup_of is None and sig(other) == sig(inv) and abs((other.issued_at - inv.issued_at).total_seconds()) < 5 * 86400:
                inv.lines[0]["quantity"] += 1
                inv.lines[0]["amount_minor"] = inv.lines[0]["quantity"] * inv.lines[0]["unit_price_minor"]
                inv.total = sum(l["amount_minor"] for l in inv.lines)

    def kind_of(self, issued: datetime) -> str:
        d = self.w.ldate(issued)
        if d < self.w.period_start:
            return "opening"
        if d > self.w.period_end:
            return "subsequent"
        return "period"

    def _invoices(self):
        rng, w, cfg = self.rng, self.w, self.cfg
        custs = list(w.customers.values())
        n = sample_range(rng, cfg["n_invoices"])
        days = (w.period_end - w.period_start).days
        # recurring monthly invoices: previous month (opening) and this month (period)
        for c in custs:
            if not c.recurring:
                continue
            for month_shift in (-1, 0):
                if month_shift == -1:
                    d = w.period_start - timedelta(days=1)
                    d = d.replace(day=min(c.recurring["day"], d.day))
                else:
                    d = w.period_start.replace(day=min(c.recurring["day"], w.period_end.day))
                label = "%s — %04d-%02d" % (c.recurring["description"], d.year, d.month)
                lines = [{"description": label, "quantity": 1,
                          "unit_price_minor": c.recurring["unit_price_minor"],
                          "amount_minor": c.recurring["unit_price_minor"]}]
                self.add_invoice(c, _random_local_time(rng, w, d), self.kind_of(w.local_dt(d, 12, 0)), lines, ["recurring"])
            # a second same-amount service in the same month: legitimate repeated amount
            if rng.random() < 0.5:
                d = w.period_start + timedelta(days=rng.randint(0, days))
                lines = [{"description": "%s (additional site) — %04d-%02d" % (c.recurring["description"], d.year, d.month),
                          "quantity": 1, "unit_price_minor": c.recurring["unit_price_minor"],
                          "amount_minor": c.recurring["unit_price_minor"]}]
                self.add_invoice(c, _random_local_time(rng, w, d), "period", lines, ["recurring", "repeated_amount"])
        # opening (prior period, still open at period start)
        for _ in range(max(3, n // 6)):
            d = w.period_start - timedelta(days=rng.randint(1, 45))
            self.add_invoice(rng.choice(custs), _random_local_time(rng, w, d), "opening")
        # in-period invoices
        for _ in range(n):
            d = w.period_start + timedelta(days=rng.randint(0, days))
            self.add_invoice(rng.choice(custs), _random_local_time(rng, w, d), "period")
        # subsequent-window invoices (correctly booked after the period)
        for _ in range(max(1, n // 12)):
            d = w.period_end + timedelta(days=rng.randint(1, cfg["subsequent_days"]))
            self.add_invoice(rng.choice(custs), _random_local_time(rng, w, d), "subsequent")
        # boundary distractors: correct documents right at the period edges, shown in
        # other UTC offsets so that the naive (non-local) calendar date is misleading
        for _ in range(sample_range(rng, cfg["distractors"]["boundary_documents"])):
            c = rng.choice(custs)
            far = [o for o in DOC_OFFSETS if abs(o - w.offset) >= 240] or [c.doc_offset]
            if rng.random() < 0.5:
                local = w.local_dt(w.period_end, 23, rng.randint(5, 55), rng.randint(0, 59))
            else:
                local = w.local_dt(w.period_end + timedelta(days=1), 0, rng.randint(5, 55), rng.randint(0, 59))
            inv = self.add_invoice(c, local, self.kind_of(local), tags=["boundary"])
            inv.issued_at = inv.issued_at.astimezone(tz(rng.choice(far)))
            inv.due_at = inv.due_at.astimezone(inv.issued_at.tzinfo)

    # ---------------------------------------------------------------- payments
    def add_payment(self, cust: Optional[Customer], when_local: datetime, cur: str, amount: int,
                    refs, kind: str, tags=None) -> Payment:
        rng, w = self.rng, self.w
        k = w.new_key()
        off = rng.choice([w.offset, 0, w.offset, cust.doc_offset if cust else 0])
        p = Payment(k, cust.key if cust else None, when_local.astimezone(tz(off)).replace(microsecond=0),
                    cur, amount, refs, kind, tags=list(tags or []))
        w.payments[k] = p
        return p

    def _pay_time(self, after: datetime, min_days=2, max_days=25) -> Optional[datetime]:
        rng, w = self.rng, self.w
        d = w.ldate(after) + timedelta(days=rng.randint(min_days, max_days))
        if d < w.period_start:      # opening invoices: nothing was paid before the period
            d = w.period_start + timedelta(days=rng.randint(0, 6))
        if d > w.window_end:
            return None
        return _random_local_time(rng, w, d, 7, 20)

    def paid_amount(self, inv_key: int) -> int:
        s = 0
        for p in self.w.payments.values():
            for r in p.refs or []:
                if r[0] == inv_key:
                    s += r[1]
        return s

    def _payments(self):
        rng, w, cfg = self.rng, self.w, self.cfg
        invs = [i for i in w.invoices.values() if i.kind != "subsequent"]
        invs.sort(key=lambda i: (i.issued_at, i.key))
        # split payments (two partial payments that together settle the invoice)
        split_n = sample_range(rng, cfg["distractors"]["split_payments"])
        multi_n = sample_range(rng, cfg["distractors"]["multi_invoice_payments"])
        cands = [i for i in invs if i.total >= 4 * (10 ** CURRENCY_EXPONENTS[i.currency])]
        rng.shuffle(cands)
        busy = set()
        for inv in cands[:split_n]:
            t1 = self._pay_time(inv.issued_at, 2, 10)
            if t1 is None:
                continue
            t2 = self._pay_time(t1, 1, 10)
            if t2 is None:
                continue
            a = max(1, int(inv.total * rng.uniform(0.3, 0.7)))
            cust = w.customers[inv.cust]
            self.add_payment(cust, t1, inv.currency, a, [[inv.key, a]], "settlement", ["split"])
            self.add_payment(cust, t2, inv.currency, inv.total - a, [[inv.key, inv.total - a]], "settlement", ["split"])
            busy.add(inv.key)
        # multi-invoice payments (one transfer settles two invoices of the same customer)
        by_cust = {}
        for inv in invs:
            if inv.key not in busy:
                by_cust.setdefault((inv.cust, inv.currency), []).append(inv)
        groups = [g for g in by_cust.values() if len(g) >= 2]
        rng.shuffle(groups)
        for g in groups[:multi_n]:
            k = 3 if len(g) >= 3 and rng.random() < 0.3 else 2
            chosen = rng.sample(g, k)
            later = max(i.issued_at for i in chosen)
            t = self._pay_time(later, 1, 12)
            if t is None:
                continue
            refs = sorted([[i.key, i.total] for i in chosen], key=lambda r: (w.invoices[r[0]].issued_at, r[0]))
            self.add_payment(w.customers[chosen[0].cust], t, chosen[0].currency, sum(r[1] for r in refs),
                             refs, "settlement", ["multi"])
            busy.update(i.key for i in chosen)
        # ordinary payments
        for inv in invs:
            if inv.key in busy:
                continue
            r = rng.random()
            if r < 0.32:
                continue                              # still unpaid
            t = self._pay_time(inv.issued_at)
            if t is None:
                continue
            cust = w.customers[inv.cust]
            if r < 0.36 and inv.total >= 4 * (10 ** CURRENCY_EXPONENTS[inv.currency]):
                a = max(1, int(inv.total * rng.uniform(0.2, 0.6)))   # partial, balance stays open
                self.add_payment(cust, t, inv.currency, a, [[inv.key, a]], "settlement", ["partial_open"])
            else:
                self.add_payment(cust, t, inv.currency, inv.total, [[inv.key, inv.total]], "settlement")

    def _distractor_payments(self):
        rng, w, cfg = self.rng, self.w, self.cfg
        custs = list(w.customers.values())
        # duplicate payment by the customer, legitimately refunded
        singles = [p for p in w.payments.values() if p.kind == "settlement" and p.refs and len(p.refs) == 1
                   and "split" not in p.tags and "partial_open" not in p.tags]
        rng.shuffle(singles)
        n = sample_range(rng, cfg["distractors"]["duplicate_payment_refunds"])
        for p in singles[:n]:
            loc = p.timestamp.astimezone(tz(w.offset))
            d2 = w.ldate(p.timestamp) + timedelta(days=rng.randint(0, 2))
            d3 = d2 + timedelta(days=rng.randint(2, 6))
            if d3 > w.window_end:
                continue
            cust = w.customers[p.cust]
            dup = self.add_payment(cust, _random_local_time(rng, w, d2, 7, 20), p.currency, p.amount, None, "duplicate", ["dup_payment"])
            self.add_payment(cust, _random_local_time(rng, w, d3, 7, 20), p.currency, -p.amount, None, "refund", ["refund"])
            p.tags.append("was_duplicated")
            dup.tags.append("refunded")
        # customer advances (prepayments without remittance)
        days = (w.period_end - w.period_start).days
        for _ in range(sample_range(rng, cfg["distractors"]["advances"])):
            c = rng.choice(custs)
            d = w.period_start + timedelta(days=rng.randint(0, days))
            self.add_payment(c, _random_local_time(rng, w, d, 7, 20), c.currency,
                             _price_minor(rng, c.currency, 100, 3000), None, "advance", ["advance"])
        # unidentified receipts (no customer, no remittance) -> suspense, legitimately
        for _ in range(sample_range(rng, cfg["distractors"]["unidentified_receipts"])):
            d = w.period_start + timedelta(days=rng.randint(0, days))
            self.add_payment(None, _random_local_time(rng, w, d, 7, 20), w.base,
                             _price_minor(rng, w.base, 50, 1500), None, "unidentified", ["unidentified"])

    # ---------------------------------------------------------------- decisions
    def clean_invoice_decision(self, inv: Invoice) -> InvPost:
        w = self.w
        rd = w.ldate(inv.issued_at)
        if inv.kind == "opening":
            return InvPost(w.local_dt(w.period_start, 0, 0, 0), rd, opening=True)
        return InvPost(w.same_day_delay(inv.issued_at, self.rng), rd)

    def clean_payment_decision(self, p: Payment) -> PayPost:
        w = self.w
        return PayPost(w.same_day_delay(p.timestamp, self.rng, 120), w.ldate(p.timestamp),
                       [True] * len(p.refs or []))

    def _clean_decisions_all(self):
        for inv in self.w.invoices.values():
            self.w.inv_post[inv.key] = self.clean_invoice_decision(inv)
        for p in self.w.payments.values():
            self.w.pay_post[p.key] = self.clean_payment_decision(p)

    # ---------------------------------------------------------------- noise
    def _expenses(self):
        rng, w = self.rng, self.w
        est = 0
        for inv in w.invoices.values():
            est += 2 if inv.kind == "opening" else 1 + len(inv.lines)
        for p in w.payments.values():
            est += 2 + (len(p.refs) if p.refs else 0)
        target = sample_range(rng, self.cfg["ledger_rows"])
        n = max(4, (target - est) // 2)
        days = (w.window_end - w.period_start).days
        accounts = sorted(EXPENSE_ACCOUNTS)
        vendors = sorted(w.vendors)
        for _ in range(n):
            k = w.new_key()
            d = w.period_start + timedelta(days=rng.randint(0, days))
            acc = rng.choice(accounts)
            w.expenses[k] = Expense(k, w.same_day_delay(_random_local_time(rng, w, d, 6, 21), rng),
                                    acc, _price_minor(rng, w.base, 20, 4000), rng.choice(vendors))
