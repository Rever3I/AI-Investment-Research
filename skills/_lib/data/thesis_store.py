#!/usr/bin/env python
"""Persistence for Thesis records.

research-thesis writes here; research-valuation reads a thesis to value it, and
research-sellcheck resolves one much later to diff the original reasoning
against the present. That last consumer is why a thesis must not be able to
reference a candidate that does not exist.
"""

from contextlib import closing
from pathlib import Path

import sqlite3

from .schema import Thesis
from .store_support import (
    connect,
    dumps,
    loads,
    open_for_read,
    open_for_write,
    row_exists,
)

_TABLE = "theses"


def _to_thesis(row: sqlite3.Row) -> Thesis:
    return Thesis(
        candidate_id=row["candidate_id"],
        business_overview=row["business_overview"],
        management=row["management"],
        competitors=row["competitors"],
        tam=row["tam"],
        risks=loads(row["risks_json"], []),
        variant_perception=row["variant_perception"],
        falsifiers=loads(row["falsifiers_json"], []),
        data_sources=loads(row["data_sources_json"], []),
        authored_at=row["authored_at"],
        id=row["id"],
    )


def save_thesis(thesis: Thesis, db_path: Path = None) -> int:
    """Persist a Thesis, stamp its row id onto it, and return that id.

    Raises ValueError if the candidate does not exist. The database would reject
    it anyway now that foreign keys are enforced, but a bare IntegrityError does
    not tell the caller which id was wrong.
    """
    path = open_for_write(db_path)
    if not row_exists(path, "candidates", thesis.candidate_id):
        raise ValueError(
            f"No candidate with id {thesis.candidate_id}. Run research-intake "
            f"for this ticker first, then attach the thesis to the id it returns."
        )
    with closing(connect(path)) as conn:
        cur = conn.execute(
            """INSERT INTO theses
               (candidate_id, business_overview, management, competitors, tam,
                risks_json, variant_perception, falsifiers_json,
                data_sources_json, authored_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (thesis.candidate_id, thesis.business_overview, thesis.management,
             thesis.competitors, thesis.tam, dumps(thesis.risks),
             thesis.variant_perception, dumps(thesis.falsifiers),
             dumps(thesis.data_sources), thesis.authored_at),
        )
        conn.commit()
        thesis.id = cur.lastrowid
        return thesis.id


def get_thesis(thesis_id: int, db_path: Path = None):
    """Return one Thesis by row id, or None if there is no such row."""
    path = open_for_read(db_path, _TABLE)
    with closing(connect(path)) as conn:
        row = conn.execute(
            "SELECT * FROM theses WHERE id = ?", (thesis_id,)
        ).fetchone()
    return _to_thesis(row) if row else None


def get_thesis_for_candidate(candidate_id: int, db_path: Path = None):
    """Return the current Thesis for a candidate, or None if it has none.

    Re-researching a name writes a new thesis rather than overwriting the old
    one, so the history stays intact for research-sellcheck. The newest is the
    one that represents what the author believes now.
    """
    path = open_for_read(db_path, _TABLE)
    with closing(connect(path)) as conn:
        row = conn.execute(
            "SELECT * FROM theses WHERE candidate_id = ? ORDER BY id DESC LIMIT 1",
            (candidate_id,),
        ).fetchone()
    return _to_thesis(row) if row else None


def list_theses(db_path: Path = None, limit: int = None) -> list:
    """Return persisted Theses, newest first."""
    path = open_for_read(db_path, _TABLE)
    sql = "SELECT * FROM theses ORDER BY id DESC"
    params = []
    if limit is not None:
        sql += " LIMIT ?"
        params.append(int(limit))

    with closing(connect(path)) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_to_thesis(r) for r in rows]
