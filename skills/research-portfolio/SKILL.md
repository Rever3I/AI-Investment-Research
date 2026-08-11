---
name: research-portfolio
description: >
  Turn a valuation's scenario probabilities into a position weight, using half
  Kelly by default, full Kelly or a fixed percentage if configured, with an
  optional concentration cap. Use when the user asks how much to buy, what
  position size to take, how to size a trade, or what weight a name deserves in
  the portfolio.
compatibility: claude-code opencode
allowed-tools:
  - Read
  - Write
  - Bash
---

# Research Portfolio (Layer 6)

Converts the scenario probabilities from `research-valuation` into a fraction of
capital. The arithmetic is in `skills/_lib/valuation/sizing.py` and is not yours
to reproduce.

## The honest caveat, stated up front

Kelly is exact arithmetic applied to inexact inputs. It maximises long-run
growth **given the probabilities**, and those probabilities were a human's
judgment several layers ago. A Kelly fraction computed from numbers nobody
thought hard about is a position size that looks quantitative and is not.

So before sizing, look at the probabilities and ask whether they were reasoned
or reached for. If they were reached for, say so — that is more useful than a
weight computed to two decimal places on top of them.

## Sizing

```python
from skills._lib.config import load_profile
from skills._lib.data.valuation_store import get_valuation
from skills._lib.valuation.sizing import size_position

valuation = get_valuation(valuation_id)
profile = load_profile()

result = size_position(
    valuation.scenarios,
    market_price=current_price,          # verified, not remembered
    method=profile["sizing_method"],     # half_kelly by default
    cap=profile.get("position_cap"),     # optional concentration limit
)
```

`get_valuation` raises `FileNotFoundError` on a fresh install; catch it and say
to run `research-valuation` first. The market price passes the Fact contract
before it gets here — the whole calculation is a ratio against it, so a stale
price silently scales the answer.

Three methods, all in the profile:

- `half_kelly` (default) — the usual hedge against the probabilities being
  wrong. Full Kelly is growth-optimal only if they are exactly right, and its
  drawdowns are severe when they are not.
- `full_kelly` — available, and the result says what it costs.
- `fixed_pct` — ignores the edge entirely and uses a set weight. The result
  still reports what Kelly would have said, for comparison.

## The answers that surprise people

**Zero is a real answer.** When expected return is not positive at the current
price, Kelly sizes the position at nothing. That is the arithmetic declining the
bet, not a missing number, and reporting it as "no recommendation" misrepresents
it. Say the edge is not there at this price.

**A capped position is not the same as an uncapped one.** If a concentration
limit bound the answer, `result.note` says so. Pass that on — the difference
between "Kelly wants 30% and your limit says 5%" and "Kelly wants 5%" matters to
whoever is deciding.

**An optimum above 100% is reported as 100%, not as leverage.** The module does
not size a levered position; if the edge is that large, the constraint is
something other than arithmetic.

**A scenario implying total loss is refused.** Kelly is undefined against an
outcome that wipes the position out, and that case needs a decision about
whether to hold the security at all, not a weight.

## Saving

```python
from skills._lib.data.schema import Portfolio
from skills._lib.data.portfolio_store import save_portfolio

portfolio = Portfolio(
    valuation_id=valuation.id,
    sizing_method=result.method,
    recommended_position_pct=float(result.percent),
    kelly_inputs={
        "full_kelly": float(result.full_kelly),
        "expected_return": float(result.expected_return),
        "market_price": float(current_price),
        "outcomes": [
            {"name": o["name"], "probability": float(o["probability"]),
             "return": float(o["return"])}
            for o in result.outcomes
        ],
    },
    sized_at=today_iso,
)
row_id = save_portfolio(portfolio)
```

Store the inputs, not just the answer. A weight with no visible probabilities
behind it cannot be argued with later, including by the person who produced it.

Note `recommended_position_pct` is a percentage (4.25 means 4.25% of capital),
while `result.fraction` is the fraction. `result.percent` does the conversion.

## Output language

Follow `output_language()` for your commentary. Do not translate `sizing_method`
— the record validates it against `half_kelly`, `full_kelly`, `fixed_pct`,
`custom` — or the scenario names inside `kelly_inputs`.

## Finishing

Report the weight, the method, the expected return it came from, and whether a
cap bound it. Show the probabilities the answer rests on, because that is what
the user should push on if they disagree.

Do not tell the user to place a trade. This is a weight derived from stated
assumptions; whether to act on it is theirs.
