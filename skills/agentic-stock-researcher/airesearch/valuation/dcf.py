#!/usr/bin/env python
"""Owner-earnings discounted cash flow, and the reverse question it answers better.

This module computes and never fetches. Every input arrives explicitly from the
caller, which is what keeps the arithmetic auditable: the numbers came through
the Fact contract, and what happens to them afterwards is here, in code, rather
than in a model's head.

Two things it deliberately does not do:

- It has no default discount rate. A single hard-coded rate is how a US-shaped
  assumption ends up silently applied to a Shanghai listing. The caller states
  the rate and where it came from, and that provenance is stored on the record.
- It does not decide whether something is cheap. It produces a value under
  stated assumptions and, more usefully, the growth the market is already
  pricing. The judgment is the analyst's.

Decimal throughout: float arithmetic on ten-year cash flow projections
accumulates error that shows up in the last significant figure of a price
target, which is exactly where someone will squint at it.
"""

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

# A terminal growth rate at or above the discount rate makes the Gordon
# denominator zero or negative, which yields an infinite or negative value that
# looks like a number and is not one.
_MIN_SPREAD = Decimal("0.005")

_MAX_PROJECTION_YEARS = 50

# A rate at or below -100% shrinks cash flow past zero and then compounds the
# negative, which yields a positive present value for a business in free fall.
_MIN_GROWTH = Decimal("-1")

# The range the reverse DCF searches. Wide enough for anything worth taking
# seriously, and reported explicitly when a price falls outside it.
_SEARCH_LOW = Decimal("-0.5")
_SEARCH_HIGH = Decimal("1.0")


class DCFError(ValueError):
    """The inputs cannot produce a meaningful valuation."""


class PriceOutsideBracket(DCFError):
    """No growth rate in the searched range reproduces the market price.

    `direction` is "below" when the price sits under the value of current owner
    earnings even with earnings shrinking as fast as the search allows, and
    "above" when it sits over the value implied by the fastest rate searched.
    These are opposite findings and reporting one as the other is worse than
    reporting neither, which is why they are not both a bare None.
    """

    def __init__(self, direction: str, market_value, bound_value, bound_rate):
        self.direction = direction
        self.market_value = market_value
        self.bound_value = bound_value
        self.bound_rate = bound_rate
        if direction == "below":
            detail = (
                f"the price ({market_value}) is below the value of these owner "
                f"earnings even at {bound_rate:%} annual growth ({bound_value})"
            )
        else:
            detail = (
                f"the price ({market_value}) is above the value implied by even "
                f"{bound_rate:%} annual growth ({bound_value})"
            )
        super().__init__(f"No growth rate in the searched range fits: {detail}.")


def _dec(value, name: str) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise DCFError(f"{name} is not a number: {value!r}") from exc


@dataclass
class DCFResult:
    """What a single set of assumptions produces.

    `per_share` is None when no share count was supplied — the total is still
    meaningful, and inventing a per-share figure from a missing denominator is
    worse than admitting it is absent.
    """

    present_value: Decimal
    terminal_value_pv: Decimal
    projected_owner_earnings: list = field(default_factory=list)
    per_share: Decimal = None
    inputs: dict = field(default_factory=dict)

    @property
    def terminal_share(self) -> Decimal:
        """How much of the value rests on the terminal assumption.

        A valuation that is 90% terminal value is a statement about the
        discount rate, not about the business.
        """
        if self.present_value == 0:
            return Decimal(0)
        return self.terminal_value_pv / self.present_value


