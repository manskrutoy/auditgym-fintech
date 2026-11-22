"""Exact money and FX arithmetic (integers in minor units, decimal-string rates)."""

from decimal import Decimal, ROUND_HALF_EVEN, ROUND_HALF_UP, localcontext

from .constants import CURRENCY_EXPONENTS

ROUNDING_MODES = {"half_even": ROUND_HALF_EVEN, "half_up": ROUND_HALF_UP}


def exponent(currency: str) -> int:
    return CURRENCY_EXPONENTS[currency]


def _q(value: Decimal, rounding: str) -> int:
    return int(value.quantize(Decimal(1), rounding=ROUNDING_MODES[rounding]))


def convert_minor(amount_minor: int, src: str, dst: str, rate, rounding: str) -> int:
    """Convert integer minor units of `src` into minor units of `dst`.

    `rate` is the price of ONE major unit of src expressed in major units of dst,
    given as a decimal string (as published in fx.csv).
    """
    if src == dst:
        return int(amount_minor)
    with localcontext() as ctx:
        ctx.prec = 60
        major = Decimal(int(amount_minor)).scaleb(-exponent(src))
        target_major = major * Decimal(str(rate))
        return _q(target_major.scaleb(exponent(dst)), rounding)


def prorate(total_minor: int, part: int, whole: int, rounding: str) -> int:
    """total * part / whole rounded with the episode rounding rule."""
    if whole == 0:
        raise ZeroDivisionError("prorate with whole == 0")
    with localcontext() as ctx:
        ctx.prec = 60
        return _q(Decimal(int(total_minor)) * Decimal(int(part)) / Decimal(int(whole)), rounding)


def format_rate(value: float) -> str:
    """Publish a rate as a decimal string with 7 significant digits."""
    d = Decimal(repr(value))
    q = Decimal(1).scaleb(d.adjusted() - 6)
    d = d.quantize(q, rounding=ROUND_HALF_EVEN)
    s = format(d, "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s
