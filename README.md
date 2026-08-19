# Agentic Stock Researcher

English · [简体中文](README.zh-CN.md)

An open, portable buy-side research pipeline delivered as a single SKILL.md
package — not locked to Claude Code, not a hosted service. Install it into any
SKILL.md-compatible AI host, configure your own market and data access, and run
the pipeline yourself.

## A real run

Coca-Cola, figures pulled live from SEC EDGAR:

```
Owner earnings   $12.0B      net income + D&A - capex, FY2025 10-K
Shares           4.31B       CommonStockSharesOutstanding
Price            $86.84      Yahoo, verified fresh

Reverse DCF      19.7%       the growth this price already assumes,
                             at a 9.2% discount rate and 2.6% terminal growth

Scenarios        bull $54.24   base $47.96   bear $40.61
Half-Kelly       0.00%       no edge at this price
```

Kweichow Moutai, from Eastmoney, with no key configured: owner earnings
CNY 83.3bn, CNY 66.6 a share, and a CNY 1,343 quote implying 6.8% a year for a
decade.

Read the reverse DCF first. It turns "is this cheap" into a question you can
actually answer: is a soft drinks company going to compound owner earnings at
19.7% a year for ten years? The scenario values follow from your growth
assumptions, not from the tool's.

## Why this one

Four things go wrong with LLM stock tools. They are the complaints sitting in
the issue trackers of the popular repos in this space, and each has a specific
answer here.

**The same run reports different fundamentals in different places.** One agent's
D/E disagrees with another's, in a single run, on one company. Here a figure is
fetched once and declared as a `Fact` carrying its source, unit and as-of date,
and the figures feeding one calculation share a `group`, so a quarterly
numerator over a trailing-twelve-month denominator is caught instead of
averaged over.

**Rerunning the same inputs gives a different answer.** Same ticker, same date,
same model, new rating. Nothing here asks a model to do arithmetic: the DCF, the
reverse DCF and the Kelly solver are deterministic `Decimal` code, and every
record is appended to SQLite rather than overwritten, so two runs are comparable
and a changed answer has a cause you can point at.

**Setup is a project in itself.** Conda environments, a data-vendor key, an LLM
key, a `.env` copied from a wiki. This has no pip dependencies at all — Python
3.10 and the standard library. Quotes and Chinese filings need no key of any
kind; US filings need a contact email because the SEC requires one.

**The data is wrong in ways that look completely normal.** This is the one
nobody goes looking for, and it is where most of the work went. Reading XBRL and
free endpoints naively produces figures that pass every sanity check and are
still wrong. Each of these was found against live filings and is now blocked by
a rule:

| Company | Naive result | Actual | Cause |
| --- | --- | --- | --- |
| Simon Property | 1.30B shares | 324M | Weighted-average counts are filed as period entries, so four quarters got summed |
| McDonald's | 716 shares | 708M | The count is filed in millions |
| Starbucks | D&A $362M | $1.77B | A fresher single quarter beat the annual figure, and the company then showed no owner earnings at all |
| Shell (London) | $3,356 | ~$45 | London quotes in pence, and the price was labelled dollars |
| NVIDIA | Capex from 2020 | Current | The tag NVIDIA used until 2020 still won over the one it uses now |
| Kweichow Moutai | D&A CNY 366M | CNY 4.15B | Depreciation is split across six fields and companies file different subsets |

A summed share count is still a plausible share count. A quarterly depreciation
figure is still a plausible depreciation figure. None of these fails a sanity
check, so each needed a rule and a regression test rather than a warning.

## What it refuses to do

Refusing is a feature. Each of these would otherwise produce a confident number
that means nothing.

- **Banks, insurers and most REITs.** Owner earnings is net income plus
  depreciation less capex, and they often have no capex line. A missing term
  reads as zero and flatters exactly the businesses where capital matters most.
- **Loss-making companies.** The arithmetic returns a negative price target with
  an ordinary-looking terminal share hiding two negatives in a ratio.
- **One company in two currencies.** A yuan price against dollar financials is
  wrong by an exchange rate and every digit of it looks fine.
- **Listings quoted in a subunit.** London quotes in pence; the currency label
  is right and only the unit is wrong, which is why no later check can see it.
- **A position with no edge.** When expected return is not positive at the
  current price, Kelly sizes at zero. That is the arithmetic declining the bet.

## What it does

One skill, five stages. Each hands the next a validated record rather than
prose, so a name that arrived from a quantitative screen and one that arrived
from a macro view are judged by the same standard.

| Stage | Does | Produces |
| --- | --- | --- |
| Intake | finds candidates from a screen or from a thesis | `Candidate` |
| Thesis | the written, falsifiable view | `Thesis` |
| Valuation | DCF, reverse DCF, interactive page, optional dissent pass | `Valuation`, `Verdict` |
| Portfolio | position weight from scenario probabilities | `Portfolio` |
| Sellcheck | what changed since the thesis was written | `Sellcheck` |

`skills/agentic-stock-researcher/` is self-contained: SKILL.md routes to a guide per
stage, and the Python library sits beside them. Copying that one directory into
a host gives a working install.

## Design principles

