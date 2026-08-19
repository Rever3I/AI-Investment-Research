# Stage 3 — Valuation, and the optional dissent pass


Takes a `Thesis` and produces a `Valuation`: scenario values with probabilities
attached, and an interactive page that lets a reader push on the assumptions
rather than accept a number.

## The arithmetic is not yours to do

Every figure comes from `airesearch/valuation/`, which computes in `Decimal`
and refuses inputs that produce meaningless results. Do not do this in your
head, and do not check its answer against your own — if the two disagree the
module is right, because it is the thing that will still be right in a year.

```python
from airesearch.valuation import (
    discounted_cash_flow, implied_growth_rate, scenario_values, expected_value,
)
```

There is deliberately **no default discount rate**. State it, and state where it
came from, because that provenance is stored on the record and is what makes the
valuation re-checkable. A US 10-year yield plus an equity risk premium is a
common construction; it is not the right one for every listing, and a built-in
default is how a US-shaped assumption gets applied silently to a company
somewhere else.

## Getting the thesis

```python
from airesearch.data.thesis_store import get_thesis

thesis = get_thesis(thesis_id)
```

Raises `FileNotFoundError` when nothing has been researched yet. Catch it and
say to run stage 2 first, rather than surfacing a traceback. A
valuation with no thesis behind it is a price target with no argument attached,
so `save_valuation` refuses one.

## Inputs

Owner earnings is the starting figure: net income plus depreciation and
amortisation, less capital expenditure. It must be positive — an owner-earnings
DCF does not apply to a business that produces none, and the module refuses
rather than returning the negative price target the arithmetic would otherwise
hand you. For a loss-maker, say the method does not fit and stop. Every number in it passes the Fact
contract first, grouped so a quarterly figure cannot end up divided by a
trailing-twelve-month one:

The SEC adapter returns exactly these four as Facts, already grouped:

```python
from airesearch.data.adapters import configure, fetch
from airesearch.factcontract import verify

configure()
facts = fetch("us_equity", ticker)      # net income, D&A, capex, share count
price = fetch("price", ticker)[0]       # the reverse DCF is a ratio against it
verify(facts + [price])                 # hard-stops on anything stale
```

Fetched some other way, the same figures have to be declared by hand:

```python
from airesearch.factcontract import Fact, verify

verify([
    Fact(name="NVDA_net_income", value=..., unit="usd", freq="ttm",
         as_of=filing_date_iso, source="sec-xbrl", entity="NVDA", group="oe"),
    Fact(name="NVDA_dep_amort", value=..., unit="usd", freq="ttm",
         as_of=filing_date_iso, source="sec-xbrl", entity="NVDA", group="oe"),
    Fact(name="NVDA_capex", value=..., unit="usd", freq="ttm",
         as_of=filing_date_iso, source="sec-xbrl", entity="NVDA", group="oe"),
])
```

## Scenarios

Three is usually right: bull, base, bear. What matters is that the
**probabilities are yours and are stated**, because stage 4 reads
them directly as position-sizing inputs. Probabilities that were never really
thought about produce a position size that looks quantitative and is not.

```python
base_inputs = dict(
    owner_earnings=owner_earnings,
    growth_rate="0.10",
    discount_rate="0.10",          # no default; yours, with a source
    terminal_growth="0.03",
    years=10,
    shares_outstanding=shares,
)
scenarios = scenario_values([
    {"name": "bull", "probability": 0.25, "growth_rate": "0.20",
     "assumptions": "networking attach rate holds above 30%"},
    {"name": "base", "probability": 0.50, "growth_rate": "0.10"},
    {"name": "bear", "probability": 0.25, "growth_rate": "0.00",
     "assumptions": "hyperscaler capex digests for two years"},
], base_inputs)
```

Each scenario overrides only what it names; everything else comes from
`base_inputs`. Write the `assumptions` string so a reader can tell what
distinguishes this case — "growth is higher" is not an assumption, it is a
restatement of the growth rate.

Probabilities must sum to 1. The record enforces it, because a set that does not
would corrupt the sizing downstream.

## The reverse DCF is the more useful output

```python
from airesearch.valuation import PriceOutsideBracket

implied = None
try:
    implied = implied_growth_rate(
        market_value=current_price, owner_earnings=owner_earnings,
        discount_rate="0.10", terminal_growth="0.03", years=10,
        shares_outstanding=shares,
    )
except PriceOutsideBracket as exc:
    out_of_range = exc          # exc.direction is "below" or "above"
```

This turns "is it cheap" into "the price assumes 18% a year for a decade — is
that going to happen?", which is a question the reader can actually judge. Lead
with it.

