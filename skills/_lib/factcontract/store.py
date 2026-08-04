#!/usr/bin/env python
"""fact_log — verified Facts land here, giving magnitude jump-detection its
historical baseline.

This is the one part of the Fact contract that improves with use: after it has
seen a few dozen daily moves for a ticker, it judges the next one against that
ticker's real distribution instead of a guessed threshold.

The table is created here rather than in data/db_init.py on purpose: the
verifier has to be able to run standalone, without any other layer having been
imported first. Same SQLite file, independent idempotent CREATE.

Writes never block adjudication — every write is wrapped, and a storage failure
degrades magnitude checking to absolute-range only rather than failing the
verification itself.
"""

import sqlite3
from pathlib import Path

# store.py lives at <repo>/skills/_lib/factcontract/store.py
DB_PATH = Path(__file__).resolve().parents[3] / "db" / "research.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS fact_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    entity      TEXT NOT NULL DEFAULT '',
    value       REAL NOT NULL,
    unit        TEXT NOT NULL,
    freq        TEXT NOT NULL,
    currency    TEXT NOT NULL DEFAULT '',
    as_of       TEXT NOT NULL,
    source      TEXT NOT NULL,
    grp         TEXT NOT NULL DEFAULT '',
    note        TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_fact_name ON fact_log(name, entity);
CREATE INDEX IF NOT EXISTS idx_fact_created ON fact_log(created_at);
"""

_initialised = False

# How many recent rows form the baseline for jump detection.
HISTORY_LIMIT = 40


def _connect():
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    global _initialised
    if _initialised:
        return True
    try:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = _connect()
        conn.executescript(_SCHEMA)
        conn.commit()
        conn.close()
        _initialised = True
        return True
    except Exception:
        return False


def record_many(facts) -> int:
    """Persist a batch of Facts. Returns rows written, 0 on any failure."""
    if not facts:
        return 0
    if not init_db():
        return 0
    rows = [
        (f.name, f.entity or "", float(f.value), f.unit, f.freq,
         f.currency or "", f.as_of, f.source, f.group or "", f.note or "")
        for f in facts
    ]
    try:
        conn = _connect()
        conn.executemany(
            """INSERT INTO fact_log
               (name, entity, value, unit, freq, currency, as_of, source, grp, note)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )
        conn.commit()
        conn.close()
        return len(rows)
    except Exception:
        return 0


def record(fact) -> int:
    return record_many([fact])


def history(name: str, entity: str = "", limit: int = HISTORY_LIMIT):
    """Recent values for a Fact name, newest first, as the jump-detection baseline.

    Repeated verifications of the same as_of are kept rather than deduplicated:
    a value that got verified several times was actually used several times, and
    that is worth weighting. Read failures return an empty list rather than
    raising.
    """
    if not init_db():
        return []
    try:
        conn = _connect()
        rows = conn.execute(
            """SELECT value FROM fact_log
               WHERE name = ? AND entity = ?
               ORDER BY id DESC LIMIT ?""",
            (name, entity or "", int(limit)),
        ).fetchall()
        conn.close()
        return [r["value"] for r in rows]
    except Exception:
        return []


def stats(days: int = 30) -> dict:
    """Per-Fact summary over a recent window: count, last seen, observed range."""
    if not init_db():
        return {}
    try:
        conn = _connect()
        rows = conn.execute(
            """SELECT name, entity, COUNT(*) AS n, MAX(created_at) AS last_seen,
                      MIN(value) AS lo, MAX(value) AS hi
               FROM fact_log
               WHERE created_at >= datetime('now', ?)
               GROUP BY name, entity
               ORDER BY n DESC""",
            (f"-{int(days)} days",),
        ).fetchall()
        conn.close()
        return {
            f"{r['name']}@{r['entity']}" if r["entity"] else r["name"]: {
                "n": r["n"], "last_seen": r["last_seen"],
                "min": r["lo"], "max": r["hi"],
            }
            for r in rows
        }
    except Exception:
        return {}
