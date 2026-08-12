"""The valuation arithmetic.

Checked against closed-form results computed independently rather than against
whatever the implementation happened to return, because a DCF that is
self-consistently wrong still produces a confident-looking price target.
"""

from decimal import Decimal

import pytest

from airesearch.valuation import (
    DCFError,
    PriceOutsideBracket,
    discounted_cash_flow,
    expected_value,
    implied_growth_rate,
    project_owner_earnings,
    scenario_values,
)


def _dcf(**overrides):
    kwargs = dict(
        owner_earnings=100,
        growth_rate="0.10",
        discount_rate="0.10",
        terminal_growth="0.03",
        years=10,
    )
    kwargs.update(overrides)
    return discounted_cash_flow(**kwargs)


# ── projection ────────────────────────────────────────────────────

def test_flat_growth_compounds(nofade=None):
    series = project_owner_earnings(100, "0.10", years=3)
    assert series == [Decimal("110.00"), Decimal("121.0000"), Decimal("133.100000")]


def test_growth_fades_linearly_to_the_terminal_rate():
    series = project_owner_earnings(100, "0.20", years=3, terminal_growth="0.00")
    # year 1 at 20%, year 2 at 10% (midpoint), year 3 at 0%
    assert series[0] == Decimal("120.00")
    assert series[1] == Decimal("132.0000")
    assert series[2] == Decimal("132.000000")


def test_a_single_year_uses_the_stated_rate(quiet=None):
    assert project_owner_earnings(100, "0.15", years=1, terminal_growth="0.00") == [
        Decimal("115.00")
    ]


def test_negative_growth_shrinks_the_series():
    series = project_owner_earnings(100, "-0.10", years=2, terminal_growth="-0.10")
    assert series[0] < Decimal(100)
    assert series[1] < series[0]


def test_zero_years_is_rejected():
    with pytest.raises(DCFError):
        project_owner_earnings(100, "0.1", years=0)


def test_an_absurd_projection_length_is_rejected():
    with pytest.raises(DCFError):
        project_owner_earnings(100, "0.1", years=200)


# ── present value, against hand-computed answers ──────────────────

def test_a_one_year_projection_matches_the_closed_form():
    # OE1 = 100 * 1.05 = 105
    # PV(OE1) = 105 / 1.10 = 95.4545...
    # TV = 105 * 1.03 / (0.10 - 0.03) = 1545.0
    # PV(TV) = 1545 / 1.10 = 1404.5454...
    result = _dcf(growth_rate="0.05", terminal_growth="0.03", years=1)
    assert result.present_value == pytest.approx(Decimal("1500.0"), rel=Decimal("1e-6"))


def test_zero_growth_with_zero_terminal_growth_is_a_perpetuity():
    # Constant owner earnings of 100 discounted at 10% in perpetuity is 1000,
    # whatever the projection length. This is the sanity check that catches an
    # off-by-one in the discounting exponent.
    for years in (1, 5, 10, 30):
        result = _dcf(growth_rate="0.00", terminal_growth="0.00", years=years)
        assert result.present_value == pytest.approx(
            Decimal("1000.0"), rel=Decimal("1e-9")
        ), f"years={years}"


def test_a_higher_discount_rate_lowers_the_value():
    cheap = _dcf(discount_rate="0.08").present_value
    dear = _dcf(discount_rate="0.12").present_value
    assert dear < cheap


def test_faster_growth_raises_the_value():
    slow = _dcf(growth_rate="0.05").present_value
    fast = _dcf(growth_rate="0.15").present_value
    assert fast > slow


def test_per_share_divides_by_the_share_count():
    result = _dcf(shares_outstanding=10)
    assert result.per_share == result.present_value / Decimal(10)


def test_per_share_is_absent_when_no_share_count_is_given():
    assert _dcf().per_share is None


def test_terminal_share_reports_how_much_rests_on_the_assumption():
    result = _dcf(years=10)
    assert Decimal("0") < result.terminal_share < Decimal("1")
    # A ten-year projection at these rates is mostly terminal value, which is
    # the point of surfacing it.
    assert result.terminal_share > Decimal("0.5")


