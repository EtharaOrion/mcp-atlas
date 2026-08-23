from fastmcp import FastMCP
from datetime import date, datetime, timedelta
import calendar
from typing import Dict, List, Optional

mcp = FastMCP("CalendarMathServer")


def _parse_date(s: str) -> date:
    return date.fromisoformat(s)


def _fmt(d: date) -> str:
    return d.isoformat()


@mcp.tool
async def business_days(start: str, end: str, holidays: Optional[List[str]] = None) -> int:
    """Count business days (Mon-Fri) between `start` and `end` inclusive, minus `holidays`."""
    d0 = _parse_date(start)
    d1 = _parse_date(end)
    holis = set(holidays or [])
    if d1 < d0:
        d0, d1 = d1, d0
    n = 0
    cur = d0
    while cur <= d1:
        if cur.weekday() < 5 and cur.isoformat() not in holis:
            n += 1
        cur += timedelta(days=1)
    return n


@mcp.tool
async def add_business_days(start: str, n: int, holidays: Optional[List[str]] = None) -> str:
    """Add `n` business days to `start` (skipping weekends and `holidays`). `n` can be negative."""
    d = _parse_date(start)
    step = 1 if n >= 0 else -1
    holis = set(holidays or [])
    left = abs(n)
    while left > 0:
        d += timedelta(days=step)
        if d.weekday() < 5 and d.isoformat() not in holis:
            left -= 1
    return _fmt(d)


@mcp.tool
async def is_business_day(date_str: str, holidays: Optional[List[str]] = None) -> bool:
    """Return True if `date_str` is Mon-Fri and not in `holidays`."""
    d = _parse_date(date_str)
    return d.weekday() < 5 and date_str not in set(holidays or [])


@mcp.tool
async def next_business_day(date_str: str, holidays: Optional[List[str]] = None) -> str:
    """Return the next business day strictly after `date_str`."""
    return await add_business_days.__wrapped__(date_str, 1, holidays)


@mcp.tool
async def previous_business_day(date_str: str, holidays: Optional[List[str]] = None) -> str:
    """Return the previous business day strictly before `date_str`."""
    return await add_business_days.__wrapped__(date_str, -1, holidays)


@mcp.tool
async def week_number(date_str: str) -> int:
    """Return the ISO 8601 week number (1-53) of `date_str`."""
    return _parse_date(date_str).isocalendar()[1]


@mcp.tool
async def day_of_week(date_str: str) -> str:
    """Return the weekday name (Monday, Tuesday, ...) of `date_str`."""
    return _parse_date(date_str).strftime("%A")


@mcp.tool
async def is_weekend(date_str: str) -> bool:
    """Return True if `date_str` is Saturday or Sunday."""
    return _parse_date(date_str).weekday() >= 5


@mcp.tool
async def days_between(a: str, b: str) -> int:
    """Return the number of days between two ISO dates (signed: b - a)."""
    return (_parse_date(b) - _parse_date(a)).days


@mcp.tool
async def date_add(date_str: str, days: int = 0, weeks: int = 0, months: int = 0, years: int = 0) -> str:
    """Add days/weeks/months/years to `date_str`. Months and years use naive calendar arithmetic."""
    d = _parse_date(date_str)
    d += timedelta(days=days, weeks=weeks)
    y = d.year + years
    m = d.month + months
    while m > 12:
        m -= 12
        y += 1
    while m < 1:
        m += 12
        y -= 1
    last = calendar.monthrange(y, m)[1]
    return _fmt(date(y, m, min(d.day, last)))


@mcp.tool
async def date_range(start: str, end: str, step_days: int = 1) -> List[str]:
    """Return the list of ISO dates from `start` to `end` inclusive, stepping by `step_days`."""
    d0 = _parse_date(start)
    d1 = _parse_date(end)
    out: List[str] = []
    cur = d0
    while cur <= d1:
        out.append(_fmt(cur))
        cur += timedelta(days=step_days)
    return out


@mcp.tool
async def month_start(date_str: str) -> str:
    """Return the first day of the same month as `date_str`."""
    d = _parse_date(date_str)
    return _fmt(date(d.year, d.month, 1))


@mcp.tool
async def month_end(date_str: str) -> str:
    """Return the last day of the same month as `date_str`."""
    d = _parse_date(date_str)
    last = calendar.monthrange(d.year, d.month)[1]
    return _fmt(date(d.year, d.month, last))


@mcp.tool
async def quarter(date_str: str) -> int:
    """Return the calendar quarter (1-4) of `date_str`."""
    return (_parse_date(date_str).month - 1) // 3 + 1


@mcp.tool
async def fiscal_year(date_str: str, start_month: int = 4) -> int:
    """Return the fiscal year of `date_str` given the fiscal-year `start_month`."""
    d = _parse_date(date_str)
    return d.year if d.month >= start_month else d.year - 1


