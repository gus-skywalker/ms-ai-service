from __future__ import annotations

from datetime import date, datetime
from typing import List


def parse_iso_date(value: str) -> date:
    return datetime.fromisoformat(value).date()


def month_key(d: date) -> str:
    return d.strftime("%Y-%m")


def future_month_keys(start: date, months: int) -> List[str]:
    keys: List[str] = []
    year = start.year
    month = start.month
    for _ in range(months):
        keys.append(f"{year:04d}-{month:02d}")
        month += 1
        if month > 12:
            month = 1
            year += 1
    return keys

