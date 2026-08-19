#!/usr/bin/env python
"""Position sizing from scenario probabilities.

Kelly answers one question: what fraction of capital maximises the long-run
growth rate of that capital, given a set of outcomes and their probabilities.
It is arithmetic, not judgment — and the judgment it depends on, the
probabilities, came from a human several layers upstream. A Kelly fraction
computed from probabilities nobody thought hard about is a number that looks
quantitative and is not, which is why this module reports the inputs it used
alongside the answer.

Half Kelly is the default. Full Kelly is growth-optimal only if the
probabilities are exactly right, and its drawdowns are brutal when they are not:
being wrong about `p` costs far more at full than the growth you give up by
halving. Practitioners halve; so does this.

Three outcomes cannot use the textbook binary formula. `f* = (bp - q) / b`
assumes you either win `b` or lose everything staked, which is not what a bull,
base and bear case describe. The general form maximises expected log wealth
directly, and this module solves that.
"""

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

# Kelly is undefined once a scenario can wipe out the position: log(0) diverges.
# A return at or below -100% means the equity is worthless in that case, which
# needs a different conversation than position sizing.
_MIN_RETURN = Decimal("-1")

# Numerical search bounds for the fraction of capital.
_MAX_FRACTION = Decimal("1")

# A price target more than this far above the price is a unit mistake. The usual
# way in is a total equity value where a per-share figure belongs.
_MAX_PLAUSIBLE_RETURN = Decimal("20")
_TOLERANCE = Decimal("0.0000001")
_MAX_ITERATIONS = 200


class SizingError(ValueError):
    """The inputs cannot produce a meaningful position size."""


def _dec(value, name: str) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise SizingError(f"{name} is not a number: {value!r}") from exc


@dataclass
class SizingResult:
    """A recommended weight, and everything needed to argue with it."""

    method: str
    fraction: Decimal
    full_kelly: Decimal
    expected_return: Decimal
    outcomes: list = field(default_factory=list)
    note: str = ""
    # True when the unconstrained optimum was above 100% of capital and
    # full_kelly is therefore a ceiling rather than the Kelly answer. Without
    # this, a reader comparing full_kelly across two names cannot tell which is
    # a real optimum and which was censored.
    clipped: bool = False
    capped: bool = False

    @property
    def percent(self) -> Decimal:
        return self.fraction * 100


def scenario_returns(scenarios, market_price) -> list:
    """Convert price targets into returns against the current price."""
    price = _dec(market_price, "market_price")
    if price <= 0:
        raise SizingError(f"market_price must be positive, got {price}")

    out = []
    total_probability = Decimal(0)
    for scenario in scenarios:
        name = scenario.get("name", "<unnamed>")
        if "price_target" not in scenario:
            raise SizingError(f"scenario {name!r} has no price_target")
        if "probability" not in scenario:
            raise SizingError(f"scenario {name!r} has no probability")
        probability = _dec(scenario["probability"], f"{name}.probability")
        if probability < 0:
            raise SizingError(f"scenario {name!r} has a negative probability")
        total_probability += probability
        target = _dec(scenario["price_target"], f"{name}.price_target")
        implied = target / price - Decimal(1)
        if implied > _MAX_PLAUSIBLE_RETURN:
            raise SizingError(
                f"scenario {name!r} implies a return of {implied:.0%}. A price "
                f"target that far above the price is a unit error, not an "
                f"opportunity: check whether it is a per-share figure or a total "
                f"equity value."
            )
        out.append({
            "name": name,
            "probability": probability,
            "return": implied,
        })

    if abs(total_probability - Decimal(1)) > Decimal("0.01"):
        raise SizingError(
            f"scenario probabilities sum to {total_probability}, not 1. Sizing "
            f"off an incomplete distribution silently overstates the edge."
        )
    return out


def _expected_log_growth_slope(fraction: Decimal, outcomes) -> Decimal:
    """d/df of expected log wealth. Zero at the Kelly optimum."""
    slope = Decimal(0)
    for outcome in outcomes:
        denominator = Decimal(1) + fraction * outcome["return"]
        if denominator <= 0:
            # Past this fraction the position is wiped out in that scenario, so
            # expected log wealth is negative infinity. Report a steep negative
            # slope so the search moves back.
            return Decimal("-1e9")
        slope += outcome["probability"] * outcome["return"] / denominator
    return slope


