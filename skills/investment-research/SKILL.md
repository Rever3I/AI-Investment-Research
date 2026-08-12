---
name: investment-research
description: >
  A five-stage equity research pipeline: find candidates, write a falsifiable
  thesis, value it with an owner-earnings DCF and a reverse DCF, size the
  position with Kelly, and check what changed when you think about selling.
  Numbers come from SEC filings and quoted prices through a contract that
  hard-stops on stale data, never from recall. Use when the user wants to
  research a company, screen for ideas, write up an investment case, value a
  stock, ask what growth the price already assumes, work out a position size,
  challenge a thesis, or decide whether one still holds.
compatibility: claude-code opencode
allowed-tools:
  - WebSearch
  - Read
  - Write
  - Bash
---

# Investment Research

Five stages. Each hands the next a validated record rather than prose, so a name
that arrived from a screen and one that arrived from a macro view are judged by
the same standard.

| Stage | Does | Produces | Guide |
| --- | --- | --- | --- |
| 1 Intake | finds candidates, two entry paths | `Candidate` | `references/intake.md` |
| 2 Thesis | the written, falsifiable view | `Thesis` | `references/thesis.md` |
| 3 Valuation | DCF, reverse DCF, interactive page, optional dissent pass | `Valuation`, `Verdict` | `references/valuation.md` |
| 4 Portfolio | position weight from scenario probabilities | `Portfolio` | `references/portfolio.md` |
| 5 Sellcheck | what changed since the thesis was written | `Sellcheck` | `references/sellcheck.md` |

**Read the guide for the stage you are on, and only that one.** Each is a few
pages and contains the exact calls, the failure modes, and the judgment the
stage needs. Reading all five up front spends context on work you may not do.

Stages run on request, not automatically. Finishing a thesis does not mean
valuing it; the user decides what to spend time on next.

## Setup

The library lives beside this file. Put the skill directory on the path once:

```python
import sys
sys.path.insert(0, "<this skill's directory>")

from airesearch.data.adapters import configure, status_report
print(status_report(configure()))
```

That prints which data sources can run. Prices work with no configuration at
all. US filings need `sec_contact` in `config/research-profile.json` (a name and
email; SEC returns 403 without one), and the macro series need a free
`fred_api_key`. If a stage needs a source that is not configured, say which
setting is missing rather than working around it.

## Three rules that hold across every stage

**Numbers come from tools, never from recall.** Every figure passes the Fact
contract, which hard-stops on stale data and warns on unit or magnitude
anomalies:

```python
from airesearch.data.adapters import fetch
from airesearch.factcontract import verify

facts = fetch("us_equity", ticker)     # net income, D&A, capex, share count
price = fetch("price", ticker)[0]
verify(facts + [price])                # raises if anything is stale
```

Do not quote a price, a multiple, or a growth rate from memory or from an
article of unknown vintage. If a number cannot be fetched and verified, say so
instead of supplying one.

**The arithmetic is not yours to do.** DCF and position sizing live in
`airesearch.valuation`, computed in `Decimal` with guards against inputs that
produce meaningless results. Do not reproduce them mentally or check them
against your own estimate.

**Nothing here is advice.** Present what the price assumes, what you believe,
and what would prove you wrong. Do not tell the user to buy, sell, or hold.

## Output language

```python
from airesearch.config import output_language
```

Prose follows that setting. Identifiers do not: tickers, `entry_path`, scenario
names, `sizing_method`, `mode`, the leading verdict word in a sellcheck, and
provenance strings in `data_sources` are matched literally by later stages or
validated against a fixed set. Each stage guide names its own exceptions.

## Where things are stored

One SQLite file, `db/research.db`, created on first write. Records are appended
rather than overwritten: re-researching a name keeps the old thesis, revaluing
keeps the old numbers. That history is what stage 5 compares against, and it is
the only evidence of whether the falsifiers were any good.
