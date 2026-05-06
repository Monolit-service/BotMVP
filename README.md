# Market TG Bot Pro MVP

Telegram-бот для рыночной информации: MOEX, глобальные акции через Finnhub, графики, новости, скринеры, события, watchlist, алерты и ежедневный дайджест.

> Бот предоставляет справочную информацию и не является индивидуальной инвестиционной рекомендацией. В нём нет торговых поручений, брокерских операций и персональных рекомендаций.

## Что добавлено в Pro MVP

Этот архив доработан от базового MVP до более конкурентного уровня за счёт функций, которые дают пользователю ответ на вопрос «что произошло и за чем следить», а не просто показывают цену.

### Команды

Базовые:

```text
/start
/help
/markets
/stock SBER 1m
/moex GAZP 1y
/us AAPL 6m
/news SBER
/brief SBER
```

Скринеры MOEX:

```text
/top gainers
/top losers
/top volume
```

Watchlist:

```text
/watch_add SBER
/watch_add US:AAPL
/watch
/watch_report
/watch_del SBER
```

Алерты:

```text
/alert SBER > 300
/alert SBER < 250
/alert SBER pct > 3
/alert SBER pct < -3
/alerts
/alert_del 12
```

Алерты однократные: после срабатывания они автоматически отключаются.

События и раскрытия:

```text
/events SBER
/calendar
/disclosures SBER
```

Дайджест:

```text
/digest_on 09:30
/digest_off
```

Дайджест отправляет пользователю watchlist, лидеров роста/снижения MOEX и ближайшие события из `data/events.csv`.

## Источники данных

- **MOEX ISS** — российские акции, индексы, свечи, скринеры по основному режиму торгов.
- **Finnhub** — глобальные акции, котировки, свечи, company news. Нужен `FINNHUB_API_KEY`.
- **RSS_FEEDS** — новости по российским компаниям или fallback для глобальных тикеров.
- **DISCLOSURE_RSS_FEEDS** — отдельные RSS/ленты раскрытий эмитентов.
- **data/events.csv** — локальный календарь событий: дивиденды, отчётности, советы директоров, купоны и т.п.

## Быстрый запуск

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

Заполните `.env`:

```env
TELEGRAM_BOT_TOKEN=...
FINNHUB_API_KEY=...        # опционально
RSS_FEEDS=...              # опционально
DISCLOSURE_RSS_FEEDS=...   # опционально
```

Запустите:

```bash
python -m app.main
```

## Запуск через Docker

```bash
docker compose up --build
```

## Календарь событий

Для функций `/events`, `/calendar`, `/brief` и ежедневного дайджеста можно подключить локальный CSV:

```bash
cp data/events.example.csv data/events.csv
```

Формат:

```csv
date,symbol,category,title,source_url,importance
2026-05-15,SBER,report,Публикация финансовых результатов,https://example.com,high
```

Где:

- `date` — дата в формате `YYYY-MM-DD`;
- `symbol` — тикер, например `SBER`;
- `category` — `report`, `dividend`, `board`, `coupon`, `macro`, `other`;
- `title` — название события;
- `source_url` — ссылка, можно оставить пустой;
- `importance` — `normal` или `high`.

## Архитектура

```text
app/
  main.py                 # aiogram handlers + background workers
  config.py               # настройки из .env
  db.py                   # SQLite: watchlist, alerts, digest prefs
  formatting.py           # HTML-форматирование ответов
  company_aliases.py      # популярные MOEX-тикеры и русские алиасы
  services/
    moex.py               # MOEX ISS: quotes, candles, market snapshot, screeners
    finnhub.py            # Finnhub quotes, candles, company news
    rss_news.py           # RSS search
    charts.py             # PNG-графики
    events.py             # локальный календарь событий
    analytics.py          # brief metrics, alert comparison, news tone
    digest.py             # digest formatter/time helpers
```

## Что делает `/brief`

`/brief SBER` собирает:

- текущую котировку;
- дневное изменение;
- динамику за период;
- диапазон цены;
- максимальную просадку периода;
- отклонение объёма от среднего;
- свежие новости;
- ближайшие события;
- простую rule-based оценку тона заголовков.

Это не AI-инвестсовет, а краткая информационная сводка.

## Продакшн-доработки

Для коммерческого запуска рекомендуется добавить:

1. Redis или отдельный job runner вместо in-process workers.
2. Платный источник real-time data и лицензию на redisplay, если данные показываются массовой аудитории.
3. Надёжный поставщик новостей и раскрытий, если RSS недостаточно.
4. Админ-панель для `events.csv` и источников данных.
5. Rate limiting по пользователям.
6. Мониторинг ошибок и uptime.
7. Юридически выверенный дисклеймер.

## Безопасное позиционирование

Правильно:

```text
Информационно-аналитический бот по рынкам. Не является индивидуальной инвестиционной рекомендацией.
```

Неправильно:

```text
Бот-брокер, который скажет, что купить, и будет торговать за пользователя.
```


## Исправление в этой сборке

В этой версии исправлена частая причина, когда бот "молчит" на `/start`: Telegram использует HTML-parse mode, поэтому символ `<` в примерах команд должен быть экранирован как `&lt;`. Раньше пример `/alert SBER pct < -3` мог ломать отправку help-сообщения.

После обновления обязательно пересоберите образ без кэша:

```bash
docker compose down
docker compose build --no-cache
docker compose up
```

## Диагностика, если бот не отвечает на `/start`

1. Проверьте, что рядом с `docker-compose.yml` есть файл `.env`, а не `.env.example`:

```bash
ls -la
cat .env
```

Минимум:

```env
TELEGRAM_BOT_TOKEN=123456789:AA...
```

2. Пересоберите и запустите контейнер:

```bash
docker compose down
docker compose up --build
```

В логах должны появиться строки вида:

```text
Bot authenticated as @your_bot_name, id=...
Polling started. Send /start to @your_bot_name
```

3. Если таких строк нет, посмотрите ошибку:

```bash
docker compose logs -f --tail=200 market-tg-bot
```

Частые причины:

- `.env` не создан или лежит не в той папке;
- неверный `TELEGRAM_BOT_TOKEN`;
- токен взят не у BotFather;
- тот же бот уже запущен в другом процессе/на другом сервере;
- на сервере нет исходящего доступа к `api.telegram.org`;
- у бота был webhook от старого запуска. Текущая версия удаляет webhook перед polling автоматически.

4. Быстрая проверка токена с сервера:

```bash
curl "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/getMe"
```

Ответ должен содержать `"ok":true`.
