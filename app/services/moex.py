from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx
import pandas as pd

from app.models import SecurityQuote
from app.services.cache import TTLCache
from app.services.periods import PERIODS, date_range_for_period

MOEX_BASE_URL = "https://iss.moex.com/iss"


class MoexError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class MoexBoard:
    secid: str
    engine: str
    market: str
    boardid: str
    title: str = ""


def _table_to_dicts(payload: dict[str, Any], table_name: str) -> list[dict[str, Any]]:
    table = payload.get(table_name, {})
    columns = table.get("columns", [])
    rows = table.get("data", [])
    return [dict(zip(columns, row)) for row in rows]


class MoexClient:
    """Small async wrapper around MOEX ISS JSON endpoints."""

    def __init__(self, timeout: float = 15.0, cache_ttl_seconds: int = 60) -> None:
        self.timeout = timeout
        self.cache = TTLCache(ttl_seconds=cache_ttl_seconds)

    async def _get_json(self, client: httpx.AsyncClient, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{MOEX_BASE_URL}{path}"
        response = await client.get(url, params=params)
        response.raise_for_status()
        return response.json()

    async def lookup(self, secid: str) -> MoexBoard:
        secid = secid.upper().strip().removeprefix("MOEX:").removesuffix(".ME")
        cached = self.cache.get(("moex_lookup", secid))
        if cached:
            return cached

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            payload = await self._get_json(
                client,
                f"/securities/{secid}.json",
                params={"iss.meta": "off", "iss.only": "boards,description"},
            )

        boards = _table_to_dicts(payload, "boards")
        if not boards:
            raise MoexError(f"Инструмент {secid} не найден на MOEX")

        # Prefer primary board, then the usual equity board, then the first available board.
        primary = [b for b in boards if str(b.get("is_primary", "")).lower() in {"1", "true"}]
        tqbr = [b for b in boards if b.get("boardid") == "TQBR"]
        selected = (primary or tqbr or boards)[0]
        board = MoexBoard(
            secid=secid,
            engine=str(selected.get("engine", "stock")),
            market=str(selected.get("market", "shares")),
            boardid=str(selected.get("boardid", "TQBR")),
            title=str(selected.get("title") or selected.get("board_title") or ""),
        )
        self.cache.set(("moex_lookup", secid), board)
        return board

    async def quote(self, secid: str) -> SecurityQuote:
        board = await self.lookup(secid)
        cached = self.cache.get(("moex_quote", board.secid, board.boardid))
        if cached:
            return cached

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            payload = await self._get_json(
                client,
                f"/engines/{board.engine}/markets/{board.market}/boards/{board.boardid}/securities/{board.secid}.json",
                params={"iss.meta": "off", "iss.only": "securities,marketdata"},
            )

        securities = _table_to_dicts(payload, "securities")
        marketdata = _table_to_dicts(payload, "marketdata")
        sec = securities[0] if securities else {}
        md = marketdata[0] if marketdata else {}

        def pick_float(*names: str) -> float | None:
            for name in names:
                value = md.get(name) if name in md else sec.get(name)
                if value in (None, ""):
                    continue
                try:
                    return float(value)
                except (TypeError, ValueError):
                    continue
            return None

        quote = SecurityQuote(
            symbol=board.secid,
            name=str(sec.get("SECNAME") or sec.get("SHORTNAME") or board.secid),
            market=f"MOEX {board.market}/{board.boardid}",
            price=pick_float("LAST", "LCURRENTPRICE", "MARKETPRICE2", "PREVWAPRICE", "PREVPRICE"),
            change_abs=pick_float("CHANGE"),
            change_pct=pick_float("LASTTOPREVPRICE", "LASTCHANGEPRCNT", "CHANGEPRCNT"),
            currency=str(sec.get("CURRENCYID") or sec.get("FACEUNIT") or "RUB"),
            volume=pick_float("VOLTODAY", "VALTODAY", "VOLUME"),
            as_of=str(md.get("SYSTIME") or md.get("TIME") or ""),
        )
        self.cache.set(("moex_quote", board.secid, board.boardid), quote)
        return quote

    async def candles(self, secid: str, period: str) -> pd.DataFrame:
        board = await self.lookup(secid)
        period_spec = PERIODS[period]
        from_dt, to_dt = date_range_for_period(period)
        params_base = {
            "from": from_dt.strftime("%Y-%m-%d"),
            "till": to_dt.strftime("%Y-%m-%d"),
            "interval": period_spec.moex_interval,
            "iss.meta": "off",
        }
        cached = self.cache.get(("moex_candles", board.secid, board.boardid, period, params_base["from"], params_base["till"]))
        if cached is not None:
            return cached.copy()

        rows: list[dict[str, Any]] = []
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            start = 0
            for _ in range(20):
                params = {**params_base, "start": start}
                try:
                    payload = await self._get_json(
                        client,
                        f"/engines/{board.engine}/markets/{board.market}/boards/{board.boardid}/securities/{board.secid}/candles.json",
                        params=params,
                    )
                except httpx.HTTPStatusError:
                    payload = await self._get_json(
                        client,
                        f"/engines/{board.engine}/markets/{board.market}/securities/{board.secid}/candles.json",
                        params=params,
                    )
                page = _table_to_dicts(payload, "candles")
                rows.extend(page)
                if len(page) < 500:
                    break
                start += len(page)

        if not rows:
            raise MoexError(f"Нет свечей для {board.secid} за период {period}")

        df = pd.DataFrame(rows)
        for col in ["open", "close", "high", "low", "value", "volume"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        if "begin" in df.columns:
            df["datetime"] = pd.to_datetime(df["begin"], errors="coerce")
        elif "end" in df.columns:
            df["datetime"] = pd.to_datetime(df["end"], errors="coerce")
        df = df.dropna(subset=["datetime", "close"]).sort_values("datetime")
        self.cache.set(("moex_candles", board.secid, board.boardid, period, params_base["from"], params_base["till"]), df.copy())
        return df


    async def screener(self, kind: str = "gainers", limit: int = 10) -> list[SecurityQuote]:
        """Top MOEX shares by daily change or turnover on the main TQBR board."""
        kind = kind.lower().strip()
        cache_key = ("moex_screener", kind, limit)
        cached = self.cache.get(cache_key)
        if cached:
            return cached

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            payload = await self._get_json(
                client,
                "/engines/stock/markets/shares/boards/TQBR/securities.json",
                params={"iss.meta": "off", "iss.only": "securities,marketdata"},
            )

        securities = {row.get("SECID"): row for row in _table_to_dicts(payload, "securities")}
        marketdata = _table_to_dicts(payload, "marketdata")
        quotes: list[SecurityQuote] = []

        def to_float(value: Any) -> float | None:
            if value in (None, ""):
                return None
            try:
                return float(value)
            except (TypeError, ValueError):
                return None

        for md in marketdata:
            secid = str(md.get("SECID") or "").upper()
            if not secid:
                continue
            sec = securities.get(secid, {})
            price = to_float(md.get("LAST") or md.get("MARKETPRICE2") or md.get("LCURRENTPRICE") or sec.get("PREVPRICE"))
            change_pct = to_float(md.get("LASTTOPREVPRICE") or md.get("CHANGEPRCNT"))
            volume = to_float(md.get("VALTODAY") or md.get("VOLTODAY") or md.get("NUMTRADES"))
            if price is None or change_pct is None:
                continue
            quotes.append(
                SecurityQuote(
                    symbol=secid,
                    name=str(sec.get("SHORTNAME") or sec.get("SECNAME") or secid),
                    market="MOEX shares/TQBR",
                    price=price,
                    change_abs=to_float(md.get("CHANGE")),
                    change_pct=change_pct,
                    currency=str(sec.get("CURRENCYID") or "RUB"),
                    volume=volume,
                    as_of=str(md.get("SYSTIME") or md.get("TIME") or ""),
                )
            )

        if kind in {"gainers", "growth", "рост"}:
            quotes.sort(key=lambda q: q.change_pct if q.change_pct is not None else -10**9, reverse=True)
        elif kind in {"losers", "fall", "снижение"}:
            quotes.sort(key=lambda q: q.change_pct if q.change_pct is not None else 10**9)
        elif kind in {"volume", "turnover", "оборот"}:
            quotes.sort(key=lambda q: q.volume if q.volume is not None else -1, reverse=True)
        else:
            raise MoexError("Неизвестный скринер. Доступно: gainers, losers, volume")

        result = quotes[:limit]
        self.cache.set(cache_key, result)
        return result

    async def market_snapshot(self) -> list[SecurityQuote]:
        symbols = ["IMOEX", "RTSI", "RGBI", "SBER", "GAZP", "LKOH", "YDEX"]
        quotes: list[SecurityQuote] = []
        for symbol in symbols:
            try:
                quotes.append(await self.quote(symbol))
            except Exception:
                continue
        return quotes