- **Numbers come from tools, not from the model.** Any figure that reaches an
  output passes through the Fact contract in `airesearch/factcontract/`, which
  hard-stops on stale data and on one company's money arriving in two
  currencies, and warns on unit or magnitude anomalies. A non-dollar listing is
  not refused: a yuan price against yuan financials values fine.
- **No opinionated defaults.** There is no built-in screening checklist and no
  mandatory committee. You configure the criteria you want and save them; until
  you do, intake is a general open search.
- **Pure stdlib.** No pip dependencies, so it runs wherever Python 3.10+ does.

## Installing

Point your host at `skills/agentic-stock-researcher/`, or clone and install:

```bash
git clone https://github.com/Rever3I/agentic-stock-researcher.git
cd agentic-stock-researcher
pip install -e .
```

The skill directory carries its own library, so copying it alone is enough. If
your host does not put the skill directory on `sys.path`, SKILL.md shows the one
line that does.

Records land in `db/research.db`, created on first write. Set `AI_RESEARCH_DB`
to put it somewhere else.

## Configuration

`config/research-profile.json`:

```json
{
  "output_language": "en",
  "sizing_method": "half_kelly",
  "fixed_pct": 0.05,
  "debate_enabled": false,
  "sec_contact": "",
  "fred_api_key": "",
  "position_cap": 1.0
}
```

- `output_language` — **the language your research is written in** (thesis prose,
  valuation commentary, conclusions). Set it to `zh-CN` and the same code
  produces Chinese reports; any language tag works, there is no whitelist. It
  does not change the code's own logs and error messages, which stay English so
  a traceback is searchable by anyone.
- `sizing_method` — `half_kelly`, `full_kelly`, `fixed_pct`, or `custom`
- `fixed_pct` — the weight used when `sizing_method` is `fixed_pct`, as a
  fraction of capital. `custom` takes its weight from the caller instead
- `debate_enabled` — whether the optional dissent layer participates
- `sec_contact` — a name and email, e.g. `"Jane Roe jane@example.com"`. SEC
  requires it in the User-Agent and returns 403 without one, so US filings have
  no source until it is set
- `fred_api_key` — a free key from
  [FRED](https://fredaccount.stlouisfed.org/apikeys), for the macro series that
  give a discount rate its provenance
- `position_cap` — concentration ceiling as a fraction of capital, applied after
  sizing. Kelly knows nothing about the rest of a portfolio; `1.0` is no ceiling

JSON rather than YAML: this project ships no third-party dependencies, and the
standard library has no YAML parser.

`ensure_profile()` writes this file with the defaults the first time it is
called and returns its path; call it before reading a setting and report the
path it gives you. Where that path is depends on the install —
`config/research-profile.json` in a checkout,
`~/.agentic-stock-researcher/research-profile.json` for a standalone skill — and
settings written to the other one are simply never read.

Point `AI_RESEARCH_PROFILE` at a different file to use another profile. Every
setting has a working default, so a missing, partial, or even damaged file falls
back with a warning rather than stopping the pipeline.

## Running the tests

```bash
python -m pytest -q
```

## Status

All five stages are built, along with the foundation they share: record schemas,
SQLite storage with enforced referential integrity, the Fact contract, a Decimal
owner-earnings DCF with reverse-DCF and scenarios, and a Kelly sizing solver
that handles multi-outcome distributions rather than only the binary case.

## Data sources

Adapters return `Fact` objects rather than bare numbers, so a figure cannot
reach a valuation without a source, a unit and an as-of time attached. Each
domain is a chain: if the first source fails, the next is tried and the fallback
is logged, because a primary that quietly always fails looks identical to one
that works.

| Domain | Source | Needs |
| --- | --- | --- |
| `price` | Yahoo, two hosts, then Tencent, then Stooq | nothing |
| `us_equity` | SEC EDGAR XBRL company facts | `sec_contact` |
| `macro` | FRED | `fred_api_key` (free) |
| `cn_equity` | Eastmoney public endpoints, then Wind | nothing |

```python
from airesearch.data.adapters import configure, fetch, status_report

print(status_report(configure()))     # what is wired up and what can run
facts = fetch("us_equity", "KO")      # net income, D&A, capex, share count
```

Prices work with no configuration at all, which is the case that matters on a
fresh clone, and two of the entries fail independently: Tencent answered
throughout the hours Eastmoney's quote endpoint was returning 502. Chinese
listings need no configuration either: `cn_equity` reads Eastmoney's public
endpoints, unofficial and undocumented in the same way the Yahoo quote endpoint
is, so the parser fails loudly rather than returning something plausible. Wind
sits behind it for anyone who has a terminal. That adapter is written to Wind's
documented interface but **has not been verified against a live terminal** —
WindPy ships with the paid product and cannot be installed otherwise.

Screening criteria can be saved and reused: `airesearch.data.screen_store`
keeps named profiles, and a candidate produced by one carries
`screened=True` and the profile name. With nothing saved, intake runs a
general open search — still the default, not a missing piece.

## Licence

[MIT](LICENSE). Use it, change it, ship it, sell it; keep the copyright notice.
Provided as is, with no warranty of any kind — including for any number it
produces.
