"""Saved screening criteria — the thing `Candidate.screened` refers to.

Before this existed, `screened` was always False and `profile_used` always
empty, because a profile name had nothing to name.
"""

import pytest

from airesearch.data.schema import Candidate, SchemaError, ScreenProfile
from airesearch.data.screen_store import (
    delete_screen_profile,
    get_screen_profile,
    list_screen_profiles,
    save_screen_profile,
)
from airesearch.data.store_support import UnreadableRecord


@pytest.fixture
def db(tmp_path):
    """A scratch database path — save_screen_profile creates the schema."""
    return tmp_path / "research.db"


def _profile(name="quality-industrials", **overrides):
    kwargs = dict(
        name=name,
        criteria={"market": "US", "sector": "industrials", "min_roic": 0.12},
        notes="what I actually look for",
    )
    kwargs.update(overrides)
    return ScreenProfile(**kwargs)


# ── the record contract ───────────────────────────────────────────

def test_a_profile_needs_a_name():
    with pytest.raises(SchemaError):
        _profile(name="   ")


def test_a_profile_with_no_criteria_is_refused():
    """That case is a general search, and `screened=False` with an empty
    `profile_used` already records it correctly. Allowing an empty profile
    would let a run claim it screened when it did not."""
    with pytest.raises(SchemaError):
        _profile(criteria={})


def test_criteria_must_be_a_mapping():
    with pytest.raises(SchemaError) as excinfo:
        _profile(criteria=["min_roic > 0.12"])
    assert "dict" in str(excinfo.value)


def test_the_name_is_stored_stripped():
    """`profile_used` is compared literally, so a trailing space would make a
    saved profile unreachable by the name the user typed."""
    assert _profile(name="  my screen  ").name == "my screen"


def test_no_vocabulary_is_imposed_on_the_criteria():
    """A fixed set of permitted metrics would be the built-in screening
    checklist this pipeline promises not to impose."""
    odd = _profile(criteria={"管理层持股": ">5%", "whatever_i_want": [1, 2, 3]})
    assert odd.criteria["whatever_i_want"] == [1, 2, 3]


# ── round trips ───────────────────────────────────────────────────

def test_a_saved_profile_reads_back_intact(db):
    save_screen_profile(_profile(), db_path=db)
    got = get_screen_profile("quality-industrials", db_path=db)
    assert got.criteria == {"market": "US", "sector": "industrials", "min_roic": 0.12}
    assert got.notes == "what I actually look for"


def test_saving_stamps_the_row_id(db):
    profile = _profile()
    row_id = save_screen_profile(profile, db_path=db)
    assert profile.id == row_id and row_id > 0


def test_a_name_that_was_never_saved_reads_as_none(db):
    save_screen_profile(_profile(), db_path=db)
    assert get_screen_profile("no-such-screen", db_path=db) is None


def test_lookup_ignores_surrounding_whitespace(db):
    save_screen_profile(_profile(), db_path=db)
    assert get_screen_profile(" quality-industrials ", db_path=db) is not None


def test_saving_the_same_name_twice_replaces_it(db):
    """A screen is revised, not versioned. Two rows under one name would leave
    `profile_used` pointing at criteria nobody can identify."""
    save_screen_profile(_profile(), db_path=db)
    save_screen_profile(_profile(criteria={"min_roic": 0.20}), db_path=db)

    assert len(list_screen_profiles(db_path=db)) == 1
    assert get_screen_profile("quality-industrials",
                              db_path=db).criteria == {"min_roic": 0.20}


def test_replacing_a_profile_still_returns_a_usable_id(db):
    """ON CONFLICT DO UPDATE reports lastrowid as 0 on some SQLite builds, and
    a caller that stored that id would later look up row 0."""
    save_screen_profile(_profile(), db_path=db)
    again = _profile(criteria={"min_roic": 0.20})
    row_id = save_screen_profile(again, db_path=db)
    assert row_id and again.id == row_id
    assert get_screen_profile("quality-industrials", db_path=db).id == row_id


def test_cjk_criteria_survive_the_round_trip(db):
    save_screen_profile(_profile(name="我的筛子", criteria={"行业": "工业"}),
                        db_path=db)
    assert get_screen_profile("我的筛子", db_path=db).criteria == {"行业": "工业"}


# ── listing and deleting ──────────────────────────────────────────

def test_profiles_list_alphabetically(db):
    for name in ("zeta", "Alpha", "mid"):
        save_screen_profile(_profile(name=name), db_path=db)
    names = [p.name for p in list_screen_profiles(db_path=db)]
    assert names == ["Alpha", "mid", "zeta"]


def test_deleting_reports_whether_there_was_anything_to_delete(db):
    save_screen_profile(_profile(), db_path=db)
    assert delete_screen_profile("quality-industrials", db_path=db) is True
    assert delete_screen_profile("quality-industrials", db_path=db) is False


def test_a_candidate_keeps_its_profile_name_after_the_profile_is_deleted(db):
    """Which criteria produced a candidate is a historical fact. Rewriting it
    because the profile was later deleted would edit the past."""
    from airesearch.data.candidate_store import get_candidate, save_candidate

    save_screen_profile(_profile(), db_path=db)
    candidate = Candidate(
        ticker="CAT", entry_path="screen", source_note="quality-industrials",
        market="US", raw_rationale="surfaced by the saved screen",
        discovered_at="2026-08-12T12:00:00Z",
        screened=True, profile_used="quality-industrials",
    )
    save_candidate(candidate, db_path=db)
    delete_screen_profile("quality-industrials", db_path=db)

    kept = get_candidate(candidate.id, db_path=db)
    assert kept.profile_used == "quality-industrials" and kept.screened is True


# ── reads before anything was written ─────────────────────────────

def test_reads_do_not_create_the_database(tmp_path):
    missing = tmp_path / "nothing-here.db"
    with pytest.raises(FileNotFoundError):
        list_screen_profiles(db_path=missing)
    assert not missing.exists()


def test_a_row_that_cannot_be_read_names_itself(db):
    """The table permits rows the record does not: criteria_json only has to be
    non-empty text. One such row must not take down the whole listing."""
    import sqlite3

    save_screen_profile(_profile(), db_path=db)
    save_screen_profile(_profile(name="broken"), db_path=db)
    conn = sqlite3.connect(str(db))
    conn.execute("UPDATE screen_profiles SET criteria_json='[]' WHERE name='broken'")
    conn.commit()
    conn.close()

    survivors = [p.name for p in list_screen_profiles(db_path=db)]
    assert survivors == ["quality-industrials"]
    with pytest.raises(UnreadableRecord) as excinfo:
        get_screen_profile("broken", db_path=db)
    assert "broken" in str(excinfo.value) or "screen_profiles" in str(excinfo.value)
