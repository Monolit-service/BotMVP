from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import datetime

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import BufferedInputFile, Message

from app.company_aliases import MOEX_COMMON_TICKERS, aliases_for
from app.config import Settings, get_settings
from app.db import BotDatabase
from app.formatting import alerts_list, brief_text, events_list, news_list, quote_caption, quotes_list
from app.services.analytics import alert_value, candle_stats, compare, simple_news_tone
from app.services.charts import build_price_chart_png
from app.services.digest import market_digest_text, now_local
from app.services.events import CorporateEventsClient
from app.services.finnhub import FinnhubClient, FinnhubError
from app.services.moex import MoexClient, MoexError
from app.services.periods import normalize_period
from app.services.rss_news import RssNewsClient

logger = logging.getLogger(__name__)
router = Router()


@dataclass
class AppContext:
    moex: MoexClient
    finnhub: FinnhubClient
    rss: RssNewsClient
    disclosures: RssNewsClient
    events: CorporateEventsClient
    db: BotDatabase
    settings: Settings
    default_period: str


CTX: AppContext | None = None


def get_ctx() -> AppContext:
    if CTX is None:
        raise RuntimeError("Application context is not initialized")
    return CTX


def user_id(message: Message) -> int:
    if not message.from_user:
        raise RuntimeError("Unknown Telegram user")
    return int(message.from_user.id)


def parse_args(text: str | None) -> list[str]:
    if not text:
        return []
    parts = text.split(maxsplit=1)
    if len(parts) == 1:
        return []
    return parts[1].split()


def clean_symbol(symbol: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.:-]", "", symbol).upper().strip()


def detect_market(symbol: str, forced: str | None = None) -> tuple[str, str]:
    symbol = clean_symbol(symbol)
    if symbol.startswith("MOEX:"):
        return symbol.removeprefix("MOEX:"), "MOEX"
    if symbol.endswith(".ME"):
        return symbol.removesuffix(".ME"), "MOEX"
    if symbol.startswith("US:"):
        return symbol.removeprefix("US:"), "GLOBAL"
    if forced:
        return symbol, forced.upper()
    if symbol in MOEX_COMMON_TICKERS:
        return symbol, "MOEX"
    return symbol, "GLOBAL"


def parse_alert_args(args: list[str]) -> tuple[str, str, str, str, float]:
    """Returns symbol, market, metric, operator, threshold."""
    if len(args) < 3:
        raise ValueError("Пример: /alert SBER > 300 или /alert SBER pct < -3")
    symbol, market = detect_market(args[0])
    metric = "price"
    op_index = 1
    if len(args) >= 4 and args[1].lower() in {"price", "цена", "pct", "change", "изменение"}:
        metric_raw = args[1].lower()
        metric = "pct" if metric_raw in {"pct", "change", "изменение"} else "price"
        op_index = 2
    operator = args[op_index]
    if operator not in {">", ">=", "<", "<="}:
        raise ValueError("Оператор должен быть одним из: >, >=, <, <=")
    try:
        threshold = float(args[op_index + 1].replace(",", "."))
    except (IndexError, ValueError):
        raise ValueError("Укажите числовой порог. Пример: /alert SBER > 300")
    return symbol, market, metric, operator, threshold


def normalize_hhmm(value: str) -> str:
    if not re.match(r"^\d{1,2}:\d{2}$", value):
        raise ValueError("Время нужно указать в формате HH:MM, например 09:30")
    hh, mm = value.split(":")
    h, m = int(hh), int(mm)
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError("Время должно быть в диапазоне 00:00–23:59")
    return f"{h:02d}:{m:02d}"


async def send_typing(message: Message) -> None:
    if message.bot:
        await message.bot.send_chat_action(message.chat.id, "typing")


async def get_quote(ctx: AppContext, symbol: str, market: str):
    return await ctx.moex.quote(symbol) if market == "MOEX" else await ctx.finnhub.quote(symbol)


async def get_candles(ctx: AppContext, symbol: str, market: str, period: str):
    return await ctx.moex.candles(symbol, period) if market == "MOEX" else await ctx.finnhub.candles(symbol, period)


