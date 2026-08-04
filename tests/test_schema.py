import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from skills._lib.data.schema import (
    Candidate,
    Portfolio,
    SchemaError,
    Sellcheck,
    Thesis,
    Valuation,
    Verdict,
)


# ── Candidate ─────────────────────────────────────────────────────

def test_candidate_valid_construction():
    c = Candidate(
        ticker="NVDA",
        entry_path="screen",
        source_note="general search",
        market="US",
        raw_rationale="AI capex beneficiary, cheap on forward FCF",
        discovered_at="2026-08-04T12:00:00Z",
    )
    assert c.ticker == "NVDA"
    assert c.screened is False
    assert c.profile_used == ""


def test_candidate_rejects_bad_entry_path():
    with pytest.raises(SchemaError):
        Candidate(
            ticker="NVDA", entry_path="wishful_thinking", source_note="x",
            market="US", raw_rationale="x", discovered_at="2026-08-04T12:00:00Z",
        )


def test_candidate_rejects_missing_ticker():
    with pytest.raises(SchemaError):
        Candidate(
            ticker="", entry_path="screen", source_note="x",
            market="US", raw_rationale="x", discovered_at="2026-08-04T12:00:00Z",
        )


def test_candidate_rejects_unknown_market():
    with pytest.raises(SchemaError):
        Candidate(
            ticker="NVDA", entry_path="screen", source_note="x",
            market="Mars", raw_rationale="x", discovered_at="2026-08-04T12:00:00Z",
        )


def test_candidate_rejects_bad_timestamp():
    with pytest.raises(SchemaError):
        Candidate(
            ticker="NVDA", entry_path="screen", source_note="x",
            market="US", raw_rationale="x", discovered_at="last tuesday",
        )


def test_candidate_normalizes_naive_timestamp_to_utc():
    c = Candidate(
        ticker="NVDA", entry_path="thesis", source_note="AI power bottleneck thesis",
        market="US", raw_rationale="x", discovered_at="2026-08-04T12:00:00",
    )
    assert c.discovered_at == "2026-08-04T12:00:00+00:00"


def test_candidate_normalizes_z_suffix_to_utc_offset():
    c = Candidate(
        ticker="NVDA", entry_path="thesis", source_note="x",
        market="US", raw_rationale="x", discovered_at="2026-08-04T12:00:00Z",
    )
    assert c.discovered_at == "2026-08-04T12:00:00+00:00"


def test_candidate_converts_offset_timestamp_to_utc():
    c = Candidate(
        ticker="NVDA", entry_path="screen", source_note="x",
        market="US", raw_rationale="x", discovered_at="2026-08-04T12:00:00+08:00",
    )
    assert c.discovered_at == "2026-08-04T04:00:00+00:00"


def test_candidate_round_trip_dict():
    c = Candidate(
        ticker="NVDA", entry_path="screen", source_note="x",
        market="US", raw_rationale="x", discovered_at="2026-08-04T12:00:00Z",
        screened=True, profile_used="deep-value",
    )
    c2 = Candidate.from_dict(c.to_dict())
    assert c2 == c


def test_candidate_from_dict_ignores_unknown_keys():
    c = Candidate.from_dict({
        "ticker": "NVDA", "entry_path": "screen", "source_note": "x",
        "market": "US", "raw_rationale": "x",
        "discovered_at": "2026-08-04T12:00:00Z",
        "id": 7, "unexpected": "ignored",
    })
    assert c.ticker == "NVDA"


# ── Thesis ────────────────────────────────────────────────────────

def test_thesis_valid_construction():
    t = Thesis(
        candidate_id=1,
        business_overview="Designs GPUs for accelerated computing.",
        management="Founder-led since 1993.",
        competitors="AMD, Intel, in-house hyperscaler silicon",
        tam="$400B accelerated computing by 2030",
        risks=["customer concentration", "China export controls"],
        variant_perception="Market underrates networking attach rate.",
        falsifiers=["hyperscaler capex guides down two quarters running"],
        authored_at="2026-08-04T12:00:00Z",
    )
    assert t.candidate_id == 1
    assert len(t.risks) == 2


def test_thesis_requires_at_least_one_risk():
    with pytest.raises(SchemaError):
        Thesis(
            candidate_id=1, business_overview="x", management="x",
            competitors="x", tam="x", risks=[],
        )


def test_thesis_requires_candidate_id():
    with pytest.raises(SchemaError):
        Thesis(
            candidate_id=None, business_overview="x", management="x",
            competitors="x", tam="x", risks=["a risk"],
        )


def test_thesis_allows_empty_authored_at():
    t = Thesis(
        candidate_id=1, business_overview="x", management="x",
        competitors="x", tam="x", risks=["a risk"],
    )
    assert t.authored_at == ""


def test_thesis_round_trip_dict():
    t = Thesis(
        candidate_id=1, business_overview="x", management="x",
        competitors="x", tam="x", risks=["a risk"],
        falsifiers=["f"], data_sources=["sec-xbrl"],
        authored_at="2026-08-04T12:00:00Z",
    )
    assert Thesis.from_dict(t.to_dict()) == t


