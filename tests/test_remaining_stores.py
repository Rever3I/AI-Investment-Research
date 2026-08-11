"""The verdict, portfolio and sellcheck stores.

Written together because they share a shape, and the interesting cases are the
ones where they differ: what each refuses to persist without, and what
sellcheck keeps that the others overwrite.
"""

import sqlite3
from contextlib import closing

import pytest

from skills._lib.data.candidate_store import save_candidate
from skills._lib.data.db_init import init_db
from skills._lib.data.portfolio_store import (
    get_portfolio,
    get_portfolio_for_valuation,
    list_portfolios,
    save_portfolio,
)
from skills._lib.data.schema import (
    Candidate,
    Portfolio,
    Sellcheck,
    Thesis,
    Valuation,
    Verdict,
)
from skills._lib.data.sellcheck_store import (
    get_sellcheck,
    list_sellchecks,
    list_sellchecks_for_thesis,
    save_sellcheck,
)
from skills._lib.data.store_support import UnreadableRecord
from skills._lib.data.thesis_store import save_thesis
from skills._lib.data.valuation_store import save_valuation
from skills._lib.data.verdict_store import (
    get_verdict,
    get_verdict_for_valuation,
    list_verdicts,
    save_verdict,
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
               management="m", competitors="c", tam="t", risks=["concentration"]),
        db_path=db,
    )


@pytest.fixture
def valuation_id(db, thesis_id):
    return save_valuation(
        Valuation(
            thesis_id=thesis_id,
            scenarios=[
                {"name": "bull", "price_target": 200.0, "probability": 0.25},
                {"name": "base", "price_target": 120.0, "probability": 0.50},
                {"name": "bear", "price_target": 60.0, "probability": 0.25},
            ],
            discount_rate_source="US 10Y + 5% ERP",
        ),
        db_path=db,
    )


def _damage(db, sql, params=()):
    with closing(sqlite3.connect(str(db))) as conn:
        conn.execute(sql, params)
        conn.commit()


# ── verdicts ──────────────────────────────────────────────────────

def _verdict(valuation_id, **overrides):
    kwargs = dict(
        valuation_id=valuation_id,
        mode="persona_debate",
        votes=[{"voice": "bull", "call": "BUY", "why": "attach rate"},
               {"voice": "bear", "call": "PASS", "why": "capex digestion"}],
        dissent_map="Unresolved: whether networking revenue is durable.",
        authored_at="2026-08-04T12:00:00Z",
    )
    kwargs.update(overrides)
    return Verdict(**kwargs)


def test_a_verdict_round_trips_with_its_votes(db, valuation_id):
    original = _verdict(valuation_id)
    row_id = save_verdict(original, db_path=db)
    assert get_verdict(row_id, db_path=db) == original


def test_the_dissent_map_is_kept_verbatim(db, valuation_id):
    """Unresolved disagreement is this layer's output; flattening it discards
    the only part a reader cannot reconstruct."""
    text = "Bull and bear agree on the numbers and disagree on durability.\nNo resolution."
    row_id = save_verdict(_verdict(valuation_id, dissent_map=text), db_path=db)
    assert get_verdict(row_id, db_path=db).dissent_map == text


def test_a_verdict_needs_a_valuation(db, valuation_id):
    with pytest.raises(ValueError) as excinfo:
        save_verdict(_verdict(999999), db_path=db)
    assert "999999" in str(excinfo.value)


def test_a_checklist_verdict_is_as_valid_as_a_debate(db, valuation_id):
    row_id = save_verdict(_verdict(valuation_id, mode="checklist", votes=[]),
                          db_path=db)
    assert get_verdict(row_id, db_path=db).mode == "checklist"


def test_the_newest_verdict_wins(db, valuation_id):
    save_verdict(_verdict(valuation_id, authored_at="2026-05-01T00:00:00Z"), db_path=db)
    newer = save_verdict(
        _verdict(valuation_id, authored_at="2026-08-04T00:00:00Z"), db_path=db
    )
    assert get_verdict_for_valuation(valuation_id, db_path=db).id == newer


def test_a_damaged_verdict_is_skipped_by_the_list(db, valuation_id):
    good = save_verdict(_verdict(valuation_id), db_path=db)
    bad = save_verdict(_verdict(valuation_id), db_path=db)
    _damage(db, "UPDATE verdicts SET mode = 'nonsense' WHERE id = ?", (bad,))
    assert [v.id for v in list_verdicts(db_path=db)] == [good]


def test_asking_for_a_damaged_verdict_by_id_says_so(db, valuation_id):
    row_id = save_verdict(_verdict(valuation_id), db_path=db)
    _damage(db, "UPDATE verdicts SET mode = 'nonsense' WHERE id = ?", (row_id,))
    with pytest.raises(UnreadableRecord):
        get_verdict(row_id, db_path=db)


# ── portfolios ────────────────────────────────────────────────────

def _portfolio(valuation_id, **overrides):
    kwargs = dict(
        valuation_id=valuation_id,
        sizing_method="half_kelly",
        recommended_position_pct=4.25,
        kelly_inputs={
            "full_kelly": 0.085,
            "expected_return": 0.25,
            "market_price": 100.0,
            "outcomes": [
                {"name": "bull", "probability": 0.25, "return": 1.0},
                {"name": "base", "probability": 0.50, "return": 0.2},
                {"name": "bear", "probability": 0.25, "return": -0.4},
            ],
        },
        sized_at="2026-08-04T12:00:00Z",
    )
    kwargs.update(overrides)
    return Portfolio(**kwargs)


