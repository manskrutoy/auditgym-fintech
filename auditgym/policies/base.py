"""Policy interface and a helper that pages through all public tables."""

from datetime import datetime, timedelta, timezone

from .. import money


class Policy:
    name = "base"

    def reset(self, obs):
        raise NotImplementedError

    def act(self, obs):
        raise NotImplementedError


def parse_offset(s):
    sign = 1 if s[0] == "+" else -1
    h, m = s[1:].split(":")
    return timezone(sign * timedelta(hours=int(h), minutes=int(m)))


class Reader:
    """Reads every table page by page; leaves `reserve` steps for submit."""

    ORDER = ("invoices", "payments", "fx", "ledger")

    def __init__(self, first_obs, reserve=1):
        self.episode_id = first_obs["episode_id"]
        self.manifest = first_obs["manifest"]
        self.policy = first_obs["policy"]
        self.data = {t: [] for t in self.ORDER}
        self.queue = list(self.ORDER)
        self.cursor = None
        self.reserve = reserve
        self.pending = None
        self.complete = False

    def feed(self, obs):
        """Consume the result of our last list_records call."""
        if self.pending is None:
            return
        res = obs.get("result")
        if res and "records" in res:
            self.data[res["table"]].extend(res["records"])
            self.cursor = res["next_cursor"]
            if self.cursor is None:
                self.queue.pop(0)
        self.pending = None

    def next_action(self, remaining):
        if not self.queue or remaining <= self.reserve:
            self.complete = not self.queue
            return None
        self.pending = True
        return {"action": "list_records", "table": self.queue[0], "cursor": self.cursor, "limit": 50}


class Books:
    """Indexes over the public records + policy helpers (no access to truth)."""

    def __init__(self, reader: Reader):
        m, p = reader.manifest, reader.policy
        self.base = m["base_currency"]
        self.tz = parse_offset(m["timezone"])
        self.pstart = m["period_start"]
        self.pend = m["period_end"]
        self.rounding = p["fx"]["rounding"]
        d = reader.data
        self.invoices = d["invoices"]
        self.payments = d["payments"]
        self.ledger = d["ledger"]
        self.fx = {}
        for r in d["fx"]:
            self.fx.setdefault(r["source_currency"], []).append((r["date"], r["rate"], r["fx_id"]))
        for v in self.fx.values():
            v.sort()
        self.inv_by_id = {i["invoice_id"]: i for i in self.invoices}
        self.ar_debit = {}
        self.ar_credit = {}
        self.suspense = {}
        self.cash = {}
        for r in self.ledger:
            if r["account"] == "1100" and r["debit_minor"] > 0 and r["invoice_id"]:
                self.ar_debit.setdefault(r["invoice_id"], []).append(r)
            if r["account"] == "1100" and r["credit_minor"] > 0 and r["payment_id"]:
                self.ar_credit.setdefault((r["payment_id"], r["invoice_id"]), []).append(r)
            if r["account"] == "1190" and r["payment_id"]:
                self.suspense.setdefault(r["payment_id"], []).append(r)
            if r["account"] == "1000" and r["payment_id"]:
                self.cash.setdefault(r["payment_id"], []).append(r)

    def local_date(self, ts):
        return datetime.fromisoformat(ts).astimezone(self.tz).date().isoformat()

    def in_period(self, d):
        return self.pstart <= d <= self.pend

    def rate_for(self, cur, d):
        best = None
        for date, rate, fid in self.fx.get(cur, []):
            if date <= d:
                best = (rate, fid)
            else:
                break
        return best

    def to_base(self, amount, cur, d):
        if cur == self.base:
            return amount, None
        r = self.rate_for(cur, d)
        if r is None:
            return None, None
        return money.convert_minor(amount, cur, self.base, r[0], self.rounding), r[1]


def finding(t, affected, amount, currency, evidence, explanation):
    ev = []
    for e in evidence:
        if e and e not in ev:
            ev.append(e)
    return {"type": t, "affected_ids": sorted(affected), "claimed_amount_minor": int(amount),
            "currency": currency, "evidence_ids": ev[:10], "explanation": explanation[:1000]}