def test_thesis_lists_are_not_shared_between_instances():
    a = Thesis(candidate_id=1, business_overview="x", management="x",
               competitors="x", tam="x", risks=["r"])
    b = Thesis(candidate_id=2, business_overview="x", management="x",
               competitors="x", tam="x", risks=["r"])
    a.falsifiers.append("only mine")
    assert b.falsifiers == []


# ── Valuation ─────────────────────────────────────────────────────

def _scenarios():
    return [
        {"name": "bull", "price_target": 250.0, "probability": 0.25, "assumptions": "g=25%"},
        {"name": "base", "price_target": 180.0, "probability": 0.50, "assumptions": "g=15%"},
        {"name": "bear", "price_target": 90.0, "probability": 0.25, "assumptions": "g=5%"},
    ]


def test_valuation_valid_construction():
    v = Valuation(
        thesis_id=1,
        scenarios=_scenarios(),
        discount_rate_source="US 10Y + 5% equity risk premium",
        valued_at="2026-08-04T12:00:00Z",
    )
    assert len(v.scenarios) == 3


def test_valuation_rejects_probabilities_not_summing_to_one():
    bad = _scenarios()
    bad[0]["probability"] = 0.9
    with pytest.raises(SchemaError):
        Valuation(thesis_id=1, scenarios=bad, discount_rate_source="x")


def test_valuation_rejects_empty_scenarios():
    with pytest.raises(SchemaError):
        Valuation(thesis_id=1, scenarios=[], discount_rate_source="x")


def test_valuation_accepts_probabilities_within_rounding_tolerance():
    scenarios = [
        {"name": "bull", "price_target": 250.0, "probability": 0.333, "assumptions": ""},
        {"name": "base", "price_target": 180.0, "probability": 0.333, "assumptions": ""},
        {"name": "bear", "price_target": 90.0, "probability": 0.334, "assumptions": ""},
    ]
    v = Valuation(thesis_id=1, scenarios=scenarios, discount_rate_source="x")
    assert len(v.scenarios) == 3


def test_valuation_round_trip_dict():
    v = Valuation(
        thesis_id=1, scenarios=_scenarios(), discount_rate_source="x",
        html_artifact_path="out/nvda.html", valued_at="2026-08-04T12:00:00Z",
    )
    assert Valuation.from_dict(v.to_dict()) == v


# ── Verdict ───────────────────────────────────────────────────────

def test_verdict_valid_construction():
    v = Verdict(
        valuation_id=1, mode="checklist",
        votes=[{"voice": "risk", "call": "PASS"}],
        dissent_map="No unresolved dissent.",
        authored_at="2026-08-04T12:00:00Z",
    )
    assert v.mode == "checklist"


def test_verdict_rejects_unknown_mode():
    with pytest.raises(SchemaError):
        Verdict(valuation_id=1, mode="vibes")


def test_verdict_round_trip_dict():
    v = Verdict(valuation_id=1, mode="persona_debate",
                votes=[{"voice": "bear", "call": "REJECT"}],
                authored_at="2026-08-04T12:00:00Z")
    assert Verdict.from_dict(v.to_dict()) == v


# ── Portfolio ─────────────────────────────────────────────────────

def test_portfolio_valid_construction():
    p = Portfolio(
        valuation_id=1, sizing_method="half_kelly",
        recommended_position_pct=4.2,
        kelly_inputs={"edge": 0.18, "odds": 1.9, "probability": 0.55},
        sized_at="2026-08-04T12:00:00Z",
    )
    assert p.recommended_position_pct == 4.2


def test_portfolio_rejects_unknown_sizing_method():
    with pytest.raises(SchemaError):
        Portfolio(valuation_id=1, sizing_method="gut_feel",
                  recommended_position_pct=1.0)


def test_portfolio_rejects_negative_position():
    with pytest.raises(SchemaError):
        Portfolio(valuation_id=1, sizing_method="half_kelly",
                  recommended_position_pct=-1.0)


def test_portfolio_allows_zero_position():
    p = Portfolio(valuation_id=1, sizing_method="half_kelly",
                  recommended_position_pct=0.0)
    assert p.recommended_position_pct == 0.0


def test_portfolio_round_trip_dict():
    p = Portfolio(valuation_id=1, sizing_method="fixed_pct",
                  recommended_position_pct=2.5, sized_at="2026-08-04T12:00:00Z")
    assert Portfolio.from_dict(p.to_dict()) == p


# ── Sellcheck ─────────────────────────────────────────────────────

def test_sellcheck_valid_construction():
    s = Sellcheck(
        thesis_id=1, trigger="user_initiated",
        diff_summary="facts_changed: China export licence revoked",
        rechecked_at="2026-08-04T12:00:00Z",
    )
    assert s.thesis_id == 1


def test_sellcheck_requires_diff_summary():
    with pytest.raises(SchemaError):
        Sellcheck(thesis_id=1, trigger="user_initiated", diff_summary="")


def test_sellcheck_round_trip_dict():
    s = Sellcheck(thesis_id=1, trigger="user_initiated",
                  diff_summary="still_holds", rechecked_at="2026-08-04T12:00:00Z")
    assert Sellcheck.from_dict(s.to_dict()) == s