`PriceOutsideBracket` means no growth rate in the searched range fits, and
`exc.direction` says which side. **Report the direction it gives you, not a
remembered one** — `"below"` means the price sits under the value of these owner
earnings even shrinking; `"above"` means it sits over the value of very fast
growth, which is ordinary for a business whose owner earnings are near zero
because capital expenditure eats them. These are opposite findings and saying
the wrong one is worse than saying neither.

Also report `terminal_share` from each scenario. A valuation that is 85%
terminal value is a statement about the discount rate rather than about the
business, and the reader deserves to know which one they are being shown.

## The interactive page

```python
from pathlib import Path

from airesearch.config import output_language
from airesearch.valuation.report import render

page = render(
    ticker=ticker, scenarios=scenarios, owner_earnings=owner_earnings,
    discount_rate="0.10", terminal_growth="0.03", years=10,
    shares_outstanding=shares, discount_rate_source=rate_source,
    market_price=current_price, implied_growth=implied, currency="$",
    generated_at=today_iso, language=output_language(),
)
path = Path("reports") / f"{ticker}-{today_iso}.html"
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(page, encoding="utf-8")   # encoding is not optional
```

The file is entirely self-contained — no CDN, no fonts, no network — so it still
opens years later on a machine with no connection. Store its path on the record
and tell the user where it is.

## Output language

`output_language()` (imported above) decides the language of everything the
reader sees.

**Translate:** your commentary, and each scenario's `assumptions` string.

**Never translate:** scenario `name` values (`bull` / `base` / `bear` — the
report styles rows by matching them, and stage 4 reads them), and
`discount_rate_source` if it names an instrument, since that is provenance.

## Saving

```python
from airesearch.data.schema import Valuation
from airesearch.data.valuation_store import save_valuation

valuation = Valuation(
    thesis_id=thesis.id,
    scenarios=scenarios,
    discount_rate_source="US 10Y (4.2%) + 5% equity risk premium",
    html_artifact_path=str(path),
    valued_at=today_iso,
)
row_id = save_valuation(valuation)
```

Revaluing appends rather than overwrites: the old numbers are the record of what
was believed when a position was sized.

---

# The dissent pass (optional)

A valuation is the natural moment to put the thesis under pressure: the numbers
exist, and nothing has been sized yet. This pass is off unless the user asked
for it or configured it on.

```python
from airesearch.config import load_profile

if not load_profile()["debate_enabled"]:
    ...   # skip, and say so once rather than running it anyway
```

A layer the user switched off is a layer whose cost they have decided.

## What it is for

Not to reach a conclusion. The numbers are already computed and sizing comes
next; a panel that restates the base case adds ceremony and no information.

What it produces that nothing else does is the **dissent map**: the arguments
that survived contact with each other and were still not resolved, each tagged
with what would settle it. That is the part worth reading in a year, because it
names in advance where the thesis was fragile. A pass that averages three views
into one verdict has destroyed the only output the reader could not have written
themselves.

## Two modes

`mode="checklist"` — the default. One analytical voice working the pressure
points:

- Which claim is doing the most work, and what happens if it is wrong?
- What does the bear case need to be true, and how would you know early?
- Which falsifier from the thesis is closest to firing right now?
- Where does the terminal share sit, and does the story justify it?
- What would someone who has held the other side for a year say?

`mode="persona_debate"` — a panel of named investor voices, if the user chose
that. Each argues from a discipline rather than performing a personality: a
quality-and-moat voice, a margin-of-safety voice, a what-am-I-missing voice, a
macro-regime voice. Two rounds is enough — one to state positions, one to answer
the strongest objection raised against them.

Either way the useful output is the same: where the voices agreed, where they
did not, and what evidence would move each unresolved point.

Any figure introduced during the pass goes through the Fact contract like every
other number here. A bear case built on a remembered percentage is not a bear
case, it is a mood.

## Saving the verdict

```python
from airesearch.data.schema import Verdict
from airesearch.data.verdict_store import save_verdict

verdict = Verdict(
    valuation_id=valuation.id,
    mode="checklist",                      # or "persona_debate"
    votes=[{"voice": "...", "call": "...", "why": "..."}],
    dissent_map="What was not resolved, and what would settle each point.",
    authored_at=today_iso,
)
row_id = save_verdict(verdict)
```

`votes` may be empty in checklist mode. `dissent_map` should not be — "no
unresolved disagreement" is a finding worth stating, and an empty string reads
as an omission rather than a conclusion.

Do not translate `mode`: the record validates it against `"checklist"` and
`"persona_debate"` exactly.

---

## Finishing

Lead with the implied growth rate, then the probability-weighted value against
the price, then the scenario table with its terminal shares. Say where the page
is. If the dissent pass ran, lead its section with what was **not** resolved
rather than with the verdict.

Stop there. Sizing is stage 4, and it does not run unasked.

Do not tell the user to buy or sell. Present what the price assumes and what you
believe; the decision is theirs.
