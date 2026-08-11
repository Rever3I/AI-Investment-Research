#!/usr/bin/env python
"""Plumbing every record store shares.

Kept in one place because the alternative is each store growing its own copy and
the copies drifting: one store starts creating databases on read, another gains
a fix the rest never get. There are six record types coming, so the duplication
would have been fivefold.
"""

import json
from contextlib import closing
from pathlib import Path

from .db_init import DEFAULT_DB_PATH, connect, init_db


def resolve(db_path) -> Path:
    return Path(db_path) if db_path else DEFAULT_DB_PATH


def open_for_write(db_path) -> Path:
    """Resolve a path, creating the schema if this is a fresh install."""
    path = resolve(db_path)
    init_db(path)
    return path


def open_for_read(db_path, table: str) -> Path:
    """Resolve a path that must already hold `table`.

    Checks the table rather than the file, because the Fact contract shares this
    database and creates it on first use holding only `fact_log`. A file check
    would pass there and then fail on the SELECT with a bare "no such table".
    """
    path = resolve(db_path)
    if not path.exists() or not has_table(path, table):
        raise FileNotFoundError(
            f"No `{table}` records at {path} yet. Run the layer that writes them "
            f"first, or point db_path at a database that has them."
        )
    return path


def has_table(path: Path, table: str) -> bool:
    with closing(connect(path)) as conn:
        return conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone() is not None


def row_exists(path: Path, table: str, row_id) -> bool:
    if not has_table(path, table):
        return False
    with closing(connect(path)) as conn:
        return conn.execute(
            f"SELECT 1 FROM {table} WHERE id = ?", (row_id,)  # noqa: S608 - table is ours
        ).fetchone() is not None


def dumps(value) -> str:
    """Serialize a list or dict column.

    ensure_ascii=False keeps CJK readable in the database file itself, which
    matters when output_language is zh-CN and someone opens the db to check
    what was stored.
    """
    return json.dumps(value, ensure_ascii=False)


def loads(raw: str, fallback):
    """Deserialize a JSON column, tolerating a value written by something else.

    A store should not explode on one damaged row; the caller gets an empty list
    for that field and the rest of the record intact.
    """
    if raw in (None, ""):
        return fallback
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return fallback
    return value if isinstance(value, type(fallback)) else fallback
