#!/usr/bin/env python
"""Persistence for Valuation records.

research-valuation writes here; research-portfolio reads from here. The scenario probabilities stored on this record are what
research-portfolio feeds into position sizing, which is why they travel with the
values rather than being restated later.
"""

import sqlite3
from contextlib import closing
from pathlib import Path

from .schema import Valuation
from .store_support import (
    connect,
    dumps,
    loads,
    materialise,
    materialise_one,
    open_for_read,
    open_for_write,
)

_TABLE = "valuations"

# See thesis_store for why insertion order is not a recency proxy.
_NEWEST_FIRST = "ORDER BY COALESCE(NULLIF(valued_at, ''), created_at) DESC, id DESC"


def _to_valuation(row: sqlite3.Row) -> Valuation:
    return Valuation(
        thesis_id=row["thesis_id"],
        scenarios=loads(row["scenarios_json"], list),
        discount_rate_source=row["discount_rate_source"],
        html_artifact_path=row["html_artifact_path"],
        valued_at=row["valued_at"],
        id=row["id"],
    )


def save_valuation(valuation: Valuation, db_path: Path = None) -> int:
    """Persist a Valuation, stamp its row id onto it, and return that id.

    Raises ValueError if the thesis does not exist. A valuation with no thesis
    behind it is a price target with no argument attached, which is the thing
    this pipeline exists to avoid.
    """
    path = open_for_write(db_path)
    with closing(connect(path)) as conn:
        exists = conn.execute(
            "SELECT 1 FROM theses WHERE id = ?", (valuation.thesis_id,)
        ).fetchone()
        if exists is None:
            raise ValueError(
                f"No thesis with id {valuation.thesis_id}. Run research-thesis "
                f"first, then value the thesis it returns."
            )
        cur = conn.execute(
            """INSERT INTO valuations
               (thesis_id, scenarios_json, discount_rate_source,
                html_artifact_path, valued_at)
               VALUES (?, ?, ?, ?, ?)""",
            (valuation.thesis_id, dumps(valuation.scenarios),
             valuation.discount_rate_source, valuation.html_artifact_path,
             valuation.valued_at),
        )
        conn.commit()
        valuation.id = cur.lastrowid
        return valuation.id


def get_valuation(valuation_id: int, db_path: Path = None):
    """Return one Valuation by row id, or None if there is no such row."""
    path = open_for_read(db_path, _TABLE)
    with closing(connect(path)) as conn:
        row = conn.execute(
            "SELECT * FROM valuations WHERE id = ?", (valuation_id,)
        ).fetchone()
    return materialise_one(row, _to_valuation, _TABLE)


def get_valuation_for_thesis(thesis_id: int, db_path: Path = None):
    """Return the current Valuation for a thesis, or None if it has none.

    Revaluing writes a new row rather than overwriting: the old numbers are the
    record of what was believed when the position was sized.
    """
    path = open_for_read(db_path, _TABLE)
    with closing(connect(path)) as conn:
        rows = conn.execute(
            f"SELECT * FROM valuations WHERE thesis_id = ? {_NEWEST_FIRST}",
            (thesis_id,),
        ).fetchall()
    found = materialise(rows, _to_valuation, _TABLE)
    return found[0] if found else None


def list_valuations(db_path: Path = None, limit: int = None) -> list:
    """Return persisted Valuations, newest first, skipping any that cannot be read."""
    path = open_for_read(db_path, _TABLE)
    sql = f"SELECT * FROM valuations {_NEWEST_FIRST}"
    params = []
    if limit is not None:
        sql += " LIMIT ?"
        params.append(int(limit))

    with closing(connect(path)) as conn:
        rows = conn.execute(sql, params).fetchall()
    return materialise(rows, _to_valuation, _TABLE)
