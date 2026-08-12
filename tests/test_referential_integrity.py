"""Referential integrity, which SQLite does not give you for free.

`REFERENCES` in a CREATE TABLE is inert unless every connection turns foreign
keys on: SQLite ships with `PRAGMA foreign_keys=0` for backward compatibility.
Without this, a thesis can point at a candidate that never existed, and the
error surfaces later as a lookup that returns nothing rather than as a write
that failed.
"""

import sqlite3
from contextlib import closing

import pytest

from airesearch.data.db_init import connect, init_db

ORPHANS = {
    "theses": "INSERT INTO theses (candidate_id, business_overview, risks_json) "
              "VALUES (99999, 'x', '[\"r\"]')",
    "valuations": "INSERT INTO valuations (thesis_id) VALUES (99999)",
    "verdicts": "INSERT INTO verdicts (valuation_id, mode) VALUES (99999, 'checklist')",
    "portfolios": "INSERT INTO portfolios (valuation_id, sizing_method, "
                  "recommended_position_pct) VALUES (99999, 'half_kelly', 1.0)",
    "sellchecks": "INSERT INTO sellchecks (thesis_id, trigger, diff_summary) "
                  "VALUES (99999, 'user_initiated', 'x')",
}


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "research.db"
    init_db(path)
    return path


def test_connect_enables_foreign_keys(db):
    with closing(connect(db)) as conn:
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


@pytest.mark.parametrize("table,sql", sorted(ORPHANS.items()))
def test_orphan_rows_are_rejected(db, table, sql):
    with closing(connect(db)) as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(sql)


def test_a_valid_reference_is_accepted(db):
    with closing(connect(db)) as conn:
        cur = conn.execute(
            "INSERT INTO candidates (ticker, entry_path, market, raw_rationale, "
            "discovered_at) VALUES ('NVDA', 'screen', 'US', 'why', "
            "'2026-08-04T12:00:00+00:00')"
        )
        conn.execute(
            "INSERT INTO theses (candidate_id, business_overview, risks_json) "
            "VALUES (?, 'real', '[\"a risk\"]')",
            (cur.lastrowid,),
        )
        conn.commit()
        assert conn.execute("SELECT COUNT(*) FROM theses").fetchone()[0] == 1


def test_connect_returns_rows_addressable_by_name(db):
    with closing(connect(db)) as conn:
        row = conn.execute("SELECT 1 AS answer").fetchone()
        assert row["answer"] == 1
