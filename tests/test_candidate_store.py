import pytest

from airesearch.data.candidate_store import (
    get_candidate,
    list_candidates,
    save_candidate,
)
from airesearch.data.db_init import init_db
from airesearch.data.schema import Candidate


@pytest.fixture
def db(tmp_path):
    """A scratch database path — save_candidate creates the schema on demand."""
    return tmp_path / "research.db"


def _candidate(**overrides):
    kwargs = dict(
        ticker="NVDA",
        entry_path="screen",
        source_note="general search",
        market="US",
        raw_rationale="AI capex beneficiary",
        discovered_at="2026-08-04T12:00:00Z",
    )
    kwargs.update(overrides)
    return Candidate(**kwargs)


def test_save_returns_a_row_id(db):
    assert save_candidate(_candidate(), db_path=db) > 0


def test_save_stamps_the_row_id_onto_the_record(db):
    # research-thesis needs this id to build a Thesis; without it the layer
    # handoff this module exists for cannot be performed.
    candidate = _candidate()
    row_id = save_candidate(candidate, db_path=db)
    assert candidate.id == row_id


def test_retrieved_candidates_carry_their_id(db):
    row_id = save_candidate(_candidate(), db_path=db)
    assert get_candidate(row_id, db_path=db).id == row_id
    assert list_candidates(db_path=db)[0].id == row_id


def test_reads_do_not_create_a_database(tmp_path):
    # A typo'd path must surface as an error, not as an empty list plus a stray
    # database file the user then has to find and delete.
    missing = tmp_path / "typo_reserach.db"
    with pytest.raises(FileNotFoundError):
        list_candidates(db_path=missing)
    with pytest.raises(FileNotFoundError):
        get_candidate(1, db_path=missing)
    assert not missing.exists()


def test_reads_report_clearly_when_the_fact_contract_made_the_database_first(db):
    """The Fact contract shares this database and creates it holding only
    fact_log. A read that only checked for the file would sail past that and die
    on the SELECT with a bare "no such table" — on a fresh clone, in the order
    the shipped SKILL.md tells the host to work."""
    from airesearch.factcontract import store as fact_store

    fact_store.init_db(db)
    assert db.exists()

    with pytest.raises(FileNotFoundError):
        list_candidates(db_path=db)
    with pytest.raises(FileNotFoundError):
        get_candidate(1, db_path=db)


def test_saving_works_after_the_fact_contract_made_the_database(db):
    """Writes must still succeed in that same situation, adding the candidates
    table alongside fact_log."""
    from airesearch.factcontract import store as fact_store

    fact_store.init_db(db)
    row_id = save_candidate(_candidate(), db_path=db)
    assert get_candidate(row_id, db_path=db).ticker == "NVDA"


def test_save_creates_the_schema_if_absent(db):
    # No explicit init_db() call — persisting must work on a fresh install.
    save_candidate(_candidate(), db_path=db)
    assert db.exists()


def test_saved_candidate_round_trips(db):
    original = _candidate(screened=True, profile_used="deep-value")
    row_id = save_candidate(original, db_path=db)
    assert get_candidate(row_id, db_path=db) == original


def test_screened_flag_survives_the_round_trip(db):
    row_id = save_candidate(_candidate(screened=False), db_path=db)
    # SQLite stores booleans as integers; it must come back as a bool, not 0.
    assert get_candidate(row_id, db_path=db).screened is False


def test_thesis_path_candidate_round_trips(db):
    original = _candidate(
        entry_path="thesis",
        source_note="Grid interconnect queues are the real AI capex ceiling.",
        raw_rationale="Sells the transformers that queue is waiting on.",
    )
    row_id = save_candidate(original, db_path=db)
    assert get_candidate(row_id, db_path=db) == original


def test_get_candidate_returns_none_for_unknown_id(db):
    save_candidate(_candidate(), db_path=db)
    assert get_candidate(9999, db_path=db) is None


def test_list_returns_every_saved_candidate(db):
    save_candidate(_candidate(ticker="NVDA"), db_path=db)
    save_candidate(_candidate(ticker="AVGO"), db_path=db)
    assert len(list_candidates(db_path=db)) == 2


def test_list_filters_by_market(db):
    save_candidate(_candidate(ticker="NVDA", market="US"), db_path=db)
    save_candidate(_candidate(ticker="000660.SZ", market="CN"), db_path=db)

    assert [c.ticker for c in list_candidates(market="US", db_path=db)] == ["NVDA"]
    assert [c.ticker for c in list_candidates(market="CN", db_path=db)] == ["000660.SZ"]


def test_list_returns_newest_first(db):
    save_candidate(_candidate(ticker="FIRST"), db_path=db)
    save_candidate(_candidate(ticker="SECOND"), db_path=db)
    assert [c.ticker for c in list_candidates(db_path=db)] == ["SECOND", "FIRST"]


def test_list_on_an_initialised_but_empty_database_returns_empty(db):
    init_db(db)
    assert list_candidates(db_path=db) == []


def test_list_honours_limit(db):
    for ticker in ("A", "B", "C"):
        save_candidate(_candidate(ticker=ticker), db_path=db)
    assert len(list_candidates(db_path=db, limit=2)) == 2
