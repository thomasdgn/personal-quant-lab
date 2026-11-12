"""Séances Euronext Paris standard (hors fermetures exceptionnelles)."""
from datetime import date, timedelta

import pandas as pd


def easter(year: int) -> date:
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    g = (b - (b + 8) // 25 + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    correction = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * correction) // 451
    n = h + correction - 7 * m + 114
    return date(year, n // 31, n % 31 + 1)


def is_session(day) -> bool:
    day = pd.Timestamp(day).date()
    spring = easter(day.year)
    holidays = {date(day.year, 1, 1), date(day.year, 5, 1), date(day.year, 12, 25), date(day.year, 12, 26),
                spring - timedelta(days=2), spring + timedelta(days=1)}
    return day.weekday() < 5 and day not in holidays


def last_session_of_month(month) -> pd.Timestamp:
    day = pd.Timestamp(month).normalize() + pd.offsets.MonthEnd(0)
    while not is_session(day):
        day -= pd.Timedelta(days=1)
    return day


def session_age(quote_date, as_of) -> int:
    quote, now = pd.Timestamp(quote_date).normalize(), pd.Timestamp(as_of).normalize()
    if quote > now:
        raise ValueError("Cours postérieur à la date de décision.")
    return sum(is_session(d) for d in pd.date_range(quote + pd.Timedelta(days=1), now, freq="D"))
