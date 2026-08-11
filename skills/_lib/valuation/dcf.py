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


class DCFError(ValueError):
    """The inputs cannot produce a meaningful valuation."""


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
    if years < 1:
        raise DCFError(f"years must be at least 1, got {years}")
    if years > _MAX_PROJECTION_YEARS:
        raise DCFError(
            f"years={years} exceeds {_MAX_PROJECTION_YEARS}; a projection that "
            f"long is an assumption about the terminal rate wearing a spreadsheet"
        )

    fade_to = g if terminal_growth is None else _dec(terminal_growth, "terminal_growth")
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

    Returns the annual rate as a Decimal, or None if no rate in the searched
    range reproduces the market value. That happens when the market is pricing
    the business below the value of its current earnings in perpetuity, which is
    a finding rather than a failure — report it, do not fill it in.
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

    # Bracket: -50% to +100% a year covers any rate worth taking seriously.
    low, high = Decimal("-0.5"), Decimal("1.0")
    if value_at(low) > target or value_at(high) < target:
        return None

    for _ in range(max_iterations):
        mid = (low + high) / 2
        value = value_at(mid)
        if abs(value - target) <= abs(target) * tolerance:
            return mid
        if value < target:
            low = mid
        else:
            high = mid
    return (low + high) / 2


def scenario_values(scenarios, base_inputs: dict) -> list:
    """Run one DCF per scenario, returning each with its computed value.

    Each scenario is a dict with `name`, `probability`, and any DCF input it
    overrides. What comes back is what the Valuation record stores and what
    research-portfolio reads as Kelly inputs, so the probabilities travel with
    the values rather than being re-stated later from memory.
    """
    out = []
    for scenario in scenarios:
        name = scenario.get("name", "<unnamed>")
        inputs = dict(base_inputs)
        inputs.update({
            k: v for k, v in scenario.items()
            if k not in ("name", "probability", "assumptions")
        })
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
            # The growth rate travels with the result so the interactive report
            # can recompute this scenario when the reader moves the discount
            # rate. Without it the page has a row it cannot recalculate.
            "growth_rate": float(result.inputs["growth_rate"]),
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
