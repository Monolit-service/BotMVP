from __future__ import annotations

from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

from aiogram import Bot

from app.formatting import fmt_num, fmt_pct
from app.models import SecurityQuote


async def safe_send_message(bot: Bot, chat_id: int, text: str) -> None:
    try:
        await bot.send_message(chat_id, text, disable_web_page_preview=True)
    except Exception:
        # The caller logs the specific context. Keeping this helper minimal avoids hard dependency cycles.
        raise


def now_local(tz_name: str) -> datetime:
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("UTC")
    return datetime.now(tz)


def market_digest_text(
    watch_quotes: list[SecurityQuote],
    top_gainers: list[SecurityQuote],
    top_losers: list[SecurityQuote],
    events_lines: list[str],
    generated_at: datetime,
) -> str:
    lines = [
        f"<b>Утренний рыночный дайджест</b>",
        f"<i>{escape(generated_at.strftime('%Y-%m-%d %H:%M'))}</i>",
        "",
    ]
    if watch_quotes:
        lines.append("<b>Watchlist</b>")
        for q in watch_quotes[:12]:
            lines.append(f"• <b>{escape(q.symbol)}</b>: {fmt_num(q.price)} {escape(q.currency or '')} ({fmt_pct(q.change_pct)})")
        lines.append("")

    if top_gainers:
        lines.append("<b>MOEX: лидеры роста</b>")
        lines.extend(f"• {escape(q.symbol)} {fmt_pct(q.change_pct)}" for q in top_gainers[:5])
        lines.append("")

    if top_losers:
        lines.append("<b>MOEX: лидеры снижения</b>")
        lines.extend(f"• {escape(q.symbol)} {fmt_pct(q.change_pct)}" for q in top_losers[:5])
        lines.append("")

    if events_lines:
        lines.append("<b>Ближайшие события</b>")
        lines.extend(events_lines[:8])
        lines.append("")

    lines.append("<i>Справочная информация. Не является индивидуальной инвестиционной рекомендацией.</i>")
    return "\n".join(lines)
