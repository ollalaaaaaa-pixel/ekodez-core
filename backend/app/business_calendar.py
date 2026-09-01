from datetime import date, timedelta


class CalendarRangeError(ValueError):
    pass


SUPPORTED_YEARS = frozenset({2025, 2026, 2027})

# Government transfers are recorded explicitly. Ordinary Saturdays and Sundays
# are handled by is_business_day(). The 2027 transfer decree was not published
# as of 2026-09-01; its table therefore contains statutory holidays and the
# automatic next-working-day transfers only and must be refreshed after the
# official decree is issued.
NON_WORKING_DAYS = frozenset(
    {
        # 2025
        *(date(2025, 1, day) for day in range(1, 9)),
        date(2025, 5, 1),
        date(2025, 5, 2),
        date(2025, 5, 8),
        date(2025, 5, 9),
        date(2025, 6, 12),
        date(2025, 6, 13),
        date(2025, 11, 3),
        date(2025, 11, 4),
        date(2025, 12, 31),
        # 2026 — Government Resolution No. 1466 of 24 September 2025.
        *(date(2026, 1, day) for day in range(1, 10)),
        date(2026, 2, 23),
        date(2026, 3, 8),
        date(2026, 3, 9),
        date(2026, 5, 1),
        date(2026, 5, 9),
        date(2026, 5, 11),
        date(2026, 6, 12),
        date(2026, 11, 4),
        date(2026, 12, 31),
        # 2027 statutory calendar; see module note above.
        *(date(2027, 1, day) for day in range(1, 9)),
        date(2027, 2, 23),
        date(2027, 3, 8),
        date(2027, 5, 1),
        date(2027, 5, 3),
        date(2027, 5, 9),
        date(2027, 5, 10),
        date(2027, 6, 12),
        date(2027, 6, 14),
        date(2027, 11, 4),
    }
)

WORKING_WEEKEND_DAYS = frozenset({date(2025, 11, 1)})


def is_business_day(day: date) -> bool:
    if day.year not in SUPPORTED_YEARS:
        raise CalendarRangeError("business calendar supports 2025-2027 only")
    if day in WORKING_WEEKEND_DAYS:
        return True
    if day in NON_WORKING_DAYS:
        return False
    return day.weekday() < 5


def add_business_days(day: date, count: int) -> date:
    if count < 0:
        raise ValueError("business day count cannot be negative")
    if day.year not in SUPPORTED_YEARS:
        raise CalendarRangeError("business calendar supports 2025-2027 only")
    current = day
    remaining = count
    while remaining:
        current += timedelta(days=1)
        if is_business_day(current):
            remaining -= 1
    return current
