import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from skills._lib.factcontract import Fact, FactCheckError, FactError, verify
from skills._lib.factcontract.fact import now_utc


@pytest.fixture(autouse=True)
def isolated_store(monkeypatch, tmp_path):
    """Point the fact_log at a scratch DB so tests never touch the real one.

    Autouse because verify() reaches the store even with record=False — it reads
    history for jump detection, and that read creates the database file. Without
    this on every test, a plain verify() call would write into the repo's own db/.
    """
    from skills._lib.factcontract import store as store_mod

    monkeypatch.setattr(store_mod, "DB_PATH", tmp_path / "research.db")
    monkeypatch.setattr(store_mod, "_initialised", False)
    return store_mod


def _fresh(**overrides):
    kwargs = dict(
        name="AAPL_chg_pct", value=1.2, unit="pct", freq="intraday",
        as_of=now_utc().isoformat(), source="yfinance", entity="AAPL",
    )
    kwargs.update(overrides)
    return Fact(**kwargs)


# ── Fact construction is the first gate ───────────────────────────

def test_fact_rejects_missing_source():
    with pytest.raises(FactError):
        _fresh(source="")


def test_fact_rejects_unknown_unit():
    with pytest.raises(FactError):
        _fresh(unit="bananas")


def test_fact_rejects_non_numeric_value():
    with pytest.raises(FactError):
        _fresh(value="not a number")


def test_fact_normalizes_as_of_to_utc_iso():
    f = _fresh(as_of="2026-08-04T12:00:00Z")
    assert f.as_of == "2026-08-04T12:00:00+00:00"


# ── staleness is the hard stop ────────────────────────────────────

def test_verify_hard_stops_on_stale_data():
    stale = _fresh(as_of="2020-01-01T00:00:00Z")
    with pytest.raises(FactCheckError):
        verify([stale], record=False)


def test_verify_hard_stops_on_future_timestamp():
    future = _fresh(as_of=(now_utc() + timedelta(hours=5)).isoformat())
    with pytest.raises(FactCheckError):
        verify([future], record=False)


def test_verify_passes_fresh_data():
    report = verify([_fresh()], record=False)
    assert report["ok"] is True
    assert report["checked"] == 1


def test_verify_can_report_without_raising():
    stale = _fresh(as_of="2020-01-01T00:00:00Z")
    report = verify([stale], raise_on_error=False, record=False)
    assert report["ok"] is False
    assert report["errors"][0]["check"] == "staleness"


def test_point_freq_never_goes_stale():
    old_static = _fresh(freq="point", as_of="1999-01-01T00:00:00Z")
    report = verify([old_static], record=False)
    assert report["ok"] is True


# ── freq_align and magnitude are warnings, not stops ──────────────

def test_mixed_frequency_within_a_group_warns_but_passes():
    a = _fresh(name="NI", value=100, unit="usd", freq="quarterly",
               source="sec-xbrl", entity="NVDA", group="dcf")
    b = _fresh(name="Shares", value=1e9, unit="shares", freq="ttm",
               source="sec-xbrl", entity="NVDA", group="dcf")
    c = _fresh(name="CapEx", value=50, unit="usd", freq="quarterly",
               source="sec-xbrl", entity="NVDA", group="dcf")
    report = verify([a, b, c], record=False)
    assert report["ok"] is True
    assert any(w["check"] == "freq_align" and w["fact"] == "Shares"
               for w in report["warnings"])


def test_ungrouped_facts_are_exempt_from_freq_align():
    a = _fresh(name="NI", value=100, unit="usd", freq="quarterly", source="sec-xbrl")
    b = _fresh(name="Shares", value=1e9, unit="shares", freq="ttm", source="sec-xbrl")
    report = verify([a, b], record=False)
    assert not any(w["check"] == "freq_align" for w in report["warnings"])


def test_implausible_magnitude_warns_but_passes():
    absurd = _fresh(name="NVDA_chg_pct", value=9000.0, unit="pct", freq="daily")
    report = verify([absurd], record=False)
    assert report["ok"] is True
    assert any(w["check"] == "magnitude" for w in report["warnings"])


# ── the store: history is what makes jump detection possible ──────

def test_store_roundtrips_recorded_values(isolated_store):
    f = _fresh(name="NVDA_chg_pct", value=3.5, unit="pct", freq="daily", entity="NVDA")
    assert isolated_store.record_many([f]) == 1
    assert isolated_store.history("NVDA_chg_pct", "NVDA") == [3.5]


def test_store_writes_to_this_repos_database(isolated_store, tmp_path):
    isolated_store.record_many([_fresh()])
    assert (tmp_path / "research.db").exists()


def test_default_store_path_resolves_inside_repo():
    # Read the unpatched module-level default, which the autouse fixture overrides.
    import importlib

    store_mod = importlib.import_module("skills._lib.factcontract.store")
    default = Path(store_mod.__file__).resolve().parents[3] / "db" / "research.db"
    repo_root = Path(__file__).resolve().parent.parent
    assert default == repo_root / "db" / "research.db"


def test_verify_records_passing_facts(isolated_store):
    verify([_fresh(name="MSFT_chg_pct", value=1.1, entity="MSFT")], record=True)
    assert isolated_store.history("MSFT_chg_pct", "MSFT") == [1.1]


def test_verify_does_not_record_facts_that_hard_stopped(isolated_store):
    stale = _fresh(name="STALE_pct", value=1.1, entity="X", as_of="2020-01-01T00:00:00Z")
    verify([stale], raise_on_error=False, record=True)
    assert isolated_store.history("STALE_pct", "X") == []


def test_jump_against_history_warns(isolated_store):
    # Establish a baseline, then verify a value an order of magnitude above it.
    baseline = [_fresh(name="JUMP_pct", value=2.0, entity="X") for _ in range(5)]
    isolated_store.record_many(baseline)

    report = verify([_fresh(name="JUMP_pct", value=80.0, entity="X")],
                    record=False)
    assert any("jump_ratio" in w for w in report["warnings"])
