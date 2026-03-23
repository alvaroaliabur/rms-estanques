"""Utility helpers — date formatting, clamping, etc."""

from datetime import datetime, timedelta


def fmt(d):
    """Format date as YYYY-MM-DD string."""
    if isinstance(d, str):
        return d[:10]
    return d.strftime("%Y-%m-%d")


def parse_date(s):
    """Parse YYYY-MM-DD string to date."""
    if isinstance(s, datetime):
        return s.date() if hasattr(s, 'date') else s
    return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()


def days_until(fecha):
    """Days from today to a given date."""
    from datetime import date
    today = date.today()
    target = parse_date(fecha)
    return (target - today).days


def add_days(d, n):
    """Add n days to a date."""
    if isinstance(d, str):
        d = parse_date(d)
    return d + timedelta(days=n)


def clamp(lo, val, hi):
    """Clamp val between lo and hi."""
    return max(lo, min(hi, val))


def is_weekend(d):
    """Friday(4) or Saturday(5) → True."""
    if isinstance(d, str):
        d = parse_date(d)
    return d.weekday() in (4, 5)


def get_month(d):
    """Extract month number from date or string."""
    if isinstance(d, str):
        return int(d[5:7])
    return d.month
