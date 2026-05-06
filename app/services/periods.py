from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


@dataclass(frozen=True)
class PeriodSpec:
    label: str
    days: int
    moex_interval: int
    finnhub_resolution: str


PERIODS: dict[str, PeriodSpec] = {
    "1d": PeriodSpec("1 день", 2, 10, "5"),
    "1w": PeriodSpec("1 неделя", 8, 60, "60"),
    "1m": PeriodSpec("1 месяц", 35, 24, "D"),
    "3m": PeriodSpec("3 месяца", 95, 24, "D"),
    "6m": PeriodSpec("6 месяцев", 190, 24, "D"),
    "1y": PeriodSpec("1 год", 370, 24, "D"),
    "3y": PeriodSpec("3 года", 3 * 370, 7, "W"),
    "5y": PeriodSpec("5 лет", 5 * 370, 31, "M"),
}


def normalize_period(period: str | None, default: str = "1m") -> str:
    if not period:
        return default
    p = period.strip().lower()
    aliases = {
        "d": "1d",
        "day": "1d",
        "день": "1d",
        "w": "1w",
        "week": "1w",
        "неделя": "1w",
        "m": "1m",
        "month": "1m",
        "месяц": "1m",
        "y": "1y",
        "year": "1y",
        "год": "1y",
    }
    p = aliases.get(p, p)
    if p not in PERIODS:
        supported = ", ".join(PERIODS)
        raise ValueError(f"Неизвестный период: {period}. Доступно: {supported}")
    return p


def date_range_for_period(period: str) -> tuple[datetime, datetime]:
    spec = PERIODS[period]
    to_dt = datetime.now(timezone.utc)
    from_dt = to_dt - timedelta(days=spec.days)
    return from_dt, to_dt
