"""SQLite-lagring för familjekalendern."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

DEFAULT_DB = Path(__file__).parent / "data" / "familjekalender.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS members (
    id    INTEGER PRIMARY KEY,
    name  TEXT NOT NULL,
    color TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS calendars (
    id           INTEGER PRIMARY KEY,
    name         TEXT NOT NULL,
    kind         TEXT NOT NULL DEFAULT 'url',   -- 'url' (prenumeration) eller 'file' (uppladdad .ics)
    url          TEXT,
    member_id    INTEGER REFERENCES members(id) ON DELETE SET NULL,
    color        TEXT,
    last_fetched TEXT,
    last_error   TEXT,
    event_count  INTEGER NOT NULL DEFAULT 0
);

-- Händelser från kalendrar. Tider lagras som lokal svensk tid:
-- 'YYYY-MM-DDTHH:MM' för tidsatta, 'YYYY-MM-DD' för heldag (slut exklusivt).
CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY,
    calendar_id INTEGER NOT NULL REFERENCES calendars(id) ON DELETE CASCADE,
    uid         TEXT,
    title       TEXT NOT NULL,
    start       TEXT NOT NULL,
    end         TEXT NOT NULL,
    all_day     INTEGER NOT NULL DEFAULT 0,
    location    TEXT,
    description TEXT
);
CREATE INDEX IF NOT EXISTS events_range ON events(start, end);

CREATE TABLE IF NOT EXISTS shift_types (
    id         INTEGER PRIMARY KEY,
    member_id  INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    name       TEXT NOT NULL,
    short      TEXT,
    start_time TEXT,   -- 'HH:MM' eller NULL för heldag (t.ex. semester)
    end_time   TEXT,
    color      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS shifts (
    id            INTEGER PRIMARY KEY,
    member_id     INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    date          TEXT NOT NULL,
    shift_type_id INTEGER NOT NULL REFERENCES shift_types(id) ON DELETE CASCADE,
    note          TEXT,
    UNIQUE (member_id, date)
);
"""


def db_path() -> Path:
    return Path(os.environ.get("FAMILJEKALENDER_DB", DEFAULT_DB))


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    path = Path(path) if path else db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def rows(cursor) -> list[dict]:
    return [dict(r) for r in cursor.fetchall()]
