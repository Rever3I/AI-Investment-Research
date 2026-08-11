#!/usr/bin/env python
"""Persistence for Thesis records.

research-thesis writes here; research-valuation reads a thesis to value it, and
research-sellcheck resolves one much later to diff the original reasoning
against the present. That last consumer is why a thesis must not be able to
reference a candidate that does not exist.
"""

import sqlite3
from contextlib import closing
from pathlib import Path

from .schema import Thesis
from .store_support import (
    connect,
    dumps,
    loads,
    materialise,
    materialise_one,
    open_for_read,
    open_for_write,
)

_TABLE = "theses"

# Newest first, by when the author wrote it rather than by insertion order.
# Row ids only track time within one database file: dump two databases and
# reload them and the ids come back in dump order, which would hand
# research-sellcheck an older thesis to diff against.
_NEWEST_FIRST = "ORDER BY COALESCE(NULLIF(authored_at, ''), created_at) DESC, id DESC"


def _to_thesis(row: sqlite3.Row) -> Thesis:
    return Thesis(
        candidate_id=row["candidate_id"],
        business_overview=row["business_overview"],
        management=row["management"],
        competitors=row["competitors"],
        tam=row["tam"],
        risks=loads(row["risks_json"], list),
        variant_perception=row["variant_perception"],
        falsifiers=loads(row["falsifiers_json"], list),
        data_sources=loads(row["data_sources_json"], list),
        authored_at=row["authored_at"],
        id=row["id"],
    )


def save_thesis(thesis: Thesis, db_path: Path = None) -> int:
    """Persist a Thesis, stamp its row id onto it, and return that id.

    Raises ValueError if the candidate does not exist. Foreign keys would reject
    it anyway, but a bare IntegrityError does not say which id was wrong. The
    check runs on the same connection as the insert, so there is no window
    between them.
    """
    path = open_for_write(db_path)
    with closing(connect(path)) as conn:
        exists = conn.execute(
            "SELECT 1 FROM candidates WHERE id = ?", (thesis.candidate_id,)
        ).fetchone()
        if exists is None:
            raise ValueError(
                f"No candidate with id {thesis.candidate_id}. Run research-intake "
                f"for this ticker first, then attach the thesis to the id it returns."
            )
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
    """Return one Thesis by row id, or None if there is no such row.

    Raises UnreadableRecord if the row exists but does not satisfy the record
    contract — asking for a specific id and getting None would be a lie.
    """
    path = open_for_read(db_path, _TABLE)
    with closing(connect(path)) as conn:
        row = conn.execute(
            "SELECT * FROM theses WHERE id = ?", (thesis_id,)
        ).fetchone()
    return materialise_one(row, _to_thesis, _TABLE)


def get_thesis_for_candidate(candidate_id: int, db_path: Path = None):
    """Return the current Thesis for a candidate, or None if it has none.

    Re-researching a name writes a new thesis rather than overwriting the old
    one, so the history stays intact for research-sellcheck. The newest readable
    one is returned: a damaged row must not make the whole handoff unavailable.
    """
    path = open_for_read(db_path, _TABLE)
    with closing(connect(path)) as conn:
        rows = conn.execute(
            f"SELECT * FROM theses WHERE candidate_id = ? {_NEWEST_FIRST}",
            (candidate_id,),
        ).fetchall()
    found = materialise(rows, _to_thesis, _TABLE)
    return found[0] if found else None


def list_theses(db_path: Path = None, limit: int = None) -> list:
    """Return persisted Theses, newest first, skipping any that cannot be read."""
    path = open_for_read(db_path, _TABLE)
    sql = f"SELECT * FROM theses {_NEWEST_FIRST}"
    params = []
    if limit is not None:
        sql += " LIMIT ?"
        params.append(int(limit))

    with closing(connect(path)) as conn:
        rows = conn.execute(sql, params).fetchall()
    return materialise(rows, _to_thesis, _TABLE)
