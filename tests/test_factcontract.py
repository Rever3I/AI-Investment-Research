from datetime import timedelta
from pathlib import Path

import pytest

from airesearch.factcontract import Fact, FactCheckError, FactError, verify
from airesearch.factcontract.fact import now_utc
from airesearch.factcontract.store import DB_PATH as _UNPATCHED_DB_PATH


def _fresh(**overrides):
    kwargs = dict(
        name="AAPL_chg_pct", value=1.2, unit="pct", freq="intraday",
        as_of=now_utc().isoformat(), source="sec-xbrl", entity="AAPL",
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


# ── currency_align is the other hard stop ─────────────────────────

def test_one_entity_in_two_currencies_hard_stops():
    """Nothing converts between them, so a yuan price divided into dollar
    owner earnings is a valuation wrong by the exchange rate — and every digit
    of it looks ordinary."""
    price = _fresh(name="600519_price", value=1687.0, unit="usd",
                   currency="CNY", entity="600519.SS", freq="intraday")
    earnings = _fresh(name="600519_net_income", value=8.6e10, unit="usd",
                      currency="USD", entity="600519.SS", freq="ttm",
                      as_of=now_utc().isoformat())
    with pytest.raises(FactCheckError) as excinfo:
        verify([price, earnings], record=False)
    assert "currency_align" in str(excinfo.value)


def test_one_entity_consistently_in_yuan_passes():
    """The point of the check is mixing, not foreignness. Refusing every
    non-dollar figure would shut out the markets the adapters exist to reach."""
    price = _fresh(name="600519_price", value=1687.0, unit="usd",
                   currency="CNY", entity="600519.SS", freq="intraday")
    earnings = _fresh(name="600519_net_income", value=8.6e10, unit="usd",
                      currency="CNY", entity="600519.SS", freq="ttm")
    assert verify([price, earnings], record=False)["ok"] is True


def test_two_entities_in_different_currencies_are_not_a_conflict():
    """A yuan name and a dollar name in one report are not being divided into
    each other. Keying on entity is what keeps that from being a false stop."""
    a = _fresh(name="A_price", value=100.0, unit="usd", currency="CNY",
               entity="600519.SS", freq="intraday")
    b = _fresh(name="B_price", value=100.0, unit="usd", currency="USD",
               entity="KO", freq="intraday")
    assert verify([a, b], record=False)["ok"] is True


def test_an_unset_currency_is_an_unknown_not_a_disagreement():
    """Most Facts predate the field. Treating blank as a conflict would stop
    every existing pipeline rather than the one case that is wrong."""
    stated = _fresh(name="KO_price", value=86.84, unit="usd", currency="USD",
                    entity="KO", freq="intraday")
    blank = _fresh(name="KO_net_income", value=1.2e10, unit="usd",
                   entity="KO", freq="ttm")
    assert verify([stated, blank], record=False)["ok"] is True


def test_a_share_count_is_not_dragged_into_the_currency_check():
    shares = _fresh(name="KO_shares", value=4.31e9, unit="shares",
                    currency="USD", entity="KO", freq="point")
    price = _fresh(name="KO_price", value=1687.0, unit="usd", currency="CNY",
                   entity="KO", freq="intraday")
    assert verify([shares, price], record=False)["ok"] is True


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

def test_store_roundtrips_recorded_values(isolated_fact_store):
    f = _fresh(name="NVDA_chg_pct", value=3.5, unit="pct", freq="daily", entity="NVDA")
    assert isolated_fact_store.record_many([f]) == 1
    assert isolated_fact_store.history("NVDA_chg_pct", "NVDA") == [3.5]


def test_store_creates_its_database_on_first_write(isolated_fact_store):
    isolated_fact_store.record_many([_fresh()])
    assert isolated_fact_store.DB_PATH.exists()


def test_default_store_path_resolves_inside_repo():
    # Captured at import time, before the autouse fixture repoints it.
    repo_root = Path(__file__).resolve().parent.parent
    assert _UNPATCHED_DB_PATH == repo_root / "db" / "research.db"


def test_verify_records_passing_facts(isolated_fact_store):
    verify([_fresh(name="MSFT_chg_pct", value=1.1, entity="MSFT")], record=True)
    assert isolated_fact_store.history("MSFT_chg_pct", "MSFT") == [1.1]


def test_verify_does_not_record_facts_that_hard_stopped(isolated_fact_store):
    stale = _fresh(name="STALE_pct", value=1.1, entity="X", as_of="2020-01-01T00:00:00Z")
    verify([stale], raise_on_error=False, record=True)
    assert isolated_fact_store.history("STALE_pct", "X") == []


def test_jump_against_history_warns(isolated_fact_store):
    # Establish a baseline, then verify a value an order of magnitude above it.
    baseline = [_fresh(name="JUMP_pct", value=2.0, entity="X") for _ in range(5)]
    isolated_fact_store.record_many(baseline)

    report = verify([_fresh(name="JUMP_pct", value=80.0, entity="X")],
                    record=False)
    assert any("jump_ratio" in w for w in report["warnings"])


def test_a_timestamp_a_few_seconds_ahead_is_tolerated():
    """Providers stamp from their own clocks. A quote fetched this second can
    arrive a few seconds in the future, and hard-stopping on that made the
    price adapter unusable at random."""
    skewed = _fresh(as_of=(now_utc() + timedelta(seconds=90)).isoformat())
    assert verify([skewed], record=False)["ok"] is True


def test_a_timestamp_hours_ahead_is_still_refused():
    """The guard exists for timezone mistakes, which are hours or days out."""
    wrong_zone = _fresh(as_of=(now_utc() + timedelta(hours=8)).isoformat())
    with pytest.raises(FactCheckError):
        verify([wrong_zone], record=False)


def test_a_point_value_does_not_trip_the_frequency_check():
    """A share count has no period, and every owner-earnings group holds one
    beside annual flows. Comparing them fired this warning on every US fetch,
    and a warning that always fires is one nobody reads by the time it matters."""
    income = _fresh(name="NI", value=1.2e11, unit="usd", freq="annual",
                    entity="NVDA", group="owner_earnings")
    shares = _fresh(name="Shares", value=2.4e10, unit="shares", freq="point",
                    entity="NVDA", group="owner_earnings")
    report = verify([income, shares], record=False)
    assert not [w for w in report["warnings"] if w["check"] == "freq_align"]


def test_a_real_frequency_mismatch_still_warns():
    """The check exists for a quarterly numerator over a TTM denominator."""
    a = _fresh(name="NI", value=100, unit="usd", freq="quarterly",
               entity="X", group="oe")
    b = _fresh(name="DA", value=10, unit="usd", freq="quarterly",
               entity="X", group="oe")
    c = _fresh(name="Capex", value=5, unit="usd", freq="ttm",
               entity="X", group="oe")
    report = verify([a, b, c], record=False)
    assert any(w["check"] == "freq_align" and w["fact"] == "Capex"
               for w in report["warnings"])
