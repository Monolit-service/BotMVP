from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Iterable

import feedparser

from app.models import NewsItem
from app.services.cache import TTLCache


class RssNewsClient:
    """RSS-based news search. Configure RSS_FEEDS in .env."""

    def __init__(self, feeds: list[str], cache_ttl_seconds: int = 300) -> None:
        self.feeds = feeds
        self.cache = TTLCache(ttl_seconds=cache_ttl_seconds)

    def is_enabled(self) -> bool:
        return bool(self.feeds)

    async def search(self, terms: Iterable[str], limit: int = 5) -> list[NewsItem]:
        terms_list = [t.lower() for t in terms if t]
        if not terms_list or not self.feeds:
            return []
        cache_key = ("rss_news", tuple(sorted(terms_list)), tuple(self.feeds))
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached[:limit]

        items: list[NewsItem] = []
        for feed_url in self.feeds:
            parsed = feedparser.parse(feed_url)
            source = parsed.feed.get("title", feed_url)
            for entry in parsed.entries:
                title = str(entry.get("title", ""))
                summary = str(entry.get("summary", ""))
                haystack = f"{title}\n{summary}".lower()
                if not any(term in haystack for term in terms_list):
                    continue
                published_at = None
                raw_date = entry.get("published") or entry.get("updated")
                if raw_date:
                    try:
                        published_at = parsedate_to_datetime(raw_date)
                        if published_at.tzinfo is None:
                            published_at = published_at.replace(tzinfo=timezone.utc)
                    except Exception:
                        published_at = None
                items.append(
                    NewsItem(
                        title=title or "Без заголовка",
                        url=str(entry.get("link", "")),
                        source=str(source),
                        published_at=published_at,
                        summary=summary,
                    )
                )

        items.sort(key=lambda item: item.published_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        self.cache.set(cache_key, items)
        return items[:limit]
