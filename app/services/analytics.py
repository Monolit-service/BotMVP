from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(slots=True)
class CandleStats:
    start_price: float | None
    last_price: float | None
    period_change_pct: float | None
    high: float | None
    low: float | None
    max_drawdown_pct: float | None
    last_volume: float | None
    avg_volume_20: float | None
    volume_ratio_20: float | None


def candle_stats(df: pd.DataFrame) -> CandleStats:
    if df.empty or "close" not in df.columns:
        return CandleStats(None, None, None, None, None, None, None, None, None)

    close = pd.to_numeric(df["close"], errors="coerce").dropna()
    if close.empty:
        return CandleStats(None, None, None, None, None, None, None, None, None)

    start = float(close.iloc[0])
    last = float(close.iloc[-1])
    change = ((last / start) - 1.0) * 100 if start else None
    high = float(close.max())
    low = float(close.min())
    running_max = close.cummax()
    drawdown = (close / running_max - 1.0) * 100
    max_drawdown = float(drawdown.min()) if not drawdown.empty else None

    last_volume = None
    avg_volume_20 = None
    volume_ratio_20 = None
    if "volume" in df.columns:
        volume = pd.to_numeric(df["volume"], errors="coerce").dropna()
        if not volume.empty:
            last_volume = float(volume.iloc[-1])
            recent = volume.tail(20)
            avg_volume_20 = float(recent.mean()) if not recent.empty else None
            volume_ratio_20 = (last_volume / avg_volume_20) if avg_volume_20 else None

    return CandleStats(start, last, change, high, low, max_drawdown, last_volume, avg_volume_20, volume_ratio_20)


def simple_news_tone(text: str) -> str:
    """Rule-based tone label for headlines. Not an investment recommendation."""
    low = text.lower()
    positive = [
        "рост", "вырос", "увелич", "рекорд", "дивиденд", "прибыль", "выручка", "повысил", "buyback",
        "upgrade", "beats", "profit", "revenue", "dividend", "record", "strong",
    ]
    negative = [
        "паден", "упал", "сниз", "убыт", "штраф", "санкц", "расслед", "понизил", "downgrade",
        "misses", "loss", "weak", "cut", "lawsuit", "fine",
    ]
    pos = sum(1 for word in positive if word in low)
    neg = sum(1 for word in negative if word in low)
    if pos > neg:
        return "скорее позитивный"
    if neg > pos:
        return "скорее негативный"
    return "нейтральный/смешанный"


def alert_value(metric: str, price: float | None, change_pct: float | None) -> float | None:
    metric = metric.lower()
    if metric in {"price", "цена"}:
        return price
    if metric in {"pct", "change", "изменение"}:
        return change_pct
    return None


def compare(value: float | None, operator: str, threshold: float) -> bool:
    if value is None:
        return False
    if operator in {">", ">=", "above"}:
        return value >= threshold if operator == ">=" else value > threshold
    if operator in {"<", "<=", "below"}:
        return value <= threshold if operator == "<=" else value < threshold
    raise ValueError(f"Unsupported operator: {operator}")