def kelly_fraction(outcomes, want_clipped: bool = False):
    """The full-Kelly fraction for a set of probability-weighted returns.

    Solves for where expected log growth stops rising. Returns 0 when the
    expected return is not positive: Kelly's answer to a bet with no edge is not
    to take it, and a negative fraction would be an instruction to short, which
    is a different decision than sizing a long.
    """
    if not outcomes:
        raise SizingError("no outcomes to size from")
    for outcome in outcomes:
        if outcome["return"] <= _MIN_RETURN:
            raise SizingError(
                f"scenario {outcome['name']!r} implies a return of "
                f"{outcome['return']:.0%}, a total loss. Kelly is undefined "
                f"against an outcome that wipes the position out; that case "
                f"needs a decision about whether to hold it at all."
            )

    def answer(fraction, clipped):
        return (fraction, clipped) if want_clipped else fraction

    # At f=0 the slope is the expected return. Not positive means no edge.
    if _expected_log_growth_slope(Decimal(0), outcomes) <= 0:
        return answer(Decimal(0), False)
    # A slope still positive at full capital means the optimum is at or beyond
    # it; without leverage the answer is all of it, and the caller needs to know
    # that this is a ceiling rather than the optimum.
    if _expected_log_growth_slope(_MAX_FRACTION, outcomes) > 0:
        return answer(_MAX_FRACTION, True)

    low, high = Decimal(0), _MAX_FRACTION
    for _ in range(_MAX_ITERATIONS):
        mid = (low + high) / 2
        slope = _expected_log_growth_slope(mid, outcomes)
        if abs(slope) < _TOLERANCE:
            return answer(mid, False)
        if slope > 0:
            low = mid
        else:
            high = mid
    return answer((low + high) / 2, False)


METHODS = ("half_kelly", "full_kelly", "fixed_pct", "custom")


def size_position(
    scenarios,
    market_price,
    method: str = "half_kelly",
    weight=None,
    cap=None,
) -> SizingResult:
    """Recommend a position weight from scenario probabilities.

    method       one of METHODS. "half_kelly" is the default.
    weight       the fraction of capital to use, required by "fixed_pct" (a
                 standing policy weight) and "custom" (a weight the caller
                 arrived at some other way). Ignored by the Kelly methods.
    cap          optional ceiling, as a fraction of capital. A concentration
                 limit is a portfolio decision Kelly knows nothing about.

    All fractions here are fractions, not percentages: 0.05 is five percent of
    capital. `SizingResult.percent` converts for display.
    """
    outcomes = scenario_returns(scenarios, market_price)
    expected = sum(o["probability"] * o["return"] for o in outcomes)

    if method not in METHODS:
        raise SizingError(
            f"unknown sizing method {method!r}; expected one of {list(METHODS)}"
        )

    if method in ("fixed_pct", "custom"):
        if weight is None:
            raise SizingError(
                f"method {method!r} needs a weight: it does not derive one from "
                f"the scenarios. Set `fixed_pct` in your profile, or pass "
                f"weight= directly."
            )
        fraction = _dec(weight, "weight")
        if fraction < 0:
            raise SizingError(f"weight cannot be negative, got {fraction}")
        if fraction > _MAX_FRACTION:
            raise SizingError(
                f"weight={fraction} is more than all of the capital. Weights are "
                f"fractions here: 0.05 is five percent, 5 is five hundred."
            )
        full, clipped = kelly_fraction(outcomes, want_clipped=True)
        note = (
            "Weight set by the caller, not derived from the edge; the Kelly "
            "figure is shown for comparison only."
        )
    else:
        full, clipped = kelly_fraction(outcomes, want_clipped=True)
        fraction = full if method == "full_kelly" else full / 2
        if full == 0:
            note = (
                "Expected return is not positive at this price, so Kelly sizes "
                "the position at zero. That is the arithmetic declining the bet, "
                "not a missing number."
            )
        elif method == "full_kelly":
            note = (
                "Full Kelly is growth-optimal only if these probabilities are "
                "exactly right, and its drawdowns are severe when they are not."
            )
        else:
            note = "Half Kelly: the usual hedge against the probabilities being wrong."

    if clipped:
        note += (
            " The unconstrained optimum is above 100% of capital, so the Kelly "
            "figure shown is that ceiling rather than the optimum itself."
        )

    capped = False
    if cap is not None:
        ceiling = _dec(cap, "cap")
        if ceiling < 0:
            raise SizingError(f"cap cannot be negative, got {ceiling}")
        if ceiling > _MAX_FRACTION:
            raise SizingError(
                f"cap={ceiling} is above all of the capital. Caps are fractions "
                f"here: 0.05 is a five percent limit, 5 is five hundred percent "
                f"and would never bind."
            )
        if fraction > ceiling:
            fraction = ceiling
            capped = True
            note += f" Capped at {ceiling:.1%} by the configured concentration limit."

    return SizingResult(
        method=method,
        fraction=fraction,
        full_kelly=full,
        expected_return=expected,
        outcomes=outcomes,
        note=note,
        clipped=clipped,
        capped=capped,
    )