def test_inputs_are_recorded_on_the_result():
    result = _dcf(discount_rate="0.11")
    assert result.inputs["discount_rate"] == Decimal("0.11")
    assert result.inputs["years"] == 10


# ── the guards that stop nonsense from looking like a number ──────

def test_terminal_growth_at_the_discount_rate_is_rejected():
    with pytest.raises(DCFError) as excinfo:
        _dcf(discount_rate="0.08", terminal_growth="0.08")
    assert "terminal_growth" in str(excinfo.value)


def test_terminal_growth_above_the_discount_rate_is_rejected():
    with pytest.raises(DCFError):
        _dcf(discount_rate="0.08", terminal_growth="0.12")


def test_a_spread_too_narrow_to_be_meaningful_is_rejected():
    with pytest.raises(DCFError):
        _dcf(discount_rate="0.0801", terminal_growth="0.08")


def test_a_zero_discount_rate_is_rejected():
    with pytest.raises(DCFError):
        _dcf(discount_rate="0")


def test_a_negative_discount_rate_is_rejected():
    with pytest.raises(DCFError):
        _dcf(discount_rate="-0.05")


def test_zero_shares_is_rejected():
    with pytest.raises(DCFError):
        _dcf(shares_outstanding=0)


def test_a_non_numeric_input_is_rejected_by_name():
    with pytest.raises(DCFError) as excinfo:
        _dcf(owner_earnings="not a number")
    assert "owner_earnings" in str(excinfo.value)


def test_there_is_no_default_discount_rate():
    """A built-in rate is how a US-shaped assumption gets applied silently to a
    listing somewhere else."""
    with pytest.raises(TypeError):
        discounted_cash_flow(owner_earnings=100, growth_rate="0.1",
                             terminal_growth="0.03")


# ── float error does not accumulate ───────────────────────────────

def test_decimal_arithmetic_is_exact_where_float_would_drift():
    result = project_owner_earnings("0.1", "0.1", years=3, terminal_growth="0.1")
    # 0.1 * 1.1^3 = 0.1331 exactly in decimal; in binary float it is not.
    assert result[-1] == Decimal("0.1331")


# ── reverse DCF ───────────────────────────────────────────────────

def test_implied_growth_recovers_the_rate_that_produced_a_value():
    known = _dcf(growth_rate="0.12", shares_outstanding=10)
    recovered = implied_growth_rate(
        market_value=known.per_share,
        owner_earnings=100,
        discount_rate="0.10",
        terminal_growth="0.03",
        years=10,
        shares_outstanding=10,
    )
    assert recovered == pytest.approx(Decimal("0.12"), abs=Decimal("0.001"))


def test_a_higher_price_implies_faster_growth():
    common = dict(owner_earnings=100, discount_rate="0.10",
                  terminal_growth="0.03", years=10)
    cheap = implied_growth_rate(market_value=1500, **common)
    dear = implied_growth_rate(market_value=3000, **common)
    assert dear > cheap


def test_a_price_below_the_searched_range_says_which_side_it_fell_off():
    """A price below the value of current earnings is a finding, not a number to
    invent."""
    with pytest.raises(PriceOutsideBracket) as excinfo:
        implied_growth_rate(
            market_value=1, owner_earnings=100, discount_rate="0.10",
            terminal_growth="0.03", years=10,
        )
    assert excinfo.value.direction == "below"


def test_a_price_above_the_searched_range_is_not_reported_as_below():
    """Both ends used to return a bare None, and the docs named only the cheap
    one — so a company priced above 400x owner earnings was reported as priced
    below its earnings in perpetuity. The exact opposite, stated confidently."""
    with pytest.raises(PriceOutsideBracket) as excinfo:
        implied_growth_rate(
            market_value=10_000_000, owner_earnings=100, discount_rate="0.10",
            terminal_growth="0.03", years=10,
        )
    assert excinfo.value.direction == "above"
    assert "above" in str(excinfo.value)