def project_owner_earnings(
    owner_earnings,
    growth_rate,
    years: int,
    terminal_growth=None,
) -> list:
    """Owner earnings for each projected year.

    When `terminal_growth` is given, the growth rate fades linearly toward it
    across the projection. A business does not step from 25% growth to 3% in one
    year, and a model that says it does front-loads value into the early years.
    """
    oe = _dec(owner_earnings, "owner_earnings")
    g = _dec(growth_rate, "growth_rate")
    if oe <= 0:
        raise DCFError(
            f"owner_earnings must be positive, got {oe}. An owner-earnings DCF "
            f"does not apply to a business that produces none: the arithmetic "
            f"still returns a number, and that number is a negative price target "
            f"with an ordinary-looking terminal share hiding inside it."
        )
    if years < 1:
        raise DCFError(f"years must be at least 1, got {years}")
    if years > _MAX_PROJECTION_YEARS:
        raise DCFError(
            f"years={years} exceeds {_MAX_PROJECTION_YEARS}; a projection that "
            f"long is an assumption about the terminal rate wearing a spreadsheet"
        )
    # Below -100% the cash flows change sign and then "grow", which produces a
    # positive, plausible-looking present value out of a collapsing business.
    # The realistic way in is a percent-versus-fraction slip: -3 meaning -3%.
    if g <= _MIN_GROWTH:
        raise DCFError(
            f"growth_rate={g} is at or below -100%. Rates are fractions here: "
            f"-0.03 is minus three percent, -3 is minus three hundred."
        )

    fade_to = g if terminal_growth is None else _dec(terminal_growth, "terminal_growth")
    if fade_to <= _MIN_GROWTH:
        raise DCFError(
            f"terminal_growth={fade_to} is at or below -100%. Rates are fractions "
            f"here: -0.03 is minus three percent, -3 is minus three hundred."
        )
    series = []
    current = oe
    for year in range(1, years + 1):
        # Linear fade: year 1 grows at g, the final year at fade_to.
        if years == 1:
            rate = g
        else:
            weight = Decimal(year - 1) / Decimal(years - 1)
            rate = g + (fade_to - g) * weight
        current = current * (Decimal(1) + rate)
        series.append(current)
    return series


def discounted_cash_flow(
    owner_earnings,
    growth_rate,
    discount_rate,
    terminal_growth,
    years: int = 10,
    shares_outstanding=None,
) -> DCFResult:
    """Present value of projected owner earnings plus a Gordon terminal value.

    owner_earnings      the starting figure, normally net income + D&A - capex
    growth_rate         growth in year 1, fading linearly to terminal_growth
    discount_rate       the caller's required return; no default, deliberately
    terminal_growth     perpetual growth after the projection
    years               projection length
    shares_outstanding  optional; supplied, the result carries a per-share value
    """
    r = _dec(discount_rate, "discount_rate")
    g_term = _dec(terminal_growth, "terminal_growth")

    if r <= 0:
        raise DCFError(f"discount_rate must be positive, got {r}")
    if r - g_term < _MIN_SPREAD:
        raise DCFError(
            f"discount_rate ({r}) must exceed terminal_growth ({g_term}) by at "
            f"least {_MIN_SPREAD}. Below that the terminal value explodes and the "
            f"result is an artefact of the arithmetic, not a valuation."
        )

    series = project_owner_earnings(owner_earnings, growth_rate, years, g_term)

    present_value = Decimal(0)
    for year, cash in enumerate(series, start=1):
        present_value += cash / (Decimal(1) + r) ** year

    terminal_value = series[-1] * (Decimal(1) + g_term) / (r - g_term)
    terminal_pv = terminal_value / (Decimal(1) + r) ** years
    present_value += terminal_pv

    per_share = None
    if shares_outstanding is not None:
        shares = _dec(shares_outstanding, "shares_outstanding")
        if shares <= 0:
            raise DCFError(f"shares_outstanding must be positive, got {shares}")
        per_share = present_value / shares

    return DCFResult(
        present_value=present_value,
        terminal_value_pv=terminal_pv,
        projected_owner_earnings=series,
        per_share=per_share,
        inputs={
            "owner_earnings": _dec(owner_earnings, "owner_earnings"),
            "growth_rate": _dec(growth_rate, "growth_rate"),
            "discount_rate": r,
            "terminal_growth": g_term,
            "years": years,
            "shares_outstanding": (
                None if shares_outstanding is None
                else _dec(shares_outstanding, "shares_outstanding")
            ),
        },
    )


