from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

import pandas as pd


@dataclass(slots=True)
class SecurityQuote:
    symbol: str
    name: str
    market: str
    price: Optional[float] = None
    change_abs: Optional[float] = None
    change_pct: Optional[float] = None
    currency: Optional[str] = None
    volume: Optional[float] = None
    as_of: Optional[str] = None


@dataclass(slots=True)
class NewsItem:
    title: str
    url: str
    source: str = ""
    published_at: Optional[datetime] = None
    summary: str = ""


@dataclass(slots=True)
class ChartData:
    symbol: str
    period: str
    currency: str | None
    candles: pd.DataFrame


@dataclass(slots=True)
class CorporateEvent:
    date: date
    symbol: str
    category: str
    title: str
    source_url: str = ""
    importance: str = "normal"


@dataclass(slots=True)
class PriceAlert:
    id: int
    telegram_user_id: int
    symbol: str
    market: str
    metric: str
    operator: str
    threshold: float
    active: bool = True
    created_at: str = ""
    triggered_at: str | None = None
    last_value: float | None = None
