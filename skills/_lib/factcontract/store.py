#!/usr/bin/env python
"""fact_log — verified Facts land here, giving magnitude jump detection its
historical baseline.

This is the one part of the Fact contract that improves with use: after it has
seen a few dozen daily moves for a ticker, it judges the next one against that
ticker's real distribution instead of a guessed threshold.

The table is created here rather than in data/db_init.py on purpose: the
verifier has to be able to run standalone, without any other layer having been
imported first. Same SQLite file, independent idempotent CREATE.

A storage failure degrades magnitude checking to absolute-range only rather than
failing verification itself — but it is logged rather than swallowed, so a
persistently broken store is visible instead of silently disabling the baseline.
"""

import logging
import sqlite3
from contextlib import closing
from pathlib import Path

_log = logging.getLogger(__name__)

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
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00','now'))
);
CREATE INDEX IF NOT EXISTS idx_fact_name ON fact_log(name, entity);
CREATE INDEX IF NOT EXISTS idx_fact_created ON fact_log(created_at);
"""

# How many recent rows form the baseline for jump detection.
HISTORY_LIMIT = 40


def _resolve(db_path) -> Path:
    return Path(db_path) if db_path else DB_PATH


def _connect(path: Path):
    conn = sqlite3.connect(str(path), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db(db_path=None) -> bool:
    """Create fact_log if absent. Cheap and idempotent, so it is not cached:
    caching it would leave the store permanently broken if the database file is
    replaced or removed mid-session."""
    path = _resolve(db_path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(_connect(path)) as conn:
            conn.executescript(_SCHEMA)
            conn.commit()
        return True
    except (sqlite3.Error, OSError):
        _log.warning("Could not initialise the fact_log at %s", path, exc_info=True)
        return False


def record_many(facts, db_path=None) -> int:
    """Persist a batch of Facts. Returns rows written, 0 on any failure."""
    if not facts:
        return 0
    path = _resolve(db_path)
    if not init_db(path):
        return 0
    rows = [
        (f.name, f.entity or "", float(f.value), f.unit, f.freq,
         f.currency or "", f.as_of, f.source, f.group or "", f.note or "")
        for f in facts
    ]
    try:
        with closing(_connect(path)) as conn:
            conn.executemany(
                """INSERT INTO fact_log
                   (name, entity, value, unit, freq, currency, as_of, source, grp, note)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                rows,
            )
            conn.commit()
        return len(rows)
    except sqlite3.Error:
        _log.warning("Could not write %d Facts to %s", len(rows), path, exc_info=True)
        return 0


def record(fact, db_path=None) -> int:
    return record_many([fact], db_path=db_path)


def history(name: str, entity: str = "", limit: int = HISTORY_LIMIT, db_path=None):
    """Recent values for a Fact name, newest first, as the jump-detection baseline.

    Repeated verifications of the same as_of are kept rather than deduplicated:
    a value that got verified several times was actually used several times, and
    that is worth weighting. Read failures return an empty list rather than
    raising, so a broken store degrades the check instead of breaking the caller.
    """
    path = _resolve(db_path)
    if not init_db(path):
        return []
    try:
        with closing(_connect(path)) as conn:
            rows = conn.execute(
                """SELECT value FROM fact_log
                   WHERE name = ? AND entity = ?
                   ORDER BY id DESC LIMIT ?""",
                (name, entity or "", int(limit)),
            ).fetchall()
        return [r["value"] for r in rows]
    except sqlite3.Error:
        _log.warning("Could not read Fact history for %s from %s", name, path,
                     exc_info=True)
        return []
