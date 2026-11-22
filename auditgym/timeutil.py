"""Timezone helpers based on fixed UTC offsets (deterministic, no tz database needed)."""

from datetime import date, datetime, timedelta, timezone


def tz(offset_minutes: int) -> timezone:
    return timezone(timedelta(minutes=offset_minutes))


def offset_str(offset_minutes: int) -> str:
    sign = "+" if offset_minutes >= 0 else "-"
    m = abs(offset_minutes)
    return "%s%02d:%02d" % (sign, m // 60, m % 60)


def iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def parse_iso(s: str) -> datetime:
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        raise ValueError("timestamp without UTC offset: %r" % s)
    return dt


def local_date(dt: datetime, offset_minutes: int) -> date:
    return dt.astimezone(tz(offset_minutes)).date()


def at_local(d: date, hour: int, minute: int, second: int, offset_minutes: int) -> datetime:
    return datetime(d.year, d.month, d.day, hour, minute, second, tzinfo=tz(offset_minutes))


def last_day_of_month(year: int, month: int) -> date:
    if month == 12:
        return date(year, 12, 31)
    return date(year, month + 1, 1) - timedelta(days=1)
