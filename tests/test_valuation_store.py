"""Persistence for Valuation records.

The scenario probabilities stored here are what research-portfolio reads as
Kelly inputs, so this is the boundary where a rounding change or a dropped field
turns into a wrong position size.
"""

import pytest

from airesearch.data.candidate_store import save_candidate
from airesearch.data.db_init import init_db
from airesearch.data.schema import Candidate, Thesis, Valuation
from airesearch.data.thesis_store import save_thesis
from airesearch.data.store_support import UnreadableRecord
from airesearch.data.valuation_store import (
    get_valuation,
    get_valuation_for_thesis,
    list_valuations,
    save_valuation,
)


@pytest.fixture
def db(tmp_path):
    return tmp_path / "research.db"


@pytest.fixture
def thesis_id(db):
    candidate_id = save_candidate(
        Candidate(ticker="NVDA", entry_path="screen", source_note="x", market="US",
                  raw_rationale="why", discovered_at="2026-08-04T12:00:00Z"),
        db_path=db,
    )
    return save_thesis(
        Thesis(candidate_id=candidate_id, business_overview="designs accelerators",
               management="founder-led", competitors="AMD", tam="$400B",
               risks=["customer concentration"]),
        db_path=db,
    )


def _scenarios():
    return [
        {"name": "bull", "price_target": 290.0, "probability": 0.25,
         "assumptions": "attach holds", "growth_rate": 0.20, "terminal_share": 0.57},
        {"name": "base", "price_target": 196.0, "probability": 0.50,
         "assumptions": "", "growth_rate": 0.10, "terminal_share": 0.54},
        {"name": "bear", "price_target": 131.0, "probability": 0.25,
         "assumptions": "", "growth_rate": 0.00, "terminal_share": 0.51},
    ]


def _valuation(thesis_id, **overrides):
    kwargs = dict(
        thesis_id=thesis_id,
        scenarios=_scenarios(),
        discount_rate_source="US 10Y (4.2%) + 5% equity risk premium",
        html_artifact_path="reports/NVDA-2026-08-04.html",
        valued_at="2026-08-04T12:00:00Z",
    )
    kwargs.update(overrides)
    return Valuation(**kwargs)


# ── writing ───────────────────────────────────────────────────────

def test_save_returns_a_row_id(db, thesis_id):
    assert save_valuation(_valuation(thesis_id), db_path=db) > 0


def test_save_stamps_the_row_id_onto_the_record(db, thesis_id):
    valuation = _valuation(thesis_id)
    assert save_valuation(valuation, db_path=db) == valuation.id


def test_save_rejects_a_thesis_that_does_not_exist(db, thesis_id):
    """A price target with no argument behind it is the thing this pipeline
    exists to avoid."""
    with pytest.raises(ValueError) as excinfo:
        save_valuation(_valuation(999999), db_path=db)
    assert "999999" in str(excinfo.value)


# ── reading back ──────────────────────────────────────────────────

def test_scenarios_round_trip_intact(db, thesis_id):
    original = _valuation(thesis_id)
    row_id = save_valuation(original, db_path=db)
    restored = get_valuation(row_id, db_path=db)
    assert restored == original
    assert restored.scenarios == _scenarios()


def test_probabilities_survive_as_floats(db, thesis_id):
    """research-portfolio divides by these; a string would fail much later and
    somewhere less obvious."""
    row_id = save_valuation(_valuation(thesis_id), db_path=db)
    restored = get_valuation(row_id, db_path=db)
    for scenario in restored.scenarios:
        assert isinstance(scenario["probability"], float)
        assert isinstance(scenario["price_target"], float)


def test_probabilities_still_sum_to_one_after_a_round_trip(db, thesis_id):
    row_id = save_valuation(_valuation(thesis_id), db_path=db)
    restored = get_valuation(row_id, db_path=db)
    assert sum(s["probability"] for s in restored.scenarios) == pytest.approx(1.0)


def test_the_artifact_path_and_rate_provenance_are_kept(db, thesis_id):
    row_id = save_valuation(_valuation(thesis_id), db_path=db)
    restored = get_valuation(row_id, db_path=db)
    assert restored.html_artifact_path == "reports/NVDA-2026-08-04.html"
    assert "equity risk premium" in restored.discount_rate_source


def test_chinese_assumptions_survive(db, thesis_id):
    scenarios = _scenarios()
    scenarios[0]["assumptions"] = "网络附加率维持在三分之一"
    row_id = save_valuation(_valuation(thesis_id, scenarios=scenarios), db_path=db)
    restored = get_valuation(row_id, db_path=db)
    assert restored.scenarios[0]["assumptions"] == "网络附加率维持在三分之一"


def test_get_returns_none_for_an_unknown_id(db, thesis_id):
    save_valuation(_valuation(thesis_id), db_path=db)
    assert get_valuation(9999, db_path=db) is None


# ── the handoff to sizing ─────────────────────────────────────────

def test_get_for_thesis_returns_the_valuation(db, thesis_id):
    row_id = save_valuation(_valuation(thesis_id), db_path=db)
    assert get_valuation_for_thesis(thesis_id, db_path=db).id == row_id


def test_revaluing_appends_and_the_newest_wins(db, thesis_id):
    """The old numbers are the record of what was believed when the position was
    sized, so they are kept rather than overwritten."""
    save_valuation(_valuation(thesis_id, valued_at="2026-05-01T00:00:00Z"), db_path=db)
    newer = save_valuation(
        _valuation(thesis_id, valued_at="2026-08-04T00:00:00Z"), db_path=db
    )
    assert get_valuation_for_thesis(thesis_id, db_path=db).id == newer
    assert len(list_valuations(db_path=db)) == 2


def test_get_for_thesis_returns_none_when_unvalued(db, thesis_id):
    assert get_valuation_for_thesis(thesis_id, db_path=db) is None


# ── damaged rows do not take down the handoff ─────────────────────

def test_a_damaged_row_is_skipped_rather_than_breaking_the_list(db, thesis_id):
    import sqlite3
    from contextlib import closing

    good = save_valuation(_valuation(thesis_id), db_path=db)
    damaged = save_valuation(_valuation(thesis_id), db_path=db)
    with closing(sqlite3.connect(str(db))) as conn:
        conn.execute("UPDATE valuations SET scenarios_json = '{not json' WHERE id = ?",
                     (damaged,))
        conn.commit()

    assert [v.id for v in list_valuations(db_path=db)] == [good]


def test_asking_for_a_damaged_row_by_id_says_so(db, thesis_id):
    import sqlite3
    from contextlib import closing

    row_id = save_valuation(_valuation(thesis_id), db_path=db)
    with closing(sqlite3.connect(str(db))) as conn:
        conn.execute("UPDATE valuations SET scenarios_json = 'null' WHERE id = ?",
                     (row_id,))
        conn.commit()

    with pytest.raises(UnreadableRecord):
        get_valuation(row_id, db_path=db)


# ── reads do not create anything ──────────────────────────────────

def test_reads_do_not_create_a_database(tmp_path):
    missing = tmp_path / "typo.db"
    for call in (
        lambda: list_valuations(db_path=missing),
        lambda: get_valuation(1, db_path=missing),
        lambda: get_valuation_for_thesis(1, db_path=missing),
    ):
        with pytest.raises(FileNotFoundError):
            call()
    assert not missing.exists()


def test_list_on_an_initialised_but_empty_database_returns_empty(db):
    init_db(db)
    assert list_valuations(db_path=db) == []