def test_a_portfolio_round_trips_with_the_inputs_behind_it(db, valuation_id):
    """A weight with no visible probabilities behind it is a number nobody can
    argue with later, including whoever produced it."""
    original = _portfolio(valuation_id)
    row_id = save_portfolio(original, db_path=db)
    restored = get_portfolio(row_id, db_path=db)
    assert restored == original
    assert restored.kelly_inputs["outcomes"][0]["probability"] == 0.25


def test_a_portfolio_needs_a_valuation(db, valuation_id):
    with pytest.raises(ValueError) as excinfo:
        save_portfolio(_portfolio(999999), db_path=db)
    assert "999999" in str(excinfo.value)


def test_a_zero_weight_is_a_real_answer_not_a_missing_one(db, valuation_id):
    row_id = save_portfolio(
        _portfolio(valuation_id, recommended_position_pct=0.0), db_path=db
    )
    assert get_portfolio(row_id, db_path=db).recommended_position_pct == 0.0


def test_resizing_appends_and_the_newest_wins(db, valuation_id):
    save_portfolio(_portfolio(valuation_id, sized_at="2026-05-01T00:00:00Z"), db_path=db)
    newer = save_portfolio(
        _portfolio(valuation_id, sized_at="2026-08-04T00:00:00Z"), db_path=db
    )
    assert get_portfolio_for_valuation(valuation_id, db_path=db).id == newer
    assert len(list_portfolios(db_path=db)) == 2


def test_a_damaged_portfolio_is_skipped_by_the_list(db, valuation_id):
    good = save_portfolio(_portfolio(valuation_id), db_path=db)
    bad = save_portfolio(_portfolio(valuation_id), db_path=db)
    _damage(db, "UPDATE portfolios SET sizing_method = 'gut_feel' WHERE id = ?", (bad,))
    assert [p.id for p in list_portfolios(db_path=db)] == [good]


# ── sellchecks ────────────────────────────────────────────────────

def _sellcheck(thesis_id, **overrides):
    kwargs = dict(
        thesis_id=thesis_id,
        trigger="user_initiated",
        diff_summary="facts_changed: export licence revoked, TAM assumption void",
        rechecked_at="2026-08-04T12:00:00Z",
    )
    kwargs.update(overrides)
    return Sellcheck(**kwargs)


def test_a_sellcheck_round_trips(db, thesis_id):
    original = _sellcheck(thesis_id)
    row_id = save_sellcheck(original, db_path=db)
    assert get_sellcheck(row_id, db_path=db) == original


def test_a_sellcheck_needs_the_thesis_it_compares_against(db, thesis_id):
    with pytest.raises(ValueError) as excinfo:
        save_sellcheck(_sellcheck(999999), db_path=db)
    assert "999999" in str(excinfo.value)


def test_every_recheck_is_kept_rather_than_replaced(db, thesis_id):
    """A thesis rechecked three times, each drifting further from the original
    argument, is a different situation from one that failed today."""
    for month, verdict in (("05", "still_holds"), ("06", "judgment_changed"),
                           ("08", "facts_changed")):
        save_sellcheck(
            _sellcheck(thesis_id, diff_summary=verdict,
                       rechecked_at=f"2026-{month}-01T00:00:00Z"),
            db_path=db,
        )
    history = list_sellchecks_for_thesis(thesis_id, db_path=db)
    assert [s.diff_summary for s in history] == [
        "facts_changed", "judgment_changed", "still_holds",
    ]


def test_a_thesis_with_no_rechecks_returns_an_empty_history(db, thesis_id):
    save_sellcheck(_sellcheck(thesis_id), db_path=db)
    other_candidate = save_candidate(
        Candidate(ticker="AVGO", entry_path="screen", source_note="x", market="US",
                  raw_rationale="why", discovered_at="2026-08-04T12:00:00Z"),
        db_path=db,
    )
    other_thesis = save_thesis(
        Thesis(candidate_id=other_candidate, business_overview="x", management="m",
               competitors="c", tam="t", risks=["r"]),
        db_path=db,
    )
    assert list_sellchecks_for_thesis(other_thesis, db_path=db) == []


def test_chinese_diff_summaries_survive(db, thesis_id):
    text = "事实变了：出口许可被撤销，原本的 TAM 假设不成立"
    row_id = save_sellcheck(_sellcheck(thesis_id, diff_summary=text), db_path=db)
    assert get_sellcheck(row_id, db_path=db).diff_summary == text


# ── all three refuse to create a database on read ─────────────────

@pytest.mark.parametrize("call", [
    lambda p: list_verdicts(db_path=p),
    lambda p: get_verdict(1, db_path=p),
    lambda p: get_verdict_for_valuation(1, db_path=p),
    lambda p: list_portfolios(db_path=p),
    lambda p: get_portfolio(1, db_path=p),
    lambda p: get_portfolio_for_valuation(1, db_path=p),
    lambda p: list_sellchecks(db_path=p),
    lambda p: get_sellcheck(1, db_path=p),
    lambda p: list_sellchecks_for_thesis(1, db_path=p),
])
def test_reads_do_not_create_a_database(tmp_path, call):
    missing = tmp_path / "typo.db"
    with pytest.raises(FileNotFoundError):
        call(missing)
    assert not missing.exists()


@pytest.mark.parametrize("lister", [list_verdicts, list_portfolios, list_sellchecks])
def test_an_initialised_but_empty_database_lists_nothing(db, lister):
    init_db(db)
    assert lister(db_path=db) == []