@mcp.tool
async def age(birth: str, at: Optional[str] = None) -> int:
    """Return the age in whole years on date `at` (default today per session anchor 2026-01-05)."""
    b = _parse_date(birth)
    ref = _parse_date(at) if at else date(2026, 1, 5)
    years = ref.year - b.year - ((ref.month, ref.day) < (b.month, b.day))
    return years


@mcp.tool
async def easter(year: int) -> str:
    """Return the ISO date of Western Easter Sunday for `year` (Gauss algorithm)."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    ell = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * ell) // 451
    month = (h + ell - 7 * m + 114) // 31
    day = ((h + ell - 7 * m + 114) % 31) + 1
    return _fmt(date(year, month, day))


@mcp.tool
async def us_federal_holidays(year: int) -> List[Dict[str, str]]:
    """Return a list of {date, name} for US federal holidays in `year` (fixed + nth-weekday rules)."""
    def nth_weekday(month: int, weekday: int, n: int) -> date:
        d = date(year, month, 1)
        offset = (weekday - d.weekday()) % 7
        return d + timedelta(days=offset + 7 * (n - 1))

    def last_weekday(month: int, weekday: int) -> date:
        last_day = calendar.monthrange(year, month)[1]
        d = date(year, month, last_day)
        offset = (d.weekday() - weekday) % 7
        return d - timedelta(days=offset)

    out = [
        {"date": _fmt(date(year, 1, 1)), "name": "New Year's Day"},
        {"date": _fmt(nth_weekday(1, 0, 3)), "name": "Martin Luther King Jr. Day"},
        {"date": _fmt(nth_weekday(2, 0, 3)), "name": "Presidents' Day"},
        {"date": _fmt(last_weekday(5, 0)), "name": "Memorial Day"},
        {"date": _fmt(date(year, 6, 19)), "name": "Juneteenth"},
        {"date": _fmt(date(year, 7, 4)), "name": "Independence Day"},
        {"date": _fmt(nth_weekday(9, 0, 1)), "name": "Labor Day"},
        {"date": _fmt(nth_weekday(10, 0, 2)), "name": "Columbus Day"},
        {"date": _fmt(date(year, 11, 11)), "name": "Veterans Day"},
        {"date": _fmt(nth_weekday(11, 3, 4)), "name": "Thanksgiving"},
        {"date": _fmt(date(year, 12, 25)), "name": "Christmas Day"},
    ]
    return out


@mcp.tool
async def iso_week_dates(year: int, week: int) -> List[str]:
    """Return the 7 ISO dates (Mon-Sun) of a given `year` and ISO `week` number."""
    jan4 = date(year, 1, 4)
    jan4_start = jan4 - timedelta(days=jan4.isocalendar()[2] - 1)
    monday = jan4_start + timedelta(weeks=week - 1)
    return [_fmt(monday + timedelta(days=i)) for i in range(7)]


@mcp.tool
async def month_calendar(year: int, month: int) -> List[List[int]]:
    """Return the month as a matrix of week rows (Mon-Sun), 0 for out-of-month cells."""
    return calendar.Calendar(firstweekday=0).monthdayscalendar(year, month)


@mcp.tool
async def days_in_month(year: int, month: int) -> int:
    """Return the number of days in the given `year` and `month`."""
    return calendar.monthrange(year, month)[1]


@mcp.tool
async def is_leap_year(year: int) -> bool:
    """Return True if `year` is a Gregorian leap year."""
    return calendar.isleap(year)


@mcp.tool
async def format_date(date_str: str, fmt: str = "%Y-%m-%d") -> str:
    """Reformat `date_str` (ISO) using an strftime format string."""
    return _parse_date(date_str).strftime(fmt)


@mcp.tool
async def parse_date(text: str, fmt: str = "%Y-%m-%d") -> str:
    """Parse `text` with the given strftime format and return an ISO date string."""
    return datetime.strptime(text, fmt).date().isoformat()


@mcp.tool
async def cron_next(cron_expr: str, from_date: str) -> str:
    """Return the next ISO date matching a 5-field cron '`m h dom mon dow`' (naive, day-granularity)."""
    parts = cron_expr.split()
    if len(parts) != 5:
        raise ValueError("expected 5 cron fields")
    _, _, dom_s, mon_s, dow_s = parts

    def match(field: str, value: int, lo: int, hi: int) -> bool:
        if field == "*":
            return True
        for part in field.split(","):
            if "/" in part:
                base, step = part.split("/")
                if base == "*":
                    return (value - lo) % int(step) == 0
            if "-" in part:
                a, b = part.split("-")
                if int(a) <= value <= int(b):
                    return True
            elif part.isdigit() and int(part) == value:
                return True
        return False

    d = _parse_date(from_date) + timedelta(days=1)
    for _ in range(400):
        if match(dom_s, d.day, 1, 31) and match(mon_s, d.month, 1, 12) and match(dow_s, d.weekday(), 0, 6):
            return _fmt(d)
        d += timedelta(days=1)
    raise ValueError("no match within one year")
