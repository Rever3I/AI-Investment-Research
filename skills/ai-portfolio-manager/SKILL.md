---
name: ai-portfolio-manager
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

# AI Portfolio Manager

The research work a portfolio manager does, in five stages: find the name, write
the argument, value it, size it, and check what changed before selling. It does
not decide for you and it does not place trades.

Delivered as a single SKILL.md package. Not locked to one host, not a hosted
service: install it into any tool that reads SKILL.md, point it at your own
market and data access, and run it yourself.

Each stage hands the next a validated record rather than prose, so a name that
arrived from a screen and one that arrived from a macro view are judged by the
same standard.

| Stage | Does | Produces | Guide |
| --- | --- | --- | --- |
| Intake | screens on your own saved criteria, or reasons from a view you hold to the names that express it | `Candidate` | `references/intake.md` |
| Thesis | the written, falsifiable view: business, management, competitors, TAM, 8-12 risks, and what would prove it wrong | `Thesis` | `references/thesis.md` |
| Valuation | owner-earnings DCF, reverse DCF, a self-contained interactive page, optional dissent pass | `Valuation`, `Verdict` | `references/valuation.md` |
| Portfolio | position weight from your scenario probabilities, half-Kelly by default | `Portfolio` | `references/portfolio.md` |
| Sellcheck | diffs today against the thesis you wrote, so a price move is not mistaken for a broken argument | `Sellcheck` | `references/sellcheck.md` |

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

from airesearch.config import ensure_profile
from airesearch.data.adapters import configure, status_report

print(ensure_profile())                 # creates the settings file on first run
print(status_report(configure()))
```

That prints which data sources can run. Prices work with no configuration at
all. US filings need `sec_contact` (a name and email; SEC returns 403 without
one), and the macro series need a free `fred_api_key`. Chinese listings need
nothing configured.

Settings live in a JSON profile. `ensure_profile()` writes it with the defaults
the first time it is called and returns the path; if the file is already there
it is returned untouched. `load_profile()` shows what is in effect.

Where that path is depends on the install: `config/research-profile.json` in a
source checkout, `~/.ai-portfolio-manager/research-profile.json` for a
standalone skill. **Always report the path `ensure_profile()` returns rather
than composing one** — settings written to the other location are simply never
read, and the run then fails on a 403 that looks like a network problem.
`AI_RESEARCH_PROFILE` overrides both.

If a stage needs a source that is not configured, say which setting is missing,
and print `profile_path()` so the user knows where to put it.

Four domains. The name is the first argument to `fetch(domain, key)`:

| Domain | Source | Needs |
| --- | --- | --- |
| `price` | Yahoo (two hosts), then Tencent, then Stooq | nothing |
| `us_equity` | SEC EDGAR XBRL company facts | `sec_contact` |
| `macro` | FRED | `fred_api_key` (free) |
| `cn_equity` | Eastmoney public endpoints, then Wind | nothing |

Each domain is a chain: when the first source fails the next is tried and the
fallback is logged.

## Three rules that hold across every stage

**Numbers come from tools, never from recall.** Every figure that reaches an
output passes the Fact contract in `airesearch/factcontract/`. Two things hard-
stop it: data past its staleness limit, and one company's money arriving in two
currencies. Unit and magnitude anomalies warn. A non-dollar listing is not
refused — a yuan price against yuan financials values fine:

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
