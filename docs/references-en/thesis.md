# Stage 2 — Thesis: the written, falsifiable view


Takes a `Candidate` from `research-intake` and turns it into a `Thesis`: the
first point in the pipeline where a view gets committed to writing and made
falsifiable.

## What separates this from a company summary

Anyone can restate a 10-K. Two sections carry the actual work, and a thesis
without them is a briefing note wearing a thesis's clothes:

**Variant perception** — what you believe that the market does not, and why the
gap exists. "Nvidia sells a lot of GPUs" is consensus and worth nothing. "The
market prices the GPU and ignores that networking is now a third of system
revenue at higher attach than the sell side models" is a view. If you cannot
articulate what the price already reflects, you do not yet have a thesis; say so
rather than dressing up consensus.

**Falsifiers** — the specific, observable things that would make you wrong. Write
them so a future reader can check them against reality without re-litigating the
whole argument: "two consecutive quarters of hyperscaler capex guiding down,"
not "if the AI cycle turns." `research-sellcheck` reads these later and diffs
them against what actually happened, which only works if they name events rather
than moods.

## Getting the candidate

```python
from airesearch.data.candidate_store import get_candidate, list_candidates

candidate = get_candidate(candidate_id)          # if the user named an id
recent = list_candidates(market="US", limit=10)  # to pick from
```

Both raise `FileNotFoundError` when nothing has ever been saved — a fresh
install has no candidates table at all. Catch it and tell the user to run
`research-intake` first rather than surfacing a traceback.

If the user names a ticker with no candidate behind it, the same applies: a
thesis cannot be saved without a real `candidate_id`. `save_thesis` refuses it
with a `ValueError` naming the id, and the database's foreign key would refuse
it too, so that `research-sellcheck` can never resolve a thesis to a candidate
that does not exist.

## The document

Cover these, in whatever order reads best for the company:

- **Business overview** — what it sells, to whom, how it makes money. Unit
  economics where they are knowable.
- **Management** — who runs it, their record, incentives, ownership. Capital
  allocation history is usually more informative than biography.
- **Competitors** — who else is in the market, what the structure is, where the
  pricing power sits. Name the substitute, not just the peer group.
- **TAM** — the size of the opportunity and, more usefully, the assumptions that
  size depends on. A TAM nobody can falsify is decoration.
- **Risks** — 8 to 12 of them, specific to this business. "Macro conditions may
  deteriorate" applies to every equity ever issued and belongs in none of them.
- **Variant perception** and **falsifiers**, as above.


## Getting the numbers

Adapters return `Fact` objects, so a figure arrives with its source, unit and
as-of time already attached. Configure once, then fetch:

```python
from airesearch.data.adapters import configure, fetch, status_report

print(status_report(configure()))          # what can run in this installation
facts = fetch("us_equity", ticker)         # net income, D&A, capex, share count
price = fetch("price", ticker)[0]          # works with no configuration
```

If a domain reports itself unavailable, say which setting is missing rather than
working around it — `status_report()` prints the exact key and where to get it.
A number fetched some other way has no provenance, which is the thing this
layer exists to prevent.

Chinese listings go through `fetch("cn_equity", "600519")` and need no
configuration: the primary is Eastmoney's public endpoints, and a six-digit code
is accepted with or without an exchange suffix. Wind sits behind it for anyone
with a terminal, unverified against a live one. Banks, insurers and brokers are
refused with the reason — owner earnings does not describe them.

## Numbers

Every figure passes through the Fact contract before it reaches the write-up:

```python
from airesearch.factcontract import Fact, verify

verify([
    # as_of is the period the figure describes. Use the real filing date — the
    # ttm limit is 100 days, so a stale one hard-stops here rather than in print.
    Fact(name="NVDA_revenue_ttm", value=130_500_000_000, unit="usd", freq="ttm",
         as_of=filing_date_iso, source="sec-xbrl", entity="NVDA",
         group="valuation"),
])
```

It hard-stops on stale data and warns when a unit or magnitude looks wrong.
Facts that feed the same calculation share a `group`, which is what catches a
quarterly numerator over a trailing-twelve-month denominator.

Do not quote a price, a multiple, or a growth rate from memory or from an
article of unknown vintage. Fetch it, declare it, verify it. Record where each
material claim came from in `data_sources` — that list is what makes the thesis
auditable a year later when the numbers have all moved.

## Output language

```python
from airesearch.config import output_language
lang = output_language()   # "en" by default; "zh-CN", "ja", anything the model reads
```

Prose goes in that language. Some values must not follow it, because downstream
layers select and compare on them — a translated value there does not fail
loudly, it fails months later when nothing matches.

**Translate:** `business_overview`, `management`, `competitors`, `tam`, each
entry in `risks`, `variant_perception`, each entry in `falsifiers`, and your
on-screen commentary.

**Never translate:** entries in `data_sources` (they are provenance strings such
as `sec-xbrl:10-K FY2025`, matched literally), and the originating candidate's
`source_note` — on the thesis path that is the user's own words, and
`research-sellcheck` diffs against them. Translation is paraphrase, and
paraphrase destroys the thing being tested.

## Saving

```python
from airesearch.data.schema import Thesis
from airesearch.data.thesis_store import save_thesis

thesis = Thesis(
    candidate_id=candidate.id,
    business_overview="...",
    management="...",
    competitors="...",
    tam="...",
    risks=["...", "..."],              # at least one; aim for 8-12
    variant_perception="...",
    falsifiers=["...", "..."],
    data_sources=["sec-xbrl:10-K FY2025", "Q1 FY2026 call transcript"],
    authored_at="2026-08-04T12:00:00Z",
)
row_id = save_thesis(thesis)           # also stamps thesis.id
```

Re-researching a name writes a new thesis rather than overwriting the old one.
That is intentional: the history is what `research-sellcheck` compares against.

## Finishing

Report the thesis and its row id. Stop there — valuation is `research-valuation`,
a separate skill the user invokes next. Running it unasked spends their time on
a number they may not want yet, and a thesis is worth reading on its own.
