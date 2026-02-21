import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from django.utils import timezone


@dataclass
class DateRange:
    start: datetime
    end: datetime  # end exclusive (lebih aman untuk query)


def _start_of_day(d: date, tz):
    return timezone.make_aware(datetime(d.year, d.month, d.day, 0, 0, 0), tz)


def _next_day_start(d: date, tz):
    return _start_of_day(d + timedelta(days=1), tz)


def parse_date_range(text: str) -> tuple[str, DateRange]:
    """
    Return (range_label, DateRange)
    Support:
      - today / hari ini
      - yesterday / kemarin
      - last 7 days / 7 hari terakhir / minggu ini (sederhana)
      - this month / bulan ini
      - custom ISO: 2026-02-01 to 2026-02-10
      - custom Indo: 1/2/2026 sampai 10/2/2026 (dd/mm/yyyy)
    """
    t = (text or "").lower().strip()
    tz = timezone.get_current_timezone()

    today = timezone.localdate()

    # ✅ today
    if any(k in t for k in ["hari ini", "today"]):
        s = _start_of_day(today, tz)
        e = _next_day_start(today, tz)
        return "today", DateRange(s, e)

    # ✅ yesterday
    if any(k in t for k in ["kemarin", "yesterday"]):
        y = today - timedelta(days=1)
        s = _start_of_day(y, tz)
        e = _next_day_start(y, tz)
        return "yesterday", DateRange(s, e)

    # ✅ last 7 days
    if any(k in t for k in ["last 7", "7 hari", "7 hari terakhir", "last seven"]):
        start_d = today - timedelta(days=6)  # termasuk hari ini
        s = _start_of_day(start_d, tz)
        e = _next_day_start(today, tz)
        return "last_7_days", DateRange(s, e)

    # ✅ this month
    if any(k in t for k in ["bulan ini", "this month"]):
        first = today.replace(day=1)
        s = _start_of_day(first, tz)
        # next month
        if first.month == 12:
            nm = date(first.year + 1, 1, 1)
        else:
            nm = date(first.year, first.month + 1, 1)
        e = _start_of_day(nm, tz)
        return "this_month", DateRange(s, e)

    # ✅ ISO custom: YYYY-MM-DD to YYYY-MM-DD
    m = re.search(r"(\d{4}-\d{2}-\d{2})\s*(to|sampai|-)\s*(\d{4}-\d{2}-\d{2})", t)
    if m:
        a = date.fromisoformat(m.group(1))
        b = date.fromisoformat(m.group(3))
        if b < a:
            a, b = b, a
        s = _start_of_day(a, tz)
        e = _next_day_start(b, tz)  # inclusive end date
        return "custom_range", DateRange(s, e)

    # ✅ dd/mm/yyyy sampai dd/mm/yyyy
    m2 = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})\s*(to|sampai|-)\s*(\d{1,2})/(\d{1,2})/(\d{4})", t)
    if m2:
        d1 = date(int(m2.group(3)), int(m2.group(2)), int(m2.group(1)))
        d2 = date(int(m2.group(7)), int(m2.group(6)), int(m2.group(5)))
        if d2 < d1:
            d1, d2 = d2, d1
        s = _start_of_day(d1, tz)
        e = _next_day_start(d2, tz)
        return "custom_range", DateRange(s, e)

    # default: today
    s = _start_of_day(today, tz)
    e = _next_day_start(today, tz)
    return "today", DateRange(s, e)