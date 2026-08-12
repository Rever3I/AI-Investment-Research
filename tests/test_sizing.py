"""Position sizing.

The binary Kelly formula is checked against its closed form, and the general
solver is checked against the binary formula on binary inputs — that is the
cross-check that catches a wrong generalisation, which would otherwise produce a
plausible number for every three-scenario case in the pipeline.
"""

from decimal import Decimal

import pytest

from airesearch.valuation.sizing import (
    SizingError,
    kelly_fraction,
    scenario_returns,
    size_position,
)


def _binary(p, b):
    """Textbook Kelly: win b times the stake with probability p, else lose it."""
    q = Decimal(1) - Decimal(str(p))
    return (Decimal(str(b)) * Decimal(str(p)) - q) / Decimal(str(b))


def _scenarios(bull=200.0, base=120.0, bear=60.0, probs=(0.25, 0.5, 0.25)):
    return [
        {"name": "bull", "price_target": bull, "probability": probs[0]},
        {"name": "base", "price_target": base, "probability": probs[1]},
        {"name": "bear", "price_target": bear, "probability": probs[2]},
    ]


# ── returns ───────────────────────────────────────────────────────

def test_price_targets_become_returns_against_the_price():
    outcomes = scenario_returns(_scenarios(), market_price=100)
    assert outcomes[0]["return"] == Decimal("1.0")     # 200 -> +100%
    assert outcomes[1]["return"] == Decimal("0.2")     # 120 -> +20%
    assert outcomes[2]["return"] == Decimal("-0.4")    # 60  -> -40%


def test_probabilities_that_do_not_sum_to_one_are_refused():
    """Sizing off an incomplete distribution silently overstates the edge."""
    with pytest.raises(SizingError) as excinfo:
        scenario_returns(_scenarios(probs=(0.25, 0.25, 0.25)), market_price=100)
    assert "sum" in str(excinfo.value)


def test_rounding_in_the_probabilities_is_tolerated():
    scenario_returns(_scenarios(probs=(0.333, 0.333, 0.334)), market_price=100)


def test_a_missing_price_target_is_named():
    with pytest.raises(SizingError) as excinfo:
        scenario_returns([{"name": "base", "probability": 1.0}], market_price=100)
    assert "base" in str(excinfo.value)


def test_a_missing_probability_is_named():
    with pytest.raises(SizingError) as excinfo:
        scenario_returns([{"name": "base", "price_target": 100.0}], market_price=100)
    assert "probability" in str(excinfo.value)


def test_a_non_positive_price_is_refused():
    with pytest.raises(SizingError):
        scenario_returns(_scenarios(), market_price=0)


# ── the general solver against the textbook formula ───────────────

@pytest.mark.parametrize("p,b", [
    (0.6, 1.0),      # even money, 60% win rate -> f* = 0.2
    (0.5, 2.0),      # 2:1 odds, coin flip      -> f* = 0.25
    (0.55, 1.0),
    (0.75, 0.5),
    (0.9, 0.2),
])
def test_the_general_solver_reproduces_binary_kelly(p, b):
    """A win of b and a total loss is the case the textbook formula covers. If
    the general solver disagrees there, it is wrong everywhere."""
    outcomes = [
        {"name": "win", "probability": Decimal(str(p)), "return": Decimal(str(b))},
        {"name": "lose", "probability": Decimal(1) - Decimal(str(p)),
         "return": Decimal("-0.999999")},   # -100% exactly is undefined for Kelly
    ]
    assert kelly_fraction(outcomes) == pytest.approx(
        _binary(p, b), abs=Decimal("0.0005")
    )


def test_a_known_three_outcome_case():
    """+100% / +20% / -70% at 25/50/25, chosen so the optimum is interior.
    Confirmed by checking the solver's answer is the peak of expected log
    wealth rather than trusting the solver's own arithmetic."""
    outcomes = scenario_returns(_scenarios(bear=30.0), market_price=100)
    f = kelly_fraction(outcomes)
    assert Decimal(0) < f < Decimal(1), f"expected an interior optimum, got {f}"

    def growth(fraction):
        total = Decimal(0)
        for o in outcomes:
            total += o["probability"] * (Decimal(1) + fraction * o["return"]).ln()
        return total

    assert growth(f) >= growth(f - Decimal("0.01"))
    assert growth(f) >= growth(f + Decimal("0.01"))


# ── the answers Kelly gives that people find surprising ───────────

def test_no_edge_means_no_position():
    """Kelly declining the bet is an answer, not a missing number."""
    flat = [
        {"name": "up", "price_target": 110.0, "probability": 0.5},
        {"name": "down", "price_target": 90.0, "probability": 0.5},
    ]
    outcomes = scenario_returns(flat, market_price=100)
    assert kelly_fraction(outcomes) == 0


