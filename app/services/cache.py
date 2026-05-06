from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Hashable


@dataclass
class CacheItem:
    value: Any
    expires_at: float


class TTLCache:
    def __init__(self, ttl_seconds: int = 60) -> None:
        self.ttl_seconds = ttl_seconds
        self._items: dict[Hashable, CacheItem] = {}

    def get(self, key: Hashable) -> Any | None:
        item = self._items.get(key)
        if not item:
            return None
        if item.expires_at <= time.time():
            self._items.pop(key, None)
            return None
        return item.value

    def set(self, key: Hashable, value: Any) -> None:
        self._items[key] = CacheItem(value=value, expires_at=time.time() + self.ttl_seconds)

    def clear(self) -> None:
        self._items.clear()
