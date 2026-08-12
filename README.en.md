# AI Investment Research

English · [简体中文](README.md)

An open, portable investment-research pipeline delivered as a single SKILL.md
package — not locked to Claude Code, not a hosted service. Install it into any
SKILL.md-compatible AI host, configure your own market and data access, and run
the pipeline yourself.

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

`skills/investment-research/` is self-contained: SKILL.md routes to a guide per
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

Point your host at `skills/investment-research/`, or clone and install:

```bash
git clone https://github.com/Rever3I/ai-investment-research.git
cd ai-investment-research
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
`~/.ai-investment-research/research-profile.json` for a standalone skill — and
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
| `price` | Yahoo chart, two hosts, then Stooq | nothing |
| `us_equity` | SEC EDGAR XBRL company facts | `sec_contact` |
| `macro` | FRED | `fred_api_key` (free) |
| `cn_equity` | Eastmoney public endpoints, then Wind | nothing |

```python
from airesearch.data.adapters import configure, fetch, status_report

print(status_report(configure()))     # what is wired up and what can run
facts = fetch("us_equity", "KO")      # net income, D&A, capex, share count
```

Prices work with no configuration at all, which is the case that matters on a
fresh clone, and so do Chinese listings: `cn_equity` reads Eastmoney's public
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
