#!/usr/bin/env python
"""Plumbing every record store shares.

Kept in one place because the alternative is each store growing its own copy and
the copies drifting: one store starts creating databases on read, another gains
a fix the rest never get. There are five more record types coming, so the
duplication would have been fivefold.

Stores must resolve their database through `resolve()` and must NOT do
`from .db_init import DEFAULT_DB_PATH`. A value import binds the path at import
time, which puts it out of reach of the test fixture that redirects it — a store
written that way writes into the developer's real database the first time a test
forgets `db_path`.
"""

import json
import logging
import sqlite3
from contextlib import closing
from pathlib import Path

from . import db_init
from .db_init import connect, init_db
from .schema import SchemaError

_log = logging.getLogger(__name__)

# Table names this package owns. `row_exists` interpolates a table name into SQL,
# so the name is checked against this set rather than trusted.
KNOWN_TABLES = frozenset({
    "candidates", "theses", "valuations", "verdicts", "portfolios", "sellchecks",
    "market_cache", "calibration_memory",
})


def resolve(db_path) -> Path:
    """The database a call should use.

    Reads `db_init.DEFAULT_DB_PATH` through the module rather than binding its
    value, so redirecting it stays possible after this module is imported.
    """
    return Path(db_path) if db_path else db_init.DEFAULT_DB_PATH


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
    if not has_table(path, table):
        raise FileNotFoundError(
            f"No `{table}` records at {path} yet. Run the layer that writes them "
            f"first, or point db_path at a database that has them."
        )
    return path


def _connect_readonly(path: Path):
    """Open without the side effect of creating the file.

    Plain `sqlite3.connect` creates an empty database, which is how an
    inspection helper ends up leaving a stray half-formed file behind.
    """
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)


def has_table(path, table: str) -> bool:
    path = Path(path)
    if not path.exists():
        return False
    try:
        with closing(_connect_readonly(path)) as conn:
            return conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone() is not None
    except sqlite3.Error:
        _log.warning("Could not inspect %s for table %r", path, table, exc_info=True)
        return False


def row_exists(path, table: str, row_id) -> bool:
    """Whether `table` holds a row with this id.

    `table` is checked against KNOWN_TABLES because it is interpolated into the
    SQL: parameter binding cannot carry an identifier.
    """
    if table not in KNOWN_TABLES:
        raise ValueError(f"Unknown table {table!r}")
    path = Path(path)
    if not has_table(path, table):
        return False
    with closing(_connect_readonly(path)) as conn:
        return conn.execute(
            f"SELECT 1 FROM {table} WHERE id = ?", (row_id,)
        ).fetchone() is not None


def dumps(value) -> str:
    """Serialize a list or dict column.

    ensure_ascii=False keeps CJK readable in the database file itself, which
    matters when output_language is zh-CN and someone opens the db to check
    what was stored.
    """
    return json.dumps(value, ensure_ascii=False)


def loads(raw, expect=list):
    """Deserialize a JSON column, tolerating a value written by something else.

    `expect` is the container type, not a fallback value: passing a fallback made
    `loads(raw, None)` silently discard everything, and made `loads('true', 0)`
    return True because bool is a subclass of int.
    """
    if expect not in (list, dict):
        raise ValueError(f"expect must be list or dict, got {expect!r}")
    empty = expect()
    if raw in (None, ""):
        return empty
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, TypeError, ValueError):
        return empty
    return value if type(value) is expect else empty


def materialise(rows, build, table: str) -> list:
    """Build records from rows, dropping any the record contract rejects.

    The schema permits rows the dataclasses do not: `business_overview` is
    `NOT NULL DEFAULT ''` in SQL but required in Python. Without this, one such
    row — hand-written SQL, a partial import, a damaged JSON column — makes every
    list call raise, and the handoff that later layers depend on stays broken for
    good. Skipping the bad row and saying so loses one record instead of all of
    them.
    """
    records = []
    for row in rows:
        try:
            records.append(build(row))
        except SchemaError as exc:
            _log.warning("Skipping %s row id=%s: %s", table, row["id"], exc)
    return records


class UnreadableRecord(LookupError):
    """A stored row exists but does not satisfy its record contract."""


def materialise_one(row, build, table: str):
    """Build one record, naming the offending row if it cannot be built."""
    if row is None:
        return None
    try:
        return build(row)
    except SchemaError as exc:
        raise UnreadableRecord(
            f"{table} row id={row['id']} does not satisfy the {table} record "
            f"contract: {exc}"
        ) from exc
