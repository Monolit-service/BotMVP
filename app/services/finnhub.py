from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx
import pandas as pd

from app.models import NewsItem, SecurityQuote
from app.services.cache import TTLCache
from app.services.periods import PERIODS, date_range_for_period

FINNHUB_BASE_URL = "https://finnhub.io/api/v1"


class FinnhubError(RuntimeError):
    pass


class FinnhubClient:
    def __init__(self, api_key: str, timeout: float = 15.0, cache_ttl_seconds: int = 60) -> None:
        self.api_key = api_key.strip()
        self.timeout = timeout
        self.cache = TTLCache(ttl_seconds=cache_ttl_seconds)

    def _require_token(self) -> None:
        if not self.api_key:
            raise FinnhubError("FINNHUB_API_KEY не задан. Добавьте ключ в .env для глобальных акций и новостей.")

    async def _get_json(self, client: httpx.AsyncClient, path: str, params: dict[str, Any]) -> Any:
        self._require_token()
        response = await client.get(f"{FINNHUB_BASE_URL}{path}", params={**params, "token": self.api_key})
        response.raise_for_status()
        data = response.json()
        if isinstance(data, dict) and data.get("error"):
            raise FinnhubError(str(data["error"]))
        return data

    async def quote(self, symbol: str) -> SecurityQuote:
        symbol = symbol.upper().strip()
        cached = self.cache.get(("finnhub_quote", symbol))
        if cached:
            return cached

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            q = await self._get_json(client, "/quote", {"symbol": symbol})
            profile = {}
            try:
                profile = await self._get_json(client, "/stock/profile2", {"symbol": symbol})
            except Exception:
                profile = {}

        current = float(q.get("c") or 0) or None
        previous = float(q.get("pc") or 0) or None
        change_abs = (current - previous) if current is not None and previous else None
        change_pct = (change_abs / previous * 100) if change_abs is not None and previous else None
        ts = q.get("t")
        as_of = datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if ts else ""

        quote = SecurityQuote(
            symbol=symbol,
            name=str(profile.get("name") or symbol),
            market=str(profile.get("exchange") or "GLOBAL"),
            price=current,
            change_abs=change_abs,
            change_pct=change_pct,
            currency=str(profile.get("currency") or "USD"),
            volume=None,
            as_of=as_of,
        )
        self.cache.set(("finnhub_quote", symbol), quote)
        return quote

    async def candles(self, symbol: str, period: str) -> pd.DataFrame:
        symbol = symbol.upper().strip()
        spec = PERIODS[period]
        from_dt, to_dt = date_range_for_period(period)
        from_ts = int(from_dt.timestamp())
        to_ts = int(to_dt.timestamp())
        cached = self.cache.get(("finnhub_candles", symbol, period, from_ts // 86400, to_ts // 86400))
        if cached is not None:
            return cached.copy()

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            payload = await self._get_json(
                client,
                "/stock/candle",
                {
                    "symbol": symbol,
                    "resolution": spec.finnhub_resolution,
                    "from": from_ts,
                    "to": to_ts,
                },
            )
        if payload.get("s") != "ok":
            raise FinnhubError(f"Нет свечей Finnhub для {symbol}: status={payload.get('s')}")

        df = pd.DataFrame(
            {
                "datetime": pd.to_datetime(payload["t"], unit="s", utc=True),
                "open": payload["o"],
                "high": payload["h"],
                "low": payload["l"],
                "close": payload["c"],
                "volume": payload.get("v", []),
            }
        )
        for col in ["open", "high", "low", "close", "volume"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna(subset=["datetime", "close"]).sort_values("datetime")
        self.cache.set(("finnhub_candles", symbol, period, from_ts // 86400, to_ts // 86400), df.copy())
        return df

    async def company_news(self, symbol: str, days: int = 14, limit: int = 5) -> list[NewsItem]:
        symbol = symbol.upper().strip()
        to_dt = datetime.now(timezone.utc)
        from_dt = to_dt - pd.Timedelta(days=days)
        cached = self.cache.get(("finnhub_news", symbol, from_dt.strftime("%Y-%m-%d"), to_dt.strftime("%Y-%m-%d")))
        if cached is not None:
            return cached[:limit]

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            payload = await self._get_json(
                client,
                "/company-news",
                {"symbol": symbol, "from": from_dt.strftime("%Y-%m-%d"), "to": to_dt.strftime("%Y-%m-%d")},
            )
        items: list[NewsItem] = []
        for raw in payload[: max(limit, 20)]:
            dt = None
            if raw.get("datetime"):
                dt = datetime.fromtimestamp(int(raw["datetime"]), timezone.utc)
            items.append(
                NewsItem(
                    title=str(raw.get("headline") or "Без заголовка"),
                    url=str(raw.get("url") or ""),
                    source=str(raw.get("source") or "Finnhub"),
                    published_at=dt,
                    summary=str(raw.get("summary") or ""),
                )
            )
        self.cache.set(("finnhub_news", symbol, from_dt.strftime("%Y-%m-%d"), to_dt.strftime("%Y-%m-%d")), items)
        return items[:limit]

    async def market_snapshot(self) -> list[SecurityQuote]:
        symbols = ["SPY", "QQQ", "DIA", "GLD", "USO"]
        quotes: list[SecurityQuote] = []
        for symbol in symbols:
            try:
                quotes.append(await self.quote(symbol))
            except Exception:
                continue
        return quotes
