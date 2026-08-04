#!/usr/bin/env python
"""Persistence for Candidate records.

research-intake writes here; research-thesis reads from here to pick up a
candidate and continue the pipeline. Keeping the handoff in the database rather
than in conversation is what lets the two layers run in separate sessions.

Reads deliberately do not create the database. A misconfigured path should
surface as "no such database" rather than quietly returning an empty list and
leaving a stray database file behind.
"""

import sqlite3
from contextlib import closing
from pathlib import Path

from .db_init import DEFAULT_DB_PATH, init_db
from .schema import Candidate


def _connect(path: Path):
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def _resolve(db_path) -> Path:
    return Path(db_path) if db_path else DEFAULT_DB_PATH


def _open_existing(db_path) -> Path:
    """Resolve a path that must already hold a database."""
    path = _resolve(db_path)
    if not path.exists():
        raise FileNotFoundError(
            f"No research database at {path}. Save a candidate first, "
            f"or point db_path at an existing database."
        )
    return path


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
    path = _resolve(db_path)
    init_db(path)
    with closing(_connect(path)) as conn:
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
    """Return one Candidate by row id, or None if there is no such row."""
    path = _open_existing(db_path)
    with closing(_connect(path)) as conn:
        row = conn.execute(
            "SELECT * FROM candidates WHERE id = ?", (candidate_id,)
        ).fetchone()
    return _to_candidate(row) if row else None


def list_candidates(market: str = None, db_path: Path = None, limit: int = None) -> list:
    """Return persisted Candidates newest first, optionally filtered by market."""
    path = _open_existing(db_path)
    sql = "SELECT * FROM candidates"
    params = []
    if market:
        sql += " WHERE market = ?"
        params.append(market)
    sql += " ORDER BY id DESC"
    if limit is not None:
        sql += " LIMIT ?"
        params.append(int(limit))

    with closing(_connect(path)) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_to_candidate(r) for r in rows]
