from __future__ import annotations

import csv
from datetime import date, datetime, timedelta
from pathlib import Path

from app.models import CorporateEvent
from app.services.cache import TTLCache


class CorporateEventsClient:
    """Reads a lightweight corporate events calendar from CSV.

    CSV columns: date,symbol,category,title,source_url,importance
    date must be YYYY-MM-DD. The file is optional; the bot works without it.
    """

    def __init__(self, csv_path: str, cache_ttl_seconds: int = 300) -> None:
        self.csv_path = csv_path
        self.cache = TTLCache(ttl_seconds=cache_ttl_seconds)

    def _load(self) -> list[CorporateEvent]:
        cached = self.cache.get(("events", self.csv_path))
        if cached is not None:
            return list(cached)
        path = Path(self.csv_path)
        if not path.exists():
            self.cache.set(("events", self.csv_path), [])
            return []

        events: list[CorporateEvent] = []
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                try:
                    event_date = datetime.strptime(str(row.get("date", "")).strip(), "%Y-%m-%d").date()
                except ValueError:
                    continue
                symbol = str(row.get("symbol", "")).upper().strip()
                if not symbol:
                    continue
                events.append(
                    CorporateEvent(
                        date=event_date,
                        symbol=symbol,
                        category=str(row.get("category", "event") or "event").strip(),
                        title=str(row.get("title", "") or "").strip(),
                        source_url=str(row.get("source_url", "") or "").strip(),
                        importance=str(row.get("importance", "normal") or "normal").strip(),
                    )
                )
        events.sort(key=lambda item: (item.date, item.symbol, item.category))
        self.cache.set(("events", self.csv_path), list(events))
        return events

    def upcoming_for_symbol(self, symbol: str, days_ahead: int = 30, limit: int = 8) -> list[CorporateEvent]:
        symbol = symbol.upper().strip()
        today = date.today()
        till = today + timedelta(days=days_ahead)
        events = [e for e in self._load() if e.symbol == symbol and today <= e.date <= till]
        return events[:limit]

    def calendar(self, days_ahead: int = 14, limit: int = 20) -> list[CorporateEvent]:
        today = date.today()
        till = today + timedelta(days=days_ahead)
        events = [e for e in self._load() if today <= e.date <= till]
        return events[:limit]
