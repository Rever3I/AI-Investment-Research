"""What happens when the database holds a row the record contract rejects.

The SQL schema and the dataclasses do not agree perfectly and cannot be made to:
a database written before the CHECK constraints existed, a partial import, or a
hand-written INSERT can all leave a row that `Thesis(...)` refuses to construct.

Before this was handled, one such row made `list_theses()` raise for the whole
database and made `get_thesis_for_candidate()` — the call research-valuation and
research-sellcheck depend on — permanently unavailable for that candidate, even
when a perfectly good newer thesis existed. Losing one record beats losing all
of them.
"""

import sqlite3
from contextlib import closing

import pytest

from airesearch.data.candidate_store import list_candidates, save_candidate
from airesearch.data.db_init import init_db
from airesearch.data.schema import Candidate, Thesis
from airesearch.data.store_support import UnreadableRecord
from airesearch.data.thesis_store import (
    get_thesis,
    get_thesis_for_candidate,
    list_theses,
    save_thesis,
)


@pytest.fixture
def db(tmp_path):
    return tmp_path / "research.db"


@pytest.fixture
def candidate_id(db):
    return save_candidate(
        Candidate(ticker="NVDA", entry_path="screen", source_note="x", market="US",
                  raw_rationale="why", discovered_at="2026-08-04T12:00:00Z"),
        db_path=db,
    )


def _damage(db, sql, params=()):
    """Write a row the record contract will reject, bypassing the CHECKs the way
    an older database or an outside tool would."""
    with closing(sqlite3.connect(str(db))) as conn:  # no PRAGMA, no CHECK bypass needed
        conn.execute(sql, params)
        conn.commit()


# ── the schema now stops these at the door ────────────────────────

def test_the_schema_rejects_a_thesis_with_no_overview(db, candidate_id):
    init_db(db)
    with pytest.raises(sqlite3.IntegrityError):
        _damage(db,
                "INSERT INTO theses (candidate_id, business_overview, risks_json) "
                "VALUES (?, '', '[\"r\"]')", (candidate_id,))


def test_the_schema_rejects_a_thesis_with_no_risks(db, candidate_id):
    init_db(db)
    with pytest.raises(sqlite3.IntegrityError):
        _damage(db,
                "INSERT INTO theses (candidate_id, business_overview, risks_json) "
                "VALUES (?, 'overview', '[]')", (candidate_id,))


def test_the_schema_rejects_a_candidate_with_no_rationale(db):
    init_db(db)
    with pytest.raises(sqlite3.IntegrityError):
        _damage(db,
                "INSERT INTO candidates (ticker, entry_path, market, raw_rationale, "
                "discovered_at) VALUES ('X', 'screen', 'US', '', '2026-08-04T12:00:00+00:00')")


# ── an older database can still hold one; reads must survive it ───

def test_a_damaged_row_does_not_take_down_the_list(db, candidate_id):
    good = save_thesis(
        Thesis(candidate_id=candidate_id, business_overview="real", management="m",
               competitors="c", tam="t", risks=["a risk"]),
        db_path=db,
    )
    # Corrupt the risks column of a *second* thesis directly.
    damaged = save_thesis(
        Thesis(candidate_id=candidate_id, business_overview="also real", management="m",
               competitors="c", tam="t", risks=["a risk"]),
        db_path=db,
    )
    _damage(db, "UPDATE theses SET risks_json = '{not json' WHERE id = ?", (damaged,))

    found = list_theses(db_path=db)
    assert [t.id for t in found] == [good]


def test_a_damaged_newest_row_does_not_block_the_handoff(db, candidate_id):
    """get_thesis_for_candidate is what research-valuation calls. A damaged
    newest row must not make the candidate permanently unresearchable."""
    good = save_thesis(
        Thesis(candidate_id=candidate_id, business_overview="usable", management="m",
               competitors="c", tam="t", risks=["a risk"],
               authored_at="2026-08-01T00:00:00Z"),
        db_path=db,
    )
    damaged = save_thesis(
        Thesis(candidate_id=candidate_id, business_overview="newer", management="m",
               competitors="c", tam="t", risks=["a risk"],
               authored_at="2026-08-04T00:00:00Z"),
        db_path=db,
    )
    _damage(db, "UPDATE theses SET risks_json = 'null' WHERE id = ?", (damaged,))

    found = get_thesis_for_candidate(candidate_id, db_path=db)
    assert found is not None
    assert found.id == good


def test_asking_for_a_damaged_row_by_id_says_so(db, candidate_id):
    """Returning None for a row that exists would be a lie, and the caller would
    go looking for a missing record instead of a broken one."""
    row_id = save_thesis(
        Thesis(candidate_id=candidate_id, business_overview="x", management="m",
               competitors="c", tam="t", risks=["a risk"]),
        db_path=db,
    )
    _damage(db, "UPDATE theses SET risks_json = '{not json' WHERE id = ?", (row_id,))

    with pytest.raises(UnreadableRecord) as excinfo:
        get_thesis(row_id, db_path=db)
    assert str(row_id) in str(excinfo.value)


def test_a_damaged_candidate_row_does_not_take_down_its_list(db, candidate_id):
    save_candidate(
        Candidate(ticker="AVGO", entry_path="screen", source_note="x", market="US",
                  raw_rationale="why", discovered_at="2026-08-04T12:00:00Z"),
        db_path=db,
    )
    _damage(db, "UPDATE candidates SET entry_path = 'nonsense' WHERE id = ?",
            (candidate_id,))

    found = list_candidates(db_path=db)
    assert [c.ticker for c in found] == ["AVGO"]


def test_skipped_rows_are_logged(db, candidate_id, caplog):
    """A silently shorter list is worse than a loud one."""
    import logging

    row_id = save_thesis(
        Thesis(candidate_id=candidate_id, business_overview="x", management="m",
               competitors="c", tam="t", risks=["a risk"]),
        db_path=db,
    )
    _damage(db, "UPDATE theses SET risks_json = '{not json' WHERE id = ?", (row_id,))

    with caplog.at_level(logging.WARNING):
        assert list_theses(db_path=db) == []
    assert any(str(row_id) in r.getMessage() for r in caplog.records)
