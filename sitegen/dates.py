"""Dates that may be partial: you might only remember the year you saw a painting."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime

PARTIAL = re.compile(r"(\d{4})(?:-(\d{1,2})(?:-(\d{1,2}))?)?")


@dataclass(frozen=True)
class When:
    day: date  # first day of the period
    precision: str  # "day" | "month" | "year"

    @property
    def iso(self) -> str:
        if self.precision == "year":
            return f"{self.day:%Y}"
        if self.precision == "month":
            return f"{self.day:%Y-%m}"
        return self.day.isoformat()

    @property
    def short(self) -> str:
        """For lists grouped by year: '12 Oct', 'Oct', or ''."""
        if self.precision == "year":
            return ""
        if self.precision == "month":
            return f"{self.day:%b}"
        return f"{self.day.day} {self.day:%b}"

    @property
    def long(self) -> str:
        if self.precision == "year":
            return f"{self.day:%Y}"
        if self.precision == "month":
            return f"{self.day:%B %Y}"
        return f"{self.day.day} {self.day:%B %Y}"

    @property
    def compact(self) -> str:
        """For tables: '12 Oct 2026', 'Oct 2026', '2026'."""
        if self.precision == "year":
            return f"{self.day:%Y}"
        if self.precision == "month":
            return f"{self.day:%b %Y}"
        return f"{self.day.day} {self.day:%b %Y}"


def parse_when(value) -> When | None:
    """Accept YAML dates/datetimes, years as ints, and 'YYYY', 'YYYY-MM', 'YYYY-MM-DD' strings."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return When(value.date(), "day")
    if isinstance(value, date):
        return When(value, "day")
    if isinstance(value, int) and 1000 <= value <= 9999:
        return When(date(value, 1, 1), "year")
    text = str(value).strip()
    try:
        return When(datetime.fromisoformat(text).date(), "day")
    except ValueError:
        pass
    m = PARTIAL.fullmatch(text)
    if not m:
        raise ValueError(f"unrecognised date {value!r} (use YYYY-MM-DD, YYYY-MM or YYYY)")
    year, month, day = int(m[1]), int(m[2] or 1), int(m[3] or 1)
    precision = "day" if m[3] else "month" if m[2] else "year"
    return When(date(year, month, day), precision)
