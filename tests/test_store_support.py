"""The plumbing every record store shares.

Tested directly rather than only through the stores, because five more stores
will lean on it and a defect here would be five defects.
"""

import json

import pytest

from skills._lib.data.db_init import init_db
from skills._lib.data.store_support import (
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
    from skills._lib.factcontract import store as fact_store

    fact_store.init_db(db)
    with pytest.raises(FileNotFoundError) as excinfo:
        open_for_read(db, "candidates")
    assert "candidates" in str(excinfo.value)


def test_open_for_read_succeeds_once_the_table_exists(db):
    init_db(db)
    assert open_for_read(db, "candidates") == db


# ── row existence ─────────────────────────────────────────────────

def test_row_exists_is_false_without_the_table(db):
    from skills._lib.factcontract import store as fact_store

    fact_store.init_db(db)
    assert row_exists(db, "candidates", 1) is False


def test_row_exists_reflects_the_data(db):
    from skills._lib.data.candidate_store import save_candidate
    from skills._lib.data.schema import Candidate

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
    for value in ([], ["a", "b"], [{"k": 1}], {"a": 1}):
        assert loads(dumps(value), type(value)()) == value


def test_loads_falls_back_on_damaged_json():
    assert loads("{not json", []) == []


def test_loads_falls_back_on_null_and_empty():
    assert loads(None, []) == []
    assert loads("", []) == []


def test_loads_falls_back_when_the_type_is_wrong():
    """A column that should hold a list but holds an object must not hand the
    caller a dict, which would then fail somewhere less obvious."""
    assert loads(json.dumps({"a": 1}), []) == []
    assert loads(json.dumps(["a"]), {}) == {}
    assert loads(json.dumps("a string"), []) == []