def test_a_negative_expected_return_means_no_position():
    losing = [
        {"name": "up", "price_target": 110.0, "probability": 0.3},
        {"name": "down", "price_target": 90.0, "probability": 0.7},
    ]
    assert kelly_fraction(scenario_returns(losing, market_price=100)) == 0


def test_an_all_upside_set_sizes_at_the_full_limit():
    """With no losing case the optimum is unbounded; without leverage that is
    all of it."""
    only_up = [
        {"name": "good", "price_target": 150.0, "probability": 0.5},
        {"name": "great", "price_target": 200.0, "probability": 0.5},
    ]
    assert kelly_fraction(scenario_returns(only_up, market_price=100)) == Decimal(1)


def test_a_total_loss_scenario_is_refused_rather_than_sized():
    wipeout = [
        {"name": "bull", "price_target": 300.0, "probability": 0.9},
        {"name": "zero", "price_target": 0.0, "probability": 0.1},
    ]
    with pytest.raises(SizingError) as excinfo:
        kelly_fraction(scenario_returns(wipeout, market_price=100))
    assert "zero" in str(excinfo.value)


def test_a_bigger_edge_sizes_bigger():
    small = size_position(_scenarios(bull=130.0), market_price=100).fraction
    large = size_position(_scenarios(bull=400.0), market_price=100).fraction
    assert large > small


# ── methods ───────────────────────────────────────────────────────

def test_half_kelly_is_half_of_full():
    result = size_position(_scenarios(), market_price=100, method="half_kelly")
    assert result.fraction == result.full_kelly / 2


def test_full_kelly_is_available_and_says_what_it_costs():
    result = size_position(_scenarios(), market_price=100, method="full_kelly")
    assert result.fraction == result.full_kelly
    assert "exactly right" in result.note


def test_half_kelly_is_the_default():
    assert size_position(_scenarios(), market_price=100).method == "half_kelly"


def test_fixed_pct_ignores_the_edge_but_still_reports_kelly():
    result = size_position(_scenarios(), market_price=100, method="fixed_pct",
                           weight="0.05")
    assert result.fraction == Decimal("0.05")
    assert result.full_kelly > 0
    assert "comparison" in result.note


@pytest.mark.parametrize("method", ["fixed_pct", "custom"])
def test_a_caller_supplied_weight_is_used_as_given(method):
    result = size_position(_scenarios(), market_price=100, method=method,
                           weight="0.07")
    assert result.fraction == Decimal("0.07")
    assert result.method == method


@pytest.mark.parametrize("method", ["fixed_pct", "custom"])
def test_a_weightless_caller_method_says_what_is_missing(method):
    """Both were documented in the README; one crashed with an unhelpful
    message and the other was not implemented at all."""
    with pytest.raises(SizingError) as excinfo:
        size_position(_scenarios(), market_price=100, method=method)
    assert "weight" in str(excinfo.value)


@pytest.mark.parametrize("method", ["half_kelly", "full_kelly", "fixed_pct", "custom"])
def test_every_documented_method_is_usable(method):
    """schema.SIZING_METHODS and both READMEs advertise these four, and a test
    enforces the READMEs. Any that raises is a documented feature that is not
    there."""
    from airesearch.data.schema import SIZING_METHODS

    assert method in SIZING_METHODS
    kwargs = {"weight": "0.05"} if method in ("fixed_pct", "custom") else {}
    result = size_position(_scenarios(), market_price=100, method=method, **kwargs)
    assert result.fraction >= 0


def test_a_weight_above_all_the_capital_is_refused():
    """5 meaning 5% is the obvious slip, and it would be a hundredfold error."""
    with pytest.raises(SizingError) as excinfo:
        size_position(_scenarios(), market_price=100, method="fixed_pct", weight=5)
    assert "fractions" in str(excinfo.value)


def test_an_unknown_method_is_refused_by_name():
    with pytest.raises(SizingError) as excinfo:
        size_position(_scenarios(), market_price=100, method="gut_feel")
    assert "gut_feel" in str(excinfo.value)


def test_a_zero_edge_position_explains_itself():
    flat = [
        {"name": "up", "price_target": 110.0, "probability": 0.5},
        {"name": "down", "price_target": 90.0, "probability": 0.5},
    ]
    result = size_position(flat, market_price=100)
    assert result.fraction == 0
    assert "declining the bet" in result.note


# ── the concentration cap ─────────────────────────────────────────

def test_a_cap_limits_the_position_and_says_so():
    uncapped = size_position(_scenarios(bull=1000.0), market_price=100)
    capped = size_position(_scenarios(bull=1000.0), market_price=100, cap="0.05")
    assert uncapped.fraction > Decimal("0.05")
    assert capped.fraction == Decimal("0.05")
    assert "Capped" in capped.note


