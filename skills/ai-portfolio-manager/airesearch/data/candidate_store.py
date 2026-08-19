#!/usr/bin/env python
"""Persistence for Candidate records.

research-intake writes here; research-thesis reads from here to pick up a
candidate and continue the pipeline. Keeping the handoff in the database rather
than in conversation is what lets the two layers run in separate sessions.

Reads deliberately do not create the database, and they check for the table
rather than the file — see store_support.open_for_read for why.
"""

import sqlite3
from contextlib import closing
from pathlib import Path

from .schema import Candidate
from .store_support import (
    connect,
    materialise,
    materialise_one,
    open_for_read,
    open_for_write,
)

_TABLE = "candidates"

# See thesis_store for why insertion order is not a recency proxy.
_NEWEST_FIRST = "ORDER BY COALESCE(NULLIF(discovered_at, ''), created_at) DESC, id DESC"


def _to_candidate(row: sqlite3.Row) -> Candidate:
    return Candidate(
        ticker=row["ticker"],
        entry_path=row["entry_path"],
        source_note=row["source_note"],
        market=row["market"],
        raw_rationale=row["raw_rationale"],
        discovered_at=row["discovered_at"],
        screened=bool(row["screened"]),
        profile_used=row["profile_used"],
        id=row["id"],
    )


def save_candidate(candidate: Candidate, db_path: Path = None) -> int:
    """Persist a Candidate, stamp its row id onto it, and return that id."""
    path = open_for_write(db_path)
    with closing(connect(path)) as conn:
        cur = conn.execute(
            """INSERT INTO candidates
               (ticker, entry_path, source_note, market, raw_rationale,
                discovered_at, screened, profile_used)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (candidate.ticker, candidate.entry_path, candidate.source_note,
             candidate.market, candidate.raw_rationale, candidate.discovered_at,
             int(candidate.screened), candidate.profile_used),
        )
        conn.commit()
        candidate.id = cur.lastrowid
        return candidate.id


def get_candidate(candidate_id: int, db_path: Path = None):
    """Return one Candidate by row id, or None if there is no such row.

    Raises UnreadableRecord if the row exists but does not satisfy the record
    contract.
    """
    path = open_for_read(db_path, _TABLE)
    with closing(connect(path)) as conn:
        row = conn.execute(
            "SELECT * FROM candidates WHERE id = ?", (candidate_id,)
        ).fetchone()
    return materialise_one(row, _to_candidate, _TABLE)


def list_candidates(market: str = None, db_path: Path = None, limit: int = None) -> list:
    """Return persisted Candidates newest first, skipping any that cannot be read."""
    path = open_for_read(db_path, _TABLE)
    sql = "SELECT * FROM candidates"
    params = []
    if market:
        sql += " WHERE market = ?"
        params.append(market)
    sql += f" {_NEWEST_FIRST}"
    if limit is not None:
        sql += " LIMIT ?"
        params.append(int(limit))

    with closing(connect(path)) as conn:
        rows = conn.execute(sql, params).fetchall()
    return materialise(rows, _to_candidate, _TABLE)
