import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    is_admin INTEGER NOT NULL DEFAULT 0,
    alerts_paused INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS invites (
    email TEXT PRIMARY KEY,
    invited_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS login_tokens (
    jti TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    created_at TEXT NOT NULL,
    used_at TEXT
);
CREATE TABLE IF NOT EXISTS alert_rules (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    venue_ids TEXT NOT NULL,       -- comma separated
    weekdays TEXT NOT NULL,        -- comma separated, 0 = Monday
    time_from TEXT NOT NULL,       -- HH:MM, inclusive slot start
    time_to TEXT NOT NULL,         -- HH:MM, exclusive slot start
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS slots (
    key TEXT PRIMARY KEY,
    venue_id TEXT NOT NULL,
    court TEXT NOT NULL,
    date TEXT NOT NULL,
    start TEXT NOT NULL,
    "end" TEXT NOT NULL,
    spaces INTEGER NOT NULL,
    price TEXT,
    free_since TEXT,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS slots_venue_date ON slots(venue_id, date);
CREATE TABLE IF NOT EXISTS alerts_sent (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    slot_key TEXT NOT NULL,
    free_since TEXT NOT NULL,
    sent_at TEXT NOT NULL,
    PRIMARY KEY (user_id, slot_key, free_since)
);
CREATE TABLE IF NOT EXISTS provider_status (
    venue_id TEXT PRIMARY KEY,
    last_ok_at TEXT,
    last_error TEXT,
    last_error_at TEXT,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    baseline_done INTEGER NOT NULL DEFAULT 0
);
"""


class Database:
    def __init__(self, path: str):
        self.path = path
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._memory_conn = self._open() if path == ":memory:" else None

    def _open(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, check_same_thread=False, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        if self.path != ":memory:":
            conn.execute("PRAGMA journal_mode = WAL")
        return conn

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """A connection inside a transaction: commits on success, rolls back on error."""
        conn = self._memory_conn or self._open()
        try:
            with conn:
                yield conn
        finally:
            if conn is not self._memory_conn:
                conn.close()

    def init(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)
