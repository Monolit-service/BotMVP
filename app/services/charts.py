from __future__ import annotations

from io import BytesIO

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd

from app.services.periods import PERIODS


def build_price_chart_png(df: pd.DataFrame, symbol: str, period: str, title: str = "") -> bytes:
    if df.empty:
        raise ValueError("Нет данных для графика")
    if "datetime" not in df.columns or "close" not in df.columns:
        raise ValueError("Ожидаются колонки datetime и close")

    period_label = PERIODS[period].label
    fig, ax = plt.subplots(figsize=(10, 5.2), dpi=160)
    ax.plot(df["datetime"], df["close"], linewidth=1.8)
    ax.set_title(title or f"{symbol} · {period_label}")
    ax.set_xlabel("Дата")
    ax.set_ylabel("Цена закрытия")
    ax.grid(True, alpha=0.25)
    fig.autofmt_xdate()
    fig.tight_layout()

    buffer = BytesIO()
    fig.savefig(buffer, format="png", bbox_inches="tight")
    plt.close(fig)
    return buffer.getvalue()
