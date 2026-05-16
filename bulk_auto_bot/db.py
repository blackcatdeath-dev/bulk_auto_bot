from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

DB_PATH = Path("data/bulk_bot.sqlite3")

SCHEMA = """
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    score REAL NOT NULL,
    price REAL NOT NULL,
    reason TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    opened_ts INTEGER NOT NULL,
    closed_ts INTEGER,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    entry_price REAL NOT NULL,
    size REAL NOT NULL,
    take_profit REAL NOT NULL,
    stop_loss REAL NOT NULL,
    status TEXT NOT NULL,
    exit_price REAL,
    realized_pnl REAL,
    reason TEXT
);

CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL,
    payload TEXT NOT NULL
);
"""


def conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    return c


def insert_signal(ts: int, symbol: str, side: str, score: float, price: float, reason: str) -> None:
    with conn() as c:
        c.execute(
            "INSERT INTO signals(ts, symbol, side, score, price, reason) VALUES (?, ?, ?, ?, ?, ?)",
            (ts, symbol, side, score, price, reason),
        )


def open_position(ts: int, symbol: str, side: str, entry_price: float, size: float, tp: float, sl: float, reason: str) -> int:
    with conn() as c:
        cur = c.execute(
            """
            INSERT INTO positions(opened_ts, symbol, side, entry_price, size, take_profit, stop_loss, status, reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'OPEN', ?)
            """,
            (ts, symbol, side, entry_price, size, tp, sl, reason),
        )
        return int(cur.lastrowid)


def get_open_positions(symbol: str | None = None) -> list[sqlite3.Row]:
    with conn() as c:
        if symbol:
            return list(c.execute(
                "SELECT * FROM positions WHERE status='OPEN' AND symbol=? ORDER BY opened_ts ASC",
                (symbol,),
            ))
        return list(c.execute("SELECT * FROM positions WHERE status='OPEN' ORDER BY opened_ts ASC"))


def has_open_position(symbol: str) -> bool:
    return len(get_open_positions(symbol)) > 0


def has_open_position_same_side(symbol: str, side: str) -> bool:
    with conn() as c:
        row = c.execute(
            "SELECT 1 FROM positions WHERE status='OPEN' AND symbol=? AND side=? LIMIT 1",
            (symbol, side),
        ).fetchone()
        return row is not None



def close_position(position_id: int, ts: int, exit_price: float, realized_pnl: float, reason: str) -> None:
    with conn() as c:
        c.execute(
            """
            UPDATE positions
            SET status='CLOSED', closed_ts=?, exit_price=?, realized_pnl=?, reason=COALESCE(reason,'') || ' | close: ' || ?
            WHERE id=?
            """,
            (ts, exit_price, realized_pnl, reason, position_id),
        )


def last_open_ts(symbol: str) -> int | None:
    with conn() as c:
        row = c.execute(
            "SELECT opened_ts FROM positions WHERE symbol=? ORDER BY opened_ts DESC LIMIT 1",
            (symbol,),
        ).fetchone()
        return int(row[0]) if row else None
