from __future__ import annotations

from html import escape
from typing import Iterable

from app.models import CorporateEvent, NewsItem, PriceAlert, SecurityQuote
from app.services.analytics import CandleStats
from app.services.periods import PERIODS


def fmt_num(value: float | None, digits: int = 2) -> str:
    if value is None:
        return "н/д"
    try:
        return f"{value:,.{digits}f}".replace(",", " ")
    except Exception:
        return str(value)


def fmt_pct(value: float | None) -> str:
    if value is None:
        return "н/д"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.2f}%"


def quote_caption(quote: SecurityQuote, period: str | None = None) -> str:
    period_text = f"\nПериод графика: <b>{escape(PERIODS[period].label)}</b>" if period and period in PERIODS else ""
    parts = [
        f"<b>{escape(quote.symbol)}</b> — {escape(quote.name)}",
        f"Рынок: {escape(quote.market)}",
        f"Цена: <b>{fmt_num(quote.price)}</b> {escape(quote.currency or '')}",
        f"Изменение: {fmt_num(quote.change_abs)} / {fmt_pct(quote.change_pct)}",
    ]
    if quote.volume is not None:
        parts.append(f"Объём/оборот: {fmt_num(quote.volume, 0)}")
    if quote.as_of:
        parts.append(f"Время данных: {escape(str(quote.as_of))}")
    parts.append(period_text.strip())
    parts.append("\n<i>Не является индивидуальной инвестиционной рекомендацией.</i>")
    return "\n".join(p for p in parts if p)


def quotes_list(title: str, quotes: Iterable[SecurityQuote]) -> str:
    lines = [f"<b>{escape(title)}</b>", ""]
    for q in quotes:
        volume = f" · оборот/объём {fmt_num(q.volume, 0)}" if q.volume is not None else ""
        lines.append(
            f"<b>{escape(q.symbol)}</b> {escape(q.name)}: "
            f"{fmt_num(q.price)} {escape(q.currency or '')} ({fmt_pct(q.change_pct)}){volume}"
        )
    lines.append("\n<i>Данные могут идти с задержкой. Не инвестиционная рекомендация.</i>")
    return "\n".join(lines)


def news_list(symbol: str, items: list[NewsItem]) -> str:
    if not items:
        return f"Новости по <b>{escape(symbol)}</b> не найдены."
    lines = [f"<b>Новости по {escape(symbol)}</b>", ""]
    for idx, item in enumerate(items, 1):
        date = item.published_at.strftime("%Y-%m-%d %H:%M") if item.published_at else "дата н/д"
        source = f" · {escape(item.source)}" if item.source else ""
        if item.url:
            lines.append(f'{idx}. <a href="{escape(item.url)}">{escape(item.title)}</a>')
        else:
            lines.append(f"{idx}. {escape(item.title)}")
        lines.append(f"   <i>{escape(date)}{source}</i>")
    lines.append("\n<i>Не является инвестиционной рекомендацией.</i>")
    return "\n".join(lines)


def events_list(title: str, events: list[CorporateEvent]) -> str:
    if not events:
        return f"<b>{escape(title)}</b>\n\nСобытия не найдены. Заполните data/events.csv или подключите внешний календарь."
    lines = [f"<b>{escape(title)}</b>", ""]
    for event in events:
        tag = f"[{event.importance}] " if event.importance and event.importance != "normal" else ""
        label = f"{event.date:%Y-%m-%d} · {event.symbol} · {event.category}"
        if event.source_url:
            lines.append(f'• <a href="{escape(event.source_url)}">{escape(tag + event.title)}</a>')
        else:
            lines.append(f"• {escape(tag + event.title)}")
        lines.append(f"  <i>{escape(label)}</i>")
    lines.append("\n<i>События являются справочной информацией.</i>")
    return "\n".join(lines)


def alerts_list(alerts: list[PriceAlert]) -> str:
    if not alerts:
        return "Активных алертов нет. Пример: /alert SBER &gt; 300"
    metric_names = {"price": "цена", "pct": "дневное изменение"}
    lines = ["<b>Активные алерты</b>", ""]
    for alert in alerts:
        metric = metric_names.get(alert.metric, alert.metric)
        suffix = " ₽/$" if alert.metric == "price" else "%"
        lines.append(
            f"#{alert.id}: <b>{escape(alert.symbol)}</b> ({escape(alert.market)}) · "
            f"{escape(metric)} {escape(alert.operator)} {fmt_num(alert.threshold)}{suffix}"
        )
    lines.append("\nУдалить: /alert_del ID")
    return "\n".join(lines)


def brief_text(
    quote: SecurityQuote,
    stats: CandleStats,
    period: str,
    news: list[NewsItem],
    news_tone: str,
    events: list[CorporateEvent],
) -> str:
    period_label = PERIODS[period].label if period in PERIODS else period
    lines = [
        f"<b>{escape(quote.symbol)} — краткий бриф</b>",
        f"{escape(quote.name)} · {escape(quote.market)}",
        "",
        f"Цена: <b>{fmt_num(quote.price)}</b> {escape(quote.currency or '')}",
        f"День: {fmt_num(quote.change_abs)} / {fmt_pct(quote.change_pct)}",
        f"Динамика за {escape(period_label)}: {fmt_pct(stats.period_change_pct)}",
        f"Диапазон периода: {fmt_num(stats.low)} — {fmt_num(stats.high)}",
        f"Макс. просадка периода: {fmt_pct(stats.max_drawdown_pct)}",
    ]
    if stats.volume_ratio_20 is not None:
        lines.append(f"Объём к среднему за 20 свечей: {fmt_num(stats.volume_ratio_20, 2)}x")
    lines.append("")

    signals: list[str] = []
    if quote.change_pct is not None and abs(quote.change_pct) >= 3:
        signals.append(f"сильное дневное движение: {fmt_pct(quote.change_pct)}")
    if stats.volume_ratio_20 is not None and stats.volume_ratio_20 >= 1.8:
        signals.append("объём заметно выше среднего")
    if news:
        signals.append(f"найдено свежих новостей: {len(news)}; тон: {news_tone}")
    if events:
        signals.append(f"есть ближайшие события: {len(events)}")
    if signals:
        lines.append("<b>Что обратить внимание</b>")
        lines.extend(f"• {escape(item)}" for item in signals)
        lines.append("")

    if news:
        lines.append("<b>Свежие новости</b>")
        for item in news[:3]:
            if item.url:
                lines.append(f'• <a href="{escape(item.url)}">{escape(item.title)}</a>')
            else:
                lines.append(f"• {escape(item.title)}")
        lines.append("")

    if events:
        lines.append("<b>Ближайшие события</b>")
        for event in events[:3]:
            lines.append(f"• {event.date:%Y-%m-%d}: {escape(event.category)} — {escape(event.title)}")
        lines.append("")

    lines.append("<i>Бриф — справочная рыночная сводка, не индивидуальная инвестиционная рекомендация.</i>")
    return "\n".join(lines)
