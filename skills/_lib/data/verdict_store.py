#!/usr/bin/env python
"""Persistence for Verdict records.

research-debate writes here, when it is enabled at all. The dissent map is kept
as written rather than resolved into a single call: unresolved disagreement is
the output of that layer, not a failure to converge, and flattening it would
throw away the only part a reader cannot reconstruct.
"""

import sqlite3
from contextlib import closing
from pathlib import Path

from .schema import Verdict
from .store_support import (
    connect,
    dumps,
    loads,
    materialise,
    materialise_one,
    open_for_read,
    open_for_write,
)

_TABLE = "verdicts"

_NEWEST_FIRST = "ORDER BY COALESCE(NULLIF(authored_at, ''), created_at) DESC, id DESC"


def _to_verdict(row: sqlite3.Row) -> Verdict:
    return Verdict(
        valuation_id=row["valuation_id"],
        mode=row["mode"],
        votes=loads(row["votes_json"], list),
        dissent_map=row["dissent_map"],
        authored_at=row["authored_at"],
        id=row["id"],
    )


def save_verdict(verdict: Verdict, db_path: Path = None) -> int:
    """Persist a Verdict, stamp its row id onto it, and return that id."""
    path = open_for_write(db_path)
    with closing(connect(path)) as conn:
        exists = conn.execute(
            "SELECT 1 FROM valuations WHERE id = ?", (verdict.valuation_id,)
        ).fetchone()
        if exists is None:
            raise ValueError(
                f"No valuation with id {verdict.valuation_id}. There is nothing "
                f"to disagree about until the numbers exist."
            )
        cur = conn.execute(
            """INSERT INTO verdicts
               (valuation_id, mode, votes_json, dissent_map, authored_at)
               VALUES (?, ?, ?, ?, ?)""",
            (verdict.valuation_id, verdict.mode, dumps(verdict.votes),
             verdict.dissent_map, verdict.authored_at),
        )
        conn.commit()
        verdict.id = cur.lastrowid
        return verdict.id


def get_verdict(verdict_id: int, db_path: Path = None):
    """Return one Verdict by row id, or None if there is no such row."""
    path = open_for_read(db_path, _TABLE)
    with closing(connect(path)) as conn:
        row = conn.execute(
            "SELECT * FROM verdicts WHERE id = ?", (verdict_id,)
        ).fetchone()
    return materialise_one(row, _to_verdict, _TABLE)


def get_verdict_for_valuation(valuation_id: int, db_path: Path = None):
    """Return the current Verdict for a valuation, or None if it has none."""
    path = open_for_read(db_path, _TABLE)
    with closing(connect(path)) as conn:
        rows = conn.execute(
            f"SELECT * FROM verdicts WHERE valuation_id = ? {_NEWEST_FIRST}",
            (valuation_id,),
        ).fetchall()
    found = materialise(rows, _to_verdict, _TABLE)
    return found[0] if found else None


def list_verdicts(db_path: Path = None, limit: int = None) -> list:
    """Return persisted Verdicts, newest first, skipping unreadable rows."""
    path = open_for_read(db_path, _TABLE)
    sql = f"SELECT * FROM verdicts {_NEWEST_FIRST}"
    params = []
    if limit is not None:
        sql += " LIMIT ?"
        params.append(int(limit))

    with closing(connect(path)) as conn:
        rows = conn.execute(sql, params).fetchall()
    return materialise(rows, _to_verdict, _TABLE)