def implied_growth_rate(
    market_value,
    owner_earnings,
    discount_rate,
    terminal_growth,
    years: int = 10,
    shares_outstanding=None,
    tolerance=Decimal("0.0001"),
    max_iterations: int = 200,
):
    """The growth rate the current price already assumes — the reverse DCF.

    More useful than a price target, because it converts an argument about
    whether something is cheap into a question anyone can check: is this company
    going to grow owner earnings at that rate for the next decade?

    Returns the annual rate as a Decimal. Raises PriceOutsideBracket when no rate
    in the searched range fits, carrying which side it fell off — a price below
    the value of shrinking earnings and a price above the value of very fast
    growth are opposite findings, and a bare None cannot tell them apart.
    """
    target = _dec(market_value, "market_value")
    if target <= 0:
        raise DCFError(f"market_value must be positive, got {target}")

    def value_at(rate):
        result = discounted_cash_flow(
            owner_earnings=owner_earnings,
            growth_rate=rate,
            discount_rate=discount_rate,
            terminal_growth=terminal_growth,
            years=years,
            shares_outstanding=shares_outstanding,
        )
        return result.per_share if shares_outstanding is not None else result.present_value

    low, high = _SEARCH_LOW, _SEARCH_HIGH
    low_value, high_value = value_at(low), value_at(high)
    if target < low_value:
        raise PriceOutsideBracket("below", target, low_value, low)
    if target > high_value:
        raise PriceOutsideBracket("above", target, high_value, high)

    for _ in range(max_iterations):
        mid = (low + high) / 2
        value = value_at(mid)
        if abs(value - target) <= abs(target) * tolerance:
            return mid
        if value < target:
            low = mid
        else:
            high = mid
    # Bisection on a continuous monotone function always narrows; reaching here
    # means the tolerance is finer than the interval can resolve. Say so rather
    # than returning a midpoint indistinguishable from a converged answer.
    raise DCFError(
        f"implied growth did not converge in {max_iterations} iterations; the "
        f"tolerance ({tolerance}) may be finer than this price can resolve. "
        f"Narrowed to [{low}, {high}]."
    )


def scenario_values(scenarios, base_inputs: dict) -> list:
    """Run one DCF per scenario, returning each with its computed value.

    Each scenario is a dict with `name`, `probability`, and any DCF input it
    overrides. What comes back is what the Valuation record stores and what
    research-portfolio reads as Kelly inputs, so the probabilities travel with
    the values rather than being re-stated later from memory.
    """
    _OVERRIDABLE = ("owner_earnings", "growth_rate", "discount_rate",
                    "terminal_growth", "years", "shares_outstanding")
    out = []
    for scenario in scenarios:
        name = scenario.get("name", "<unnamed>")
        if "name" not in scenario:
            raise DCFError(f"scenario is missing a name: {scenario!r}")
        if "probability" not in scenario:
            raise DCFError(f"scenario {name!r} is missing a probability")

        overrides = {k: v for k, v in scenario.items() if k in _OVERRIDABLE}
        unknown = set(scenario) - set(_OVERRIDABLE) - {"name", "probability", "assumptions"}
        if unknown:
            raise DCFError(
                f"scenario {name!r} sets {sorted(unknown)}, which the DCF does "
                f"not take. Overridable inputs are {list(_OVERRIDABLE)}."
            )
        inputs = dict(base_inputs)
        inputs.update(overrides)
        try:
            result = discounted_cash_flow(**inputs)
        except (DCFError, TypeError) as exc:
            # Without the name, a failure in one of five scenarios sends the
            # caller reading all five sets of assumptions.
            raise DCFError(f"scenario {name!r}: {exc}") from exc
        value = result.per_share if result.per_share is not None else result.present_value
        out.append({
            "name": scenario["name"],
            "probability": scenario["probability"],
            "assumptions": scenario.get("assumptions", ""),
            "price_target": float(value),
            "terminal_share": float(result.terminal_share),
            # The full resolved input set travels with the result, not just the
            # growth rate. The interactive report recomputes each row as the
            # reader moves the sliders, and a scenario that overrode the discount
            # rate has to keep that override — otherwise the page silently shows
            # a different number from the one stored on the record.
            "inputs": {
                "owner_earnings": float(result.inputs["owner_earnings"]),
                "growth_rate": float(result.inputs["growth_rate"]),
                "discount_rate": float(result.inputs["discount_rate"]),
                "terminal_growth": float(result.inputs["terminal_growth"]),
                "years": int(result.inputs["years"]),
                "shares_outstanding": (
                    None if result.inputs["shares_outstanding"] is None
                    else float(result.inputs["shares_outstanding"])
                ),
            },
            # Which of those the scenario set itself, so the report knows what a
            # slider is allowed to change.
            "overrides": sorted(overrides),
        })
    return out


def expected_value(scenarios) -> Decimal:
    """Probability-weighted value across scenarios."""
    total = Decimal(0)
    for scenario in scenarios:
        total += _dec(scenario["price_target"], "price_target") * _dec(
            scenario["probability"], "probability"
        )
    return total
