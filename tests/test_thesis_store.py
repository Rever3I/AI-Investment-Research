"""Persistence for Thesis records, and the handoff it exists to serve.

The list fields cross a JSON-text boundary, and `candidate_id` crosses a
referential one. Both are places where a wrong value persists cleanly and only
surfaces as a wrong answer much later.
"""

import pytest

from skills._lib.data.candidate_store import save_candidate
from skills._lib.data.db_init import init_db
from skills._lib.data.schema import Candidate, Thesis
from skills._lib.data.thesis_store import (
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
    """A real candidate, since a Thesis cannot exist without one."""
    return save_candidate(
        Candidate(
            ticker="NVDA", entry_path="screen", source_note="general search",
            market="US", raw_rationale="AI capex beneficiary",
            discovered_at="2026-08-04T12:00:00Z",
        ),
        db_path=db,
    )


def _thesis(candidate_id, **overrides):
    kwargs = dict(
        candidate_id=candidate_id,
        business_overview="Designs accelerators for AI training and inference.",
        management="Founder-led since 1993, insider ownership around 3.5%.",
        competitors="AMD, Intel, in-house hyperscaler silicon",
        tam="$400B accelerated computing by 2030",
        risks=["customer concentration", "export controls", "capex digestion"],
        variant_perception="The market prices the GPU and ignores the networking attach.",
        falsifiers=["two consecutive quarters of hyperscaler capex guiding down"],
        data_sources=["sec-xbrl:10-K FY2025", "earnings call transcript Q1 FY2026"],
        authored_at="2026-08-04T12:00:00Z",
    )
    kwargs.update(overrides)
    return Thesis(**kwargs)


# ── writing ───────────────────────────────────────────────────────

def test_save_returns_a_row_id(db, candidate_id):
    assert save_thesis(_thesis(candidate_id), db_path=db) > 0


def test_save_stamps_the_row_id_onto_the_record(db, candidate_id):
    thesis = _thesis(candidate_id)
    row_id = save_thesis(thesis, db_path=db)
    assert thesis.id == row_id


def test_save_rejects_a_candidate_that_does_not_exist(db, candidate_id):
    """A thesis about a candidate nobody screened is a dangling reference, and
    research-sellcheck would later resolve it to nothing."""
    with pytest.raises(ValueError) as excinfo:
        save_thesis(_thesis(999999), db_path=db)
    assert "999999" in str(excinfo.value)


def test_save_works_on_a_database_the_fact_contract_created(db, candidate_id):
    from skills._lib.factcontract import store as fact_store

    fact_store.init_db(db)
    assert save_thesis(_thesis(candidate_id), db_path=db) > 0


# ── reading back ──────────────────────────────────────────────────

def test_thesis_round_trips_including_its_list_fields(db, candidate_id):
    original = _thesis(candidate_id)
    row_id = save_thesis(original, db_path=db)
    restored = get_thesis(row_id, db_path=db)

    assert restored == original
    assert isinstance(restored.risks, list)
    assert restored.risks == original.risks
    assert restored.falsifiers == original.falsifiers
    assert restored.data_sources == original.data_sources


def test_an_empty_optional_list_round_trips_as_a_list(db, candidate_id):
    original = _thesis(candidate_id, falsifiers=[], data_sources=[])
    row_id = save_thesis(original, db_path=db)
    restored = get_thesis(row_id, db_path=db)
    assert restored.falsifiers == []
    assert restored.data_sources == []


def test_text_with_quotes_and_newlines_survives(db, candidate_id):
    tricky = 'He said "no comment" —\nthen guided down.\t{"not": "json"}'
    row_id = save_thesis(
        _thesis(candidate_id, variant_perception=tricky), db_path=db
    )
    assert get_thesis(row_id, db_path=db).variant_perception == tricky


def test_non_ascii_prose_survives(db, candidate_id):
    """output_language can be zh-CN, so the store has to carry CJK unharmed."""
    chinese = "市场只给 GPU 定价，忽略了网络设备的附加率。"
    row_id = save_thesis(
        _thesis(candidate_id, variant_perception=chinese), db_path=db
    )
    assert get_thesis(row_id, db_path=db).variant_perception == chinese


def test_get_returns_none_for_an_unknown_id(db, candidate_id):
    save_thesis(_thesis(candidate_id), db_path=db)
    assert get_thesis(9999, db_path=db) is None


# ── finding the thesis for a candidate ────────────────────────────

def test_get_for_candidate_returns_the_thesis(db, candidate_id):
    row_id = save_thesis(_thesis(candidate_id), db_path=db)
    assert get_thesis_for_candidate(candidate_id, db_path=db).id == row_id


def test_get_for_candidate_returns_the_newest_when_rewritten(db, candidate_id):
    """Re-researching a name writes a second thesis. The current one is the one
    that should come back."""
    save_thesis(_thesis(candidate_id, variant_perception="first pass"), db_path=db)
    newer = save_thesis(
        _thesis(candidate_id, variant_perception="revised after Q2"), db_path=db
    )
    found = get_thesis_for_candidate(candidate_id, db_path=db)
    assert found.id == newer
    assert found.variant_perception == "revised after Q2"


def test_get_for_candidate_returns_none_when_unresearched(db, candidate_id):
    save_thesis(_thesis(candidate_id), db_path=db)
    other = save_candidate(
        Candidate(ticker="AVGO", entry_path="screen", source_note="x", market="US",
                  raw_rationale="x", discovered_at="2026-08-04T12:00:00Z"),
        db_path=db,
    )
    assert get_thesis_for_candidate(other, db_path=db) is None


# ── listing ───────────────────────────────────────────────────────

def test_list_returns_newest_first(db, candidate_id):
    first = save_thesis(_thesis(candidate_id, variant_perception="one"), db_path=db)
    second = save_thesis(_thesis(candidate_id, variant_perception="two"), db_path=db)
    assert [t.id for t in list_theses(db_path=db)] == [second, first]


def test_list_honours_limit(db, candidate_id):
    for note in ("a", "b", "c"):
        save_thesis(_thesis(candidate_id, variant_perception=note), db_path=db)
    assert len(list_theses(db_path=db, limit=2)) == 2


def test_list_on_an_initialised_but_empty_database_returns_empty(db):
    init_db(db)
    assert list_theses(db_path=db) == []


# ── reads do not create anything ──────────────────────────────────

def test_reads_do_not_create_a_database(tmp_path):
    missing = tmp_path / "typo.db"
    for call in (
        lambda: list_theses(db_path=missing),
        lambda: get_thesis(1, db_path=missing),
        lambda: get_thesis_for_candidate(1, db_path=missing),
    ):
        with pytest.raises(FileNotFoundError):
            call()
    assert not missing.exists()


def test_reads_report_clearly_when_only_the_fact_log_exists(db):
    """The Fact contract shares this database and creates it holding only
    fact_log. A file-existence check would sail past that and die on the SELECT."""
    from skills._lib.factcontract import store as fact_store

    fact_store.init_db(db)
    with pytest.raises(FileNotFoundError):
        list_theses(db_path=db)