def test_the_two_out_of_range_directions_are_distinguishable():
    common = dict(owner_earnings=100, discount_rate="0.10",
                  terminal_growth="0.03", years=10)
    directions = set()
    for price in (1, 10_000_000):
        try:
            implied_growth_rate(market_value=price, **common)
        except PriceOutsideBracket as exc:
            directions.add(exc.direction)
    assert directions == {"below", "above"}


def test_a_non_positive_market_value_is_rejected():
    with pytest.raises(DCFError):
        implied_growth_rate(market_value=0, owner_earnings=100,
                            discount_rate="0.1", terminal_growth="0.03")


# ── scenarios, which feed position sizing ─────────────────────────

def _scenarios():
    return [
        {"name": "bull", "probability": 0.25, "growth_rate": "0.20", "assumptions": "attach holds"},
        {"name": "base", "probability": 0.50, "growth_rate": "0.10"},
        {"name": "bear", "probability": 0.25, "growth_rate": "0.00"},
    ]


def _base_inputs():
    return dict(owner_earnings=100, growth_rate="0.10", discount_rate="0.10",
                terminal_growth="0.03", years=10, shares_outstanding=10)


def test_each_scenario_gets_its_own_value():
    results = scenario_values(_scenarios(), _base_inputs())
    assert [r["name"] for r in results] == ["bull", "base", "bear"]
    assert results[0]["price_target"] > results[1]["price_target"]
    assert results[1]["price_target"] > results[2]["price_target"]


def test_probabilities_travel_with_the_values():
    """research-portfolio reads these as Kelly inputs; restating them later from
    memory is how the sizing and the valuation drift apart."""
    results = scenario_values(_scenarios(), _base_inputs())
    assert [r["probability"] for r in results] == [0.25, 0.50, 0.25]


def test_scenario_output_matches_the_valuation_record_shape():
    from airesearch.data.schema import Valuation

    results = scenario_values(_scenarios(), _base_inputs())
    record = Valuation(thesis_id=1, scenarios=results,
                       discount_rate_source="US 10Y + 5% ERP")
    assert len(record.scenarios) == 3


def test_assumptions_carry_through_and_default_to_empty():
    results = scenario_values(_scenarios(), _base_inputs())
    assert results[0]["assumptions"] == "attach holds"
    assert results[1]["assumptions"] == ""


def test_a_scenario_overrides_only_what_it_names():
    results = scenario_values(
        [{"name": "base", "probability": 1.0, "discount_rate": "0.20"}],
        _base_inputs(),
    )
    plain = scenario_values(
        [{"name": "base", "probability": 1.0}], _base_inputs()
    )
    assert results[0]["price_target"] < plain[0]["price_target"]


def test_expected_value_is_probability_weighted():
    scenarios = [
        {"price_target": 200, "probability": 0.5},
        {"price_target": 100, "probability": 0.5},
    ]
    assert expected_value(scenarios) == Decimal("150.0")


def test_expected_value_of_the_computed_scenarios_sits_between_bear_and_bull():
    results = scenario_values(_scenarios(), _base_inputs())
    ev = expected_value(results)
    assert Decimal(str(results[2]["price_target"])) < ev
    assert ev < Decimal(str(results[0]["price_target"]))


def test_a_failing_scenario_is_named(quiet=None):
    """A failure in one of five scenarios must not send the caller reading all
    five sets of assumptions."""
    with pytest.raises(DCFError) as excinfo:
        scenario_values(
            [{"name": "bear", "probability": 1.0, "terminal_growth": "0.99"}],
            _base_inputs(),
        )
    assert "bear" in str(excinfo.value)


def test_a_scenario_missing_a_required_input_is_named():
    with pytest.raises(DCFError) as excinfo:
        scenario_values(
            [{"name": "base", "probability": 1.0}],
            {"owner_earnings": 100, "discount_rate": "0.10",
             "terminal_growth": "0.03"},
        )
    assert "base" in str(excinfo.value)
    assert "growth_rate" in str(excinfo.value)


# ── inputs that make the arithmetic meaningless ───────────────────

