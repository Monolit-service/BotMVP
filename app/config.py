from __future__ import annotations

from functools import lru_cache
from typing import List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables or .env."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    telegram_bot_token: str = Field(..., alias="TELEGRAM_BOT_TOKEN")
    finnhub_api_key: str = Field(default="", alias="FINNHUB_API_KEY")
    rss_feeds: List[str] = Field(default_factory=list, alias="RSS_FEEDS")
    disclosure_rss_feeds: List[str] = Field(default_factory=list, alias="DISCLOSURE_RSS_FEEDS")
    sqlite_path: str = Field(default="./data/bot.sqlite3", alias="SQLITE_PATH")
    events_csv_path: str = Field(default="./data/events.csv", alias="EVENTS_CSV_PATH")
    default_period: str = Field(default="1m", alias="DEFAULT_PERIOD")
    default_market: str = Field(default="MOEX", alias="DEFAULT_MARKET")
    tz: str = Field(default="Europe/Moscow", alias="TZ")
    http_timeout_seconds: float = Field(default=15.0, alias="HTTP_TIMEOUT_SECONDS")
    cache_ttl_seconds: int = Field(default=60, alias="CACHE_TTL_SECONDS")
    alert_check_interval_seconds: int = Field(default=60, alias="ALERT_CHECK_INTERVAL_SECONDS")
    digest_check_interval_seconds: int = Field(default=60, alias="DIGEST_CHECK_INTERVAL_SECONDS")
    digest_default_time: str = Field(default="09:30", alias="DIGEST_DEFAULT_TIME")
    screener_limit: int = Field(default=10, alias="SCREENER_LIMIT")

    @field_validator("rss_feeds", "disclosure_rss_feeds", mode="before")
    @classmethod
    def split_url_list(cls, value):
        if not value:
            return []
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
