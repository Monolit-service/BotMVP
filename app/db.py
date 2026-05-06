from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from app.models import PriceAlert


class BotDatabase:
    def __init__(self, path: str) -> None:
        self.path = path
        db_dir = Path(path).parent
        if str(db_dir) not in {"", "."}:
            os.makedirs(db_dir, exist_ok=True)

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init(self) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS watchlist (
                    telegram_user_id INTEGER NOT NULL,
                    symbol TEXT NOT NULL,
                    market TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (telegram_user_id, symbol, market)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS price_alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_user_id INTEGER NOT NULL,
                    symbol TEXT NOT NULL,
                    market TEXT NOT NULL,
                    metric TEXT NOT NULL,
                    operator TEXT NOT NULL,
                    threshold REAL NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    triggered_at TEXT,
                    last_value REAL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS user_preferences (
                    telegram_user_id INTEGER PRIMARY KEY,
                    digest_enabled INTEGER NOT NULL DEFAULT 0,
                    digest_time TEXT NOT NULL DEFAULT '09:30',
                    last_digest_date TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_alerts_active ON price_alerts(active, market, symbol)")

    def add_watch(self, telegram_user_id: int, symbol: str, market: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO watchlist (telegram_user_id, symbol, market, created_at) VALUES (?, ?, ?, ?)",
                (telegram_user_id, symbol.upper(), market.upper(), datetime.now(timezone.utc).isoformat()),
            )

    def remove_watch(self, telegram_user_id: int, symbol: str, market: str | None = None) -> int:
        with self.connect() as conn:
            if market:
                cursor = conn.execute(
                    "DELETE FROM watchlist WHERE telegram_user_id = ? AND symbol = ? AND market = ?",
                    (telegram_user_id, symbol.upper(), market.upper()),
                )
            else:
                cursor = conn.execute(
                    "DELETE FROM watchlist WHERE telegram_user_id = ? AND symbol = ?",
                    (telegram_user_id, symbol.upper()),
                )
            return cursor.rowcount

    def list_watch(self, telegram_user_id: int) -> list[tuple[str, str]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT symbol, market FROM watchlist WHERE telegram_user_id = ? ORDER BY market, symbol",
                (telegram_user_id,),
            ).fetchall()
        return [(row["symbol"], row["market"]) for row in rows]

    def add_alert(self, telegram_user_id: int, symbol: str, market: str, metric: str, operator: str, threshold: float) -> int:
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO price_alerts
                    (telegram_user_id, symbol, market, metric, operator, threshold, active, created_at)
                VALUES (?, ?, ?, ?, ?, ?, 1, ?)
                """,
                (
                    telegram_user_id,
                    symbol.upper(),
                    market.upper(),
                    metric.lower(),
                    operator,
                    float(threshold),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            return int(cursor.lastrowid)

    def list_alerts(self, telegram_user_id: int, active_only: bool = True) -> list[PriceAlert]:
        with self.connect() as conn:
            query = "SELECT * FROM price_alerts WHERE telegram_user_id = ?"
            params: list[object] = [telegram_user_id]
            if active_only:
                query += " AND active = 1"
            query += " ORDER BY active DESC, id DESC"
            rows = conn.execute(query, params).fetchall()
        return [_row_to_alert(row) for row in rows]

    def active_alerts(self) -> list[PriceAlert]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM price_alerts WHERE active = 1 ORDER BY id").fetchall()
        return [_row_to_alert(row) for row in rows]

    def delete_alert(self, telegram_user_id: int, alert_id: int) -> int:
        with self.connect() as conn:
            cursor = conn.execute(
                "DELETE FROM price_alerts WHERE telegram_user_id = ? AND id = ?",
                (telegram_user_id, alert_id),
            )
            return cursor.rowcount

    def mark_alert_triggered(self, alert_id: int, last_value: float | None) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE price_alerts SET active = 0, triggered_at = ?, last_value = ? WHERE id = ?",
                (datetime.now(timezone.utc).isoformat(), last_value, alert_id),
            )

    def touch_alert_value(self, alert_id: int, last_value: float | None) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE price_alerts SET last_value = ? WHERE id = ?", (last_value, alert_id))

    def enable_digest(self, telegram_user_id: int, digest_time: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO user_preferences
                    (telegram_user_id, digest_enabled, digest_time, created_at, updated_at)
                VALUES (?, 1, ?, ?, ?)
                ON CONFLICT(telegram_user_id) DO UPDATE SET
                    digest_enabled = 1,
                    digest_time = excluded.digest_time,
                    updated_at = excluded.updated_at
                """,
                (telegram_user_id, digest_time, now, now),
            )

    def disable_digest(self, telegram_user_id: int) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO user_preferences
                    (telegram_user_id, digest_enabled, digest_time, created_at, updated_at)
                VALUES (?, 0, '09:30', ?, ?)
                ON CONFLICT(telegram_user_id) DO UPDATE SET
                    digest_enabled = 0,
                    updated_at = excluded.updated_at
                """,
                (telegram_user_id, now, now),
            )

    def digest_users_due(self, local_date: str, current_hhmm: str) -> list[tuple[int, str]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT telegram_user_id, digest_time
                FROM user_preferences
                WHERE digest_enabled = 1
                  AND digest_time <= ?
                  AND COALESCE(last_digest_date, '') <> ?
                ORDER BY telegram_user_id
                """,
                (current_hhmm, local_date),
            ).fetchall()
        return [(int(row["telegram_user_id"]), str(row["digest_time"])) for row in rows]

    def mark_digest_sent(self, telegram_user_id: int, local_date: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as conn:
            conn.execute(
                "UPDATE user_preferences SET last_digest_date = ?, updated_at = ? WHERE telegram_user_id = ?",
                (local_date, now, telegram_user_id),
            )


def _row_to_alert(row: sqlite3.Row) -> PriceAlert:
    return PriceAlert(
        id=int(row["id"]),
        telegram_user_id=int(row["telegram_user_id"]),
        symbol=str(row["symbol"]),
        market=str(row["market"]),
        metric=str(row["metric"]),
        operator=str(row["operator"]),
        threshold=float(row["threshold"]),
        active=bool(row["active"]),
        created_at=str(row["created_at"]),
        triggered_at=str(row["triggered_at"]) if row["triggered_at"] else None,
        last_value=float(row["last_value"]) if row["last_value"] is not None else None,
    )