def test_a_loss_making_business_is_refused_rather_than_valued():
    """The arithmetic still returns a number for negative owner earnings: a
    negative price target with an ordinary-looking 54% terminal share hiding the
    fact that both halves of the ratio are negative. That number then flows into
    position sizing."""
    with pytest.raises(DCFError) as excinfo:
        _dcf(owner_earnings=-100)
    assert "owner_earnings" in str(excinfo.value)


def test_zero_owner_earnings_is_refused():
    with pytest.raises(DCFError):
        _dcf(owner_earnings=0)


@pytest.mark.parametrize("bad", ["-1", "-1.5", "-3"])
def test_growth_at_or_below_minus_one_hundred_percent_is_refused(bad):
    """-3 meaning -3% used to return a positive, plausible 1077.92."""
    with pytest.raises(DCFError) as excinfo:
        _dcf(growth_rate=bad)
    assert "-100%" in str(excinfo.value)


@pytest.mark.parametrize("bad", ["-1", "-2"])
def test_terminal_growth_at_or_below_minus_one_hundred_percent_is_refused(bad):
    with pytest.raises(DCFError):
        _dcf(terminal_growth=bad)


def test_terminal_share_stays_within_zero_and_one_for_valid_inputs():
    """It used to leave [0,1] whenever a sign flip put the present value and the
    terminal value on opposite sides of zero."""
    for g in ("-0.9", "-0.5", "0.0", "0.5", "1.0"):
        for years in (1, 5, 10, 30):
            result = _dcf(growth_rate=g, years=years)
            assert Decimal(0) <= result.terminal_share <= Decimal(1), (
                f"g={g} years={years} -> {result.terminal_share}"
            )


def test_terminal_share_matches_a_hand_computed_value():
    """0 < ts < 1 passes even when the figure is 5% wrong."""
    # Zero growth throughout: PV of 10 years of 100 at 10%, plus a 1000
    # perpetuity discounted 10 years. Terminal share = 1000/1.1^10 / 1000.
    result = _dcf(growth_rate="0.00", terminal_growth="0.00", years=10)
    expected = (Decimal(1000) / (Decimal("1.1") ** 10)) / Decimal(1000)
    assert result.terminal_share == pytest.approx(expected, rel=Decimal("1e-12"))


def test_the_spread_guard_fires_exactly_at_the_boundary():
    _dcf(discount_rate="0.085", terminal_growth="0.08")      # spread == 0.005, allowed
    with pytest.raises(DCFError):
        _dcf(discount_rate="0.08499", terminal_growth="0.08")


def test_a_scenario_without_a_name_is_named_as_the_problem():
    with pytest.raises(DCFError) as excinfo:
        scenario_values([{"probability": 1.0, "growth_rate": "0.1"}], _base_inputs())
    assert "name" in str(excinfo.value)


def test_a_scenario_without_a_probability_is_refused():
    with pytest.raises(DCFError) as excinfo:
        scenario_values([{"name": "base", "growth_rate": "0.1"}], _base_inputs())
    assert "probability" in str(excinfo.value)


def test_a_scenario_setting_an_unknown_input_is_refused():
    """A typo'd key used to be silently ignored, so the scenario quietly ran on
    the base assumptions it thought it had overridden."""
    with pytest.raises(DCFError) as excinfo:
        scenario_values(
            [{"name": "base", "probability": 1.0, "discount_rte": "0.2"}],
            _base_inputs(),
        )
    assert "discount_rte" in str(excinfo.value)


def test_scenario_results_carry_their_full_resolved_inputs():
    """The report recomputes each row as the reader moves a slider, and a
    scenario that overrode the discount rate has to keep that override."""
    results = scenario_values(
        [{"name": "bear", "probability": 1.0, "growth_rate": "0.0",
          "discount_rate": "0.20"}],
        _base_inputs(),
    )
    assert results[0]["inputs"]["discount_rate"] == 0.20
    assert results[0]["inputs"]["growth_rate"] == 0.0
    assert results[0]["overrides"] == ["discount_rate", "growth_rate"]