def test_a_cap_above_the_recommendation_changes_nothing():
    plain = size_position(_scenarios(), market_price=100)
    capped = size_position(_scenarios(), market_price=100, cap="0.99")
    assert capped.fraction == plain.fraction


def test_a_negative_cap_is_refused():
    with pytest.raises(SizingError):
        size_position(_scenarios(), market_price=100, cap="-0.1")


# ── what the result carries ───────────────────────────────────────

def test_the_result_reports_the_inputs_it_used():
    """A Kelly fraction is only as good as its probabilities, so they travel
    with the answer rather than being recoverable only from memory."""
    result = size_position(_scenarios(), market_price=100)
    assert [o["name"] for o in result.outcomes] == ["bull", "base", "bear"]
    # 0.25(+100%) + 0.50(+20%) + 0.25(-40%)
    assert result.expected_return == pytest.approx(Decimal("0.25"), abs=Decimal("1e-9"))


def test_percent_is_the_fraction_scaled():
    result = size_position(_scenarios(), market_price=100)
    assert result.percent == result.fraction * 100


def test_an_optimum_beyond_full_capital_is_capped_rather_than_levered():
    """+100% / +20% / -40% at 25/50/25 has a Kelly optimum above 100% of
    capital. Without leverage the answer is all of it, not a number above one."""
    outcomes = scenario_returns(_scenarios(), market_price=100)
    assert kelly_fraction(outcomes) == Decimal(1)
    assert size_position(_scenarios(), market_price=100).fraction == Decimal("0.5")


# ── the reported number must mean what the reader thinks ──────────

def test_a_clipped_optimum_is_flagged_and_explained():
    """+100%/+20%/-40% at 25/50/25 has an optimum above all of the capital, so
    half Kelly reports 50% of capital in one name. Nothing in the result used to
    distinguish 'the optimum was 1.0' from 'the optimum was 3.7 and we censored
    it', which is the difference between a Kelly answer and a ceiling."""
    result = size_position(_scenarios(), market_price=100)
    assert result.clipped is True
    assert result.full_kelly == Decimal(1)
    assert "above 100%" in result.note
    assert "ceiling" in result.note


def test_an_interior_optimum_is_not_flagged_as_clipped():
    result = size_position(_scenarios(bear=30.0), market_price=100)
    assert result.clipped is False
    assert "ceiling" not in result.note


def test_a_capped_result_says_it_was_capped_in_data_not_only_prose():
    result = size_position(_scenarios(), market_price=100, cap="0.05")
    assert result.capped is True
    assert result.fraction == Decimal("0.05")


def test_an_uncapped_result_is_not_marked_capped():
    assert size_position(_scenarios(), market_price=100).capped is False


def test_a_cap_above_all_the_capital_is_refused_rather_than_ignored():
    """`5` meaning 5% used to pass straight through and never bind, silently
    leaving the position uncapped."""
    with pytest.raises(SizingError) as excinfo:
        size_position(_scenarios(), market_price=100, cap=5)
    assert "fractions" in str(excinfo.value)


def test_an_impossible_return_is_refused_as_a_unit_error():
    """price_target can be a total equity value when no share count was given.
    Sizing used to accept a +20,000,000,000% return and size at the ceiling."""
    absurd = [
        {"name": "bull", "price_target": 6e10, "probability": 0.5},
        {"name": "bear", "price_target": 90.0, "probability": 0.5},
    ]
    with pytest.raises(SizingError) as excinfo:
        size_position(absurd, market_price=100)
    assert "unit error" in str(excinfo.value)


def test_a_negative_probability_is_caught_even_when_the_set_sums_to_one():
    """+0.5 / -0.5 / +1.0 sums to 1 and is still nonsense."""
    sneaky = [
        {"name": "a", "price_target": 200.0, "probability": 0.5},
        {"name": "b", "price_target": 150.0, "probability": -0.5},
        {"name": "c", "price_target": 120.0, "probability": 1.0},
    ]
    with pytest.raises(SizingError) as excinfo:
        scenario_returns(sneaky, market_price=100)
    assert "negative probability" in str(excinfo.value)


def test_the_valuation_record_refuses_what_sizing_refuses():
    """A record that persists and then hard-fails two layers later is worse than
    one that never persists."""
    from airesearch.data.schema import SchemaError, Valuation

    with pytest.raises(SchemaError) as excinfo:
        Valuation(thesis_id=1, discount_rate_source="x", scenarios=[
            {"name": "a", "price_target": 200.0, "probability": 0.5},
            {"name": "b", "price_target": 150.0, "probability": -0.5},
            {"name": "c", "price_target": 120.0, "probability": 1.0},
        ])
    assert "negative probability" in str(excinfo.value)
