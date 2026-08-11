#!/usr/bin/env python
"""Persistence for Sellcheck records.

research-sellcheck writes here when the user is deciding whether to exit. Each
row is a dated comparison against the thesis as originally written, so the
sequence of them is a record of how a view aged — which is the only way to find
out later whether the falsifiers were any good.
"""

import sqlite3
from contextlib import closing
from pathlib import Path

from .schema import Sellcheck
from .store_support import (
    connect,
    materialise,
    materialise_one,
    open_for_read,
    open_for_write,
)

_TABLE = "sellchecks"

_NEWEST_FIRST = "ORDER BY COALESCE(NULLIF(rechecked_at, ''), created_at) DESC, id DESC"


def _to_sellcheck(row: sqlite3.Row) -> Sellcheck:
    return Sellcheck(
        thesis_id=row["thesis_id"],
        trigger=row["trigger"],
        diff_summary=row["diff_summary"],
        rechecked_at=row["rechecked_at"],
        id=row["id"],
    )


def save_sellcheck(sellcheck: Sellcheck, db_path: Path = None) -> int:
    """Persist a Sellcheck, stamp its row id onto it, and return that id."""
    path = open_for_write(db_path)
    with closing(connect(path)) as conn:
        exists = conn.execute(
            "SELECT 1 FROM theses WHERE id = ?", (sellcheck.thesis_id,)
        ).fetchone()
        if exists is None:
            raise ValueError(
                f"No thesis with id {sellcheck.thesis_id}. A sellcheck compares "
                f"against what was originally argued; without that there is "
                f"nothing to compare to."
            )
        cur = conn.execute(
            """INSERT INTO sellchecks (thesis_id, trigger, diff_summary, rechecked_at)
               VALUES (?, ?, ?, ?)""",
            (sellcheck.thesis_id, sellcheck.trigger, sellcheck.diff_summary,
             sellcheck.rechecked_at),
        )
        conn.commit()
        sellcheck.id = cur.lastrowid
        return sellcheck.id


def get_sellcheck(sellcheck_id: int, db_path: Path = None):
    """Return one Sellcheck by row id, or None if there is no such row."""
    path = open_for_read(db_path, _TABLE)
    with closing(connect(path)) as conn:
        row = conn.execute(
            "SELECT * FROM sellchecks WHERE id = ?", (sellcheck_id,)
        ).fetchone()
    return materialise_one(row, _to_sellcheck, _TABLE)


def list_sellchecks_for_thesis(thesis_id: int, db_path: Path = None) -> list:
    """Every recheck of one thesis, newest first.

    The history is the point: a thesis rechecked three times, each saying the
    facts moved a little further from the original argument, is a different
    situation from one that just failed today.
    """
    path = open_for_read(db_path, _TABLE)
    with closing(connect(path)) as conn:
        rows = conn.execute(
            f"SELECT * FROM sellchecks WHERE thesis_id = ? {_NEWEST_FIRST}",
            (thesis_id,),
        ).fetchall()
    return materialise(rows, _to_sellcheck, _TABLE)


def list_sellchecks(db_path: Path = None, limit: int = None) -> list:
    """Return persisted Sellchecks, newest first, skipping unreadable rows."""
    path = open_for_read(db_path, _TABLE)
    sql = f"SELECT * FROM sellchecks {_NEWEST_FIRST}"
    params = []
    if limit is not None:
        sql += " LIMIT ?"
        params.append(int(limit))

    with closing(connect(path)) as conn:
        rows = conn.execute(sql, params).fetchall()
    return materialise(rows, _to_sellcheck, _TABLE)
