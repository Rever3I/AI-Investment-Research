"""The plumbing every record store shares.

Tested directly rather than only through the stores, because five more stores
will lean on it and a defect here would be five defects.
"""

import json

import pytest

from airesearch.data.db_init import init_db
from airesearch.data.store_support import (
    dumps,
    has_table,
    loads,
    open_for_read,
    open_for_write,
    row_exists,
)


@pytest.fixture
def db(tmp_path):
    return tmp_path / "research.db"


# ── opening ───────────────────────────────────────────────────────

def test_open_for_write_creates_the_schema(db):
    assert open_for_write(db) == db
    assert has_table(db, "candidates")


def test_open_for_read_raises_on_a_missing_database(db):
    with pytest.raises(FileNotFoundError):
        open_for_read(db, "candidates")


def test_open_for_read_does_not_create_anything(db):
    with pytest.raises(FileNotFoundError):
        open_for_read(db, "candidates")
    assert not db.exists()


def test_open_for_read_raises_when_the_table_is_absent(db):
    """The Fact contract creates this database holding only fact_log."""
    from airesearch.factcontract import store as fact_store

    fact_store.init_db(db)
    with pytest.raises(FileNotFoundError) as excinfo:
        open_for_read(db, "candidates")
    assert "candidates" in str(excinfo.value)


def test_open_for_read_succeeds_once_the_table_exists(db):
    init_db(db)
    assert open_for_read(db, "candidates") == db


# ── row existence ─────────────────────────────────────────────────

def test_row_exists_is_false_without_the_table(db):
    from airesearch.factcontract import store as fact_store

    fact_store.init_db(db)
    assert row_exists(db, "candidates", 1) is False


def test_row_exists_reflects_the_data(db):
    from airesearch.data.candidate_store import save_candidate
    from airesearch.data.schema import Candidate

    row_id = save_candidate(
        Candidate(ticker="NVDA", entry_path="screen", source_note="x", market="US",
                  raw_rationale="x", discovered_at="2026-08-04T12:00:00Z"),
        db_path=db,
    )
    assert row_exists(db, "candidates", row_id) is True
    assert row_exists(db, "candidates", row_id + 999) is False


# ── JSON columns ──────────────────────────────────────────────────

def test_dumps_keeps_cjk_readable_in_the_file():
    """A zh-CN run stores Chinese prose; escaping it makes the database
    unreadable to anyone inspecting it directly."""
    assert dumps(["网络附加率"]) == '["网络附加率"]'


def test_dumps_and_loads_round_trip():
    for value in ([], ["a", "b"], [{"k": 1}]):
        assert loads(dumps(value), list) == value
    assert loads(dumps({"a": 1}), dict) == {"a": 1}


def test_loads_falls_back_on_damaged_json():
    assert loads("{not json", list) == []


def test_loads_falls_back_on_null_and_empty():
    assert loads(None, list) == []
    assert loads("", list) == []


def test_loads_falls_back_when_the_type_is_wrong():
    """A column that should hold a list but holds an object must not hand the
    caller a dict, which would then fail somewhere less obvious."""
    assert loads(json.dumps({"a": 1}), list) == []
    assert loads(json.dumps(["a"]), dict) == {}
    assert loads(json.dumps("a string"), list) == []


def test_loads_does_not_mistake_a_bool_for_a_container():
    """bool is a subclass of int, and an isinstance-based check let it through."""
    assert loads(json.dumps(True), list) == []
    assert loads(json.dumps(1), list) == []


def test_loads_rejects_a_fallback_value_in_place_of_a_type():
    """Passing [] instead of list used to work by accident; passing None made it
    silently discard every value. Both are now loud."""
    for bad in ([], {}, None, str):
        with pytest.raises(ValueError):
            loads('["a"]', bad)