async def get_news_for_symbol(ctx: AppContext, symbol: str, market: str, limit: int = 5):
    if market == "GLOBAL":
        try:
            return await ctx.finnhub.company_news(symbol, days=21, limit=limit)
        except FinnhubError:
            if ctx.rss.is_enabled():
                return await ctx.rss.search([symbol], limit=limit)
            raise
    return await ctx.rss.search(aliases_for(symbol), limit=limit)


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await message.answer(
        "<b>Market TG Bot Pro MVP</b>\n\n"
        "Я показываю рынки, графики, новости, события, скринеры, watchlist, алерты и персональный дайджест.\n\n"
        "<b>Базовые команды</b>\n"
        "• /markets — обзор рынка\n"
        "• /stock SBER 1m — график и котировка\n"
        "• /moex GAZP 1y — российский рынок MOEX\n"
        "• /us AAPL 6m — глобальные акции через Finnhub\n"
        "• /news SBER — новости компании\n"
        "• /brief SBER — краткая сводка по тикеру\n\n"
        "<b>Конкурентные функции</b>\n"
        "• /top gainers | losers | volume — скринер MOEX\n"
        "• /events SBER — ближайшие события по тикеру\n"
        "• /calendar — календарь событий\n"
        "• /disclosures SBER — раскрытия/сообщения из RSS-источников\n"
        "• /alert SBER > 300 — ценовой алерт\n"
        "• /alert SBER pct < -3 — алерт по дневному изменению, %\n"
        "• /alerts — список алертов\n"
        "• /digest_on 09:30 — ежедневный дайджест\n\n"
        "<b>Watchlist</b>\n"
        "• /watch_add SBER\n"
        "• /watch\n"
        "• /watch_report\n"
        "• /watch_del SBER\n\n"
        "Периоды: 1d, 1w, 1m, 3m, 6m, 1y, 3y, 5y.\n\n"
        "<i>Бот предоставляет справочную информацию и не даёт индивидуальных инвестиционных рекомендаций.</i>"
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await cmd_start(message)


@router.message(Command("markets"))
async def cmd_markets(message: Message) -> None:
    ctx = get_ctx()
    await send_typing(message)
    blocks = []
    try:
        moex_quotes = await ctx.moex.market_snapshot()
        if moex_quotes:
            blocks.append(quotes_list("MOEX: рынок РФ", moex_quotes))
    except Exception as exc:
        logger.exception("MOEX market snapshot error")
        blocks.append(f"<b>MOEX</b>\nНе удалось получить данные: {exc}")

    try:
        top = await ctx.moex.screener("gainers", limit=5)
        if top:
            blocks.append(quotes_list("MOEX: лидеры роста", top))
    except Exception as exc:
        logger.warning("MOEX top error: %s", exc)

    try:
        global_quotes = await ctx.finnhub.market_snapshot()
        if global_quotes:
            blocks.append(quotes_list("Global: ETF-индикаторы", global_quotes))
    except FinnhubError as exc:
        blocks.append(f"<b>Global</b>\n{exc}")
    except Exception as exc:
        logger.exception("Global market snapshot error")
        blocks.append(f"<b>Global</b>\nНе удалось получить данные: {exc}")

    await message.answer("\n\n".join(blocks) if blocks else "Не удалось получить рыночные данные.", disable_web_page_preview=True)


async def send_stock(message: Message, forced_market: str | None = None) -> None:
    ctx = get_ctx()
    args = parse_args(message.text)
    if not args:
        await message.answer("Пример: /stock SBER 1m или /stock AAPL 6m")
        return

    symbol, market = detect_market(args[0], forced=forced_market)
    try:
        period = normalize_period(args[1] if len(args) > 1 else ctx.default_period, default=ctx.default_period)
    except ValueError as exc:
        await message.answer(str(exc))
        return

    await send_typing(message)
    try:
        quote = await get_quote(ctx, symbol, market)
        candles = await get_candles(ctx, symbol, market, period)
        png = build_price_chart_png(candles, symbol=quote.symbol, period=period, title=f"{quote.symbol} · {quote.name}")
        photo = BufferedInputFile(png, filename=f"{quote.symbol}_{period}.png")
        await message.answer_photo(photo=photo, caption=quote_caption(quote, period=period))
    except (MoexError, FinnhubError, ValueError) as exc:
        await message.answer(f"Не удалось получить данные: {exc}")
    except Exception as exc:
        logger.exception("stock command failed")
        await message.answer(f"Ошибка при получении данных: {exc}")


@router.message(Command("stock"))
async def cmd_stock(message: Message) -> None:
    await send_stock(message)


@router.message(Command("moex"))
async def cmd_moex(message: Message) -> None:
    await send_stock(message, forced_market="MOEX")


@router.message(Command("us"))
async def cmd_us(message: Message) -> None:
    await send_stock(message, forced_market="GLOBAL")


@router.message(Command("news"))
async def cmd_news(message: Message) -> None:
    ctx = get_ctx()
    args = parse_args(message.text)
    if not args:
        await message.answer("Пример: /news AAPL или /news SBER")
        return
    symbol, market = detect_market(args[0])
    await send_typing(message)
    try:
        items = await get_news_for_symbol(ctx, symbol, market, limit=5)
    except FinnhubError as exc:
        await message.answer(str(exc))
        return
    if market == "MOEX" and not items:
        await message.answer(
            f"Новости по <b>{symbol}</b> через RSS не найдены. "
            "Добавьте RSS_FEEDS в .env или подключите коммерческий источник новостей."
        )
        return
    await message.answer(news_list(symbol, items), disable_web_page_preview=True)


@router.message(Command("brief"))
async def cmd_brief(message: Message) -> None:
    ctx = get_ctx()
    args = parse_args(message.text)
    if not args:
        await message.answer("Пример: /brief SBER или /brief AAPL 3m")
        return
    symbol, market = detect_market(args[0])
    try:
        period = normalize_period(args[1] if len(args) > 1 else "1m", default="1m")
    except ValueError as exc:
        await message.answer(str(exc))
        return
    await send_typing(message)
    try:
        quote = await get_quote(ctx, symbol, market)
        candles = await get_candles(ctx, symbol, market, period)
        stats = candle_stats(candles)
        try:
            news = await get_news_for_symbol(ctx, symbol, market, limit=5)
        except Exception:
            news = []
        tone = simple_news_tone("\n".join(item.title for item in news)) if news else "н/д"
        events = ctx.events.upcoming_for_symbol(symbol, days_ahead=30, limit=5) if market == "MOEX" else []
        await message.answer(brief_text(quote, stats, period, news, tone, events), disable_web_page_preview=True)
    except (MoexError, FinnhubError, ValueError) as exc:
        await message.answer(f"Не удалось собрать бриф: {exc}")
    except Exception as exc:
        logger.exception("brief failed")
        await message.answer(f"Ошибка при сборе брифа: {exc}")


@router.message(Command("top"))
async def cmd_top(message: Message) -> None:
    ctx = get_ctx()
    args = parse_args(message.text)
    kind = args[0].lower() if args else "gainers"
    aliases = {"рост": "gainers", "up": "gainers", "down": "losers", "падение": "losers", "объем": "volume", "объём": "volume"}
    kind = aliases.get(kind, kind)
    await send_typing(message)
    try:
        quotes = await ctx.moex.screener(kind, limit=ctx.settings.screener_limit)
        titles = {"gainers": "MOEX: лидеры роста", "losers": "MOEX: лидеры снижения", "volume": "MOEX: лидеры по обороту"}
        await message.answer(quotes_list(titles.get(kind, f"MOEX: {kind}"), quotes), disable_web_page_preview=True)
    except Exception as exc:
        await message.answer(f"Не удалось получить скринер: {exc}")


@router.message(Command("events"))
async def cmd_events(message: Message) -> None:
    ctx = get_ctx()
    args = parse_args(message.text)
    if not args:
        await message.answer("Пример: /events SBER")
        return
    symbol, market = detect_market(args[0], forced="MOEX")
    events = ctx.events.upcoming_for_symbol(symbol, days_ahead=60, limit=12)
    await message.answer(events_list(f"События по {symbol}", events), disable_web_page_preview=True)


@router.message(Command("calendar"))
async def cmd_calendar(message: Message) -> None:
    ctx = get_ctx()
    events = ctx.events.calendar(days_ahead=14, limit=20)
    await message.answer(events_list("Календарь событий на 14 дней", events), disable_web_page_preview=True)


@router.message(Command("disclosures"))
async def cmd_disclosures(message: Message) -> None:
    ctx = get_ctx()
    args = parse_args(message.text)
    if not args:
        await message.answer("Пример: /disclosures SBER")
        return
    symbol, _ = detect_market(args[0], forced="MOEX")
    if not ctx.disclosures.is_enabled():
        await message.answer(
            "DISCLOSURE_RSS_FEEDS не настроен. Добавьте RSS/ленты раскрытий в .env, "
            "или подключите коммерческий API раскрытий."
        )
        return
    await send_typing(message)
    items = await ctx.disclosures.search(aliases_for(symbol), limit=7)
    await message.answer(news_list(f"{symbol}: раскрытия", items), disable_web_page_preview=True)


@router.message(Command("alert"))
async def cmd_alert(message: Message) -> None:
    ctx = get_ctx()
    args = parse_args(message.text)
    try:
        symbol, market, metric, operator, threshold = parse_alert_args(args)
    except ValueError as exc:
        await message.answer(str(exc))
        return
    alert_id = ctx.db.add_alert(user_id(message), symbol, market, metric, operator, threshold)
    metric_text = "цена" if metric == "price" else "дневное изменение, %"
    await message.answer(
        f"Создал алерт #{alert_id}: <b>{symbol}</b> ({market}) · {metric_text} {operator} {threshold:g}\n"
        "Алерт однократный: после срабатывания он будет отключён."
    )


@router.message(Command("alerts"))
async def cmd_alerts(message: Message) -> None:
    ctx = get_ctx()
    await message.answer(alerts_list(ctx.db.list_alerts(user_id(message))))


@router.message(Command("alert_del"))
async def cmd_alert_del(message: Message) -> None:
    ctx = get_ctx()
    args = parse_args(message.text)
    if not args or not args[0].isdigit():
        await message.answer("Пример: /alert_del 12")
        return
    removed = ctx.db.delete_alert(user_id(message), int(args[0]))
    await message.answer("Алерт удалён." if removed else "Такой алерт не найден.")


@router.message(Command("digest_on"))
async def cmd_digest_on(message: Message) -> None:
    ctx = get_ctx()
    args = parse_args(message.text)
    try:
        digest_time = normalize_hhmm(args[0]) if args else normalize_hhmm(ctx.settings.digest_default_time)
    except ValueError as exc:
        await message.answer(str(exc))
        return
    ctx.db.enable_digest(user_id(message), digest_time)
    await message.answer(f"Включил ежедневный дайджест на <b>{digest_time}</b> ({ctx.settings.tz}).")


@router.message(Command("digest_off"))
async def cmd_digest_off(message: Message) -> None:
    ctx = get_ctx()
    ctx.db.disable_digest(user_id(message))
    await message.answer("Ежедневный дайджест отключён.")


@router.message(Command("watch_add"))
async def cmd_watch_add(message: Message) -> None:
    ctx = get_ctx()
    args = parse_args(message.text)
    if not args:
        await message.answer("Пример: /watch_add SBER или /watch_add US:AAPL")
        return
    symbol, market = detect_market(args[0])
    ctx.db.add_watch(user_id(message), symbol, market)
    await message.answer(f"Добавил в watchlist: <b>{symbol}</b> ({market})")


@router.message(Command("watch_del"))
async def cmd_watch_del(message: Message) -> None:
    ctx = get_ctx()
    args = parse_args(message.text)
    if not args:
        await message.answer("Пример: /watch_del SBER")
        return
    symbol, market = detect_market(args[0])
    removed = ctx.db.remove_watch(user_id(message), symbol, market)
    if removed == 0:
        removed = ctx.db.remove_watch(user_id(message), symbol, None)
    await message.answer("Удалил из watchlist." if removed else "Такого тикера в watchlist не было.")


@router.message(Command("watch"))
async def cmd_watch(message: Message) -> None:
    ctx = get_ctx()
    items = ctx.db.list_watch(user_id(message))
    if not items:
        await message.answer("Watchlist пуст. Добавьте тикер командой /watch_add SBER")
        return
    lines = ["<b>Ваш watchlist</b>", ""]
    for symbol, market in items:
        lines.append(f"• {symbol} ({market})")
    lines.append("\nГрафик: /stock SBER 1m\nСводка: /watch_report\nДайджест: /digest_on 09:30")
    await message.answer("\n".join(lines))


@router.message(Command("watch_report"))
async def cmd_watch_report(message: Message) -> None:
    ctx = get_ctx()
    text = await build_watch_report(ctx, user_id(message))
    await message.answer(text, disable_web_page_preview=True)


async def build_watch_report(ctx: AppContext, telegram_user_id: int) -> str:
    items = ctx.db.list_watch(telegram_user_id)
    if not items:
        return "Watchlist пуст. Добавьте тикер командой /watch_add SBER"
    quotes = []
    for symbol, market in items:
        try:
            quotes.append(await get_quote(ctx, symbol, market))
        except Exception as exc:
            logger.warning("watch_report error for %s %s: %s", market, symbol, exc)
    return quotes_list("Сводка watchlist", quotes) if quotes else "Не удалось получить данные по watchlist."


async def build_digest_for_user(ctx: AppContext, telegram_user_id: int) -> str:
    watch_quotes = []
    for symbol, market in ctx.db.list_watch(telegram_user_id):
        try:
            watch_quotes.append(await get_quote(ctx, symbol, market))
        except Exception as exc:
            logger.warning("digest watch quote error for %s %s: %s", market, symbol, exc)

    try:
        top_gainers = await ctx.moex.screener("gainers", limit=5)
    except Exception:
        top_gainers = []
    try:
        top_losers = await ctx.moex.screener("losers", limit=5)
    except Exception:
        top_losers = []

    events_lines: list[str] = []
    for event in ctx.events.calendar(days_ahead=7, limit=8):
        events_lines.append(f"• {event.date:%Y-%m-%d} · {event.symbol}: {event.title}")

    return market_digest_text(watch_quotes, top_gainers, top_losers, events_lines, now_local(ctx.settings.tz))


async def alert_worker(bot: Bot) -> None:
    ctx = get_ctx()
    while True:
        try:
            alerts = ctx.db.active_alerts()
            for alert in alerts:
                try:
                    quote = await get_quote(ctx, alert.symbol, alert.market)
                    value = alert_value(alert.metric, quote.price, quote.change_pct)
                    ctx.db.touch_alert_value(alert.id, value)
                    if compare(value, alert.operator, alert.threshold):
                        ctx.db.mark_alert_triggered(alert.id, value)
                        metric_text = "цена" if alert.metric == "price" else "дневное изменение"
                        suffix = (quote.currency or "") if alert.metric == "price" else "%"
                        await bot.send_message(
                            alert.telegram_user_id,
                            f"🔔 <b>Алерт сработал #{alert.id}</b>\n"
                            f"{alert.symbol} ({alert.market}) · {metric_text}: <b>{value:.2f}</b> {suffix}\n"
                            f"Условие: {alert.operator} {alert.threshold:g}\n\n"
                            "<i>Не является инвестиционной рекомендацией.</i>",
                        )
                except Exception as exc:
                    logger.warning("alert check error #%s %s %s: %s", alert.id, alert.market, alert.symbol, exc)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("alert worker failed")
        await asyncio.sleep(max(ctx.settings.alert_check_interval_seconds, 15))


async def digest_worker(bot: Bot) -> None:
    ctx = get_ctx()
    while True:
        try:
            local_now = now_local(ctx.settings.tz)
            local_date = local_now.strftime("%Y-%m-%d")
            current_hhmm = local_now.strftime("%H:%M")
            for telegram_user_id, _digest_time in ctx.db.digest_users_due(local_date, current_hhmm):
                try:
                    text = await build_digest_for_user(ctx, telegram_user_id)
                    await bot.send_message(telegram_user_id, text, disable_web_page_preview=True)
                    ctx.db.mark_digest_sent(telegram_user_id, local_date)
                except Exception as exc:
                    logger.warning("digest send error for user %s: %s", telegram_user_id, exc)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("digest worker failed")
        await asyncio.sleep(max(ctx.settings.digest_check_interval_seconds, 30))


@router.message(F.text)
async def cmd_unknown(message: Message) -> None:
    await message.answer("Не понял команду. Используйте /help")


async def main() -> None:
    global CTX
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = get_settings()
    db = BotDatabase(settings.sqlite_path)
    db.init()
    CTX = AppContext(
        moex=MoexClient(timeout=settings.http_timeout_seconds, cache_ttl_seconds=settings.cache_ttl_seconds),
        finnhub=FinnhubClient(
            api_key=settings.finnhub_api_key,
            timeout=settings.http_timeout_seconds,
            cache_ttl_seconds=settings.cache_ttl_seconds,
        ),
        rss=RssNewsClient(feeds=settings.rss_feeds, cache_ttl_seconds=max(settings.cache_ttl_seconds, 300)),
        disclosures=RssNewsClient(feeds=settings.disclosure_rss_feeds, cache_ttl_seconds=max(settings.cache_ttl_seconds, 300)),
        events=CorporateEventsClient(settings.events_csv_path, cache_ttl_seconds=max(settings.cache_ttl_seconds, 300)),
        db=db,
        settings=settings,
        default_period=settings.default_period,
    )

    bot = Bot(token=settings.telegram_bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(router)

    try:
        me = await bot.get_me()
        logger.info("Bot authenticated as @%s, id=%s", me.username, me.id)
        webhook_info = await bot.get_webhook_info()
        if webhook_info.url:
            logger.warning("Existing Telegram webhook found and will be deleted: %s", webhook_info.url)
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("Polling started. Send /start to @%s", me.username)
    except Exception:
        logger.exception("Telegram connection failed. Check TELEGRAM_BOT_TOKEN, internet access and proxy/firewall settings.")
        await bot.session.close()
        raise

    tasks = [asyncio.create_task(alert_worker(bot)), asyncio.create_task(digest_worker(bot))]
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
