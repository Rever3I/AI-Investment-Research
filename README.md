# AI Investment Research

English · [简体中文](README.zh-CN.md)

An open, portable investment-research pipeline delivered as SKILL.md packages —
not locked to Claude Code, not a hosted service. Install the skills into any
SKILL.md-compatible AI host, configure your own market/data access, and run
the pipeline yourself.

## Layers

1. **research-intake** — dual entry (screen-first / thesis-first), produces a `Candidate` record
2. **research-thesis** — deep-dive research, produces a `Thesis` record
3. **research-valuation** — DCF/comps/scenarios, produces a `Valuation` record + interactive HTML
   Its optional dissent pass puts the thesis under pressure and records what it
   did not resolve, as a `Verdict`
4. **research-portfolio** — position sizing (half-Kelly default), produces a `Portfolio` record
5. **research-sellcheck** — on-demand thesis-drift check at sell time, produces a `Sellcheck` record

Every layer hands the next one a validated record rather than prose, so the
pipeline works the same whether a candidate arrived from a quantitative screen
or from a macro thesis.

## Design principles

- **Numbers come from tools, not from the model.** Any figure that reaches an
  output passes through the Fact contract in `skills/_lib/factcontract/`, which
  hard-stops on stale data and warns on unit or magnitude anomalies.
- **No opinionated defaults.** There is no built-in screening checklist and no
  mandatory committee. You configure the criteria you want and save them; until
  you do, intake is a general open search.
- **Pure stdlib.** No pip dependencies, so the skills run wherever Python 3.10+ does.

## Installing

The skills import a shared library (`skills/_lib/`), so the repo root has to be
importable wherever your AI host runs Python. Clone it and install in place:

```bash
git clone https://github.com/Rever3I/ai-investment-research.git
cd ai-investment-research
pip install -e .
```

Copying a single `skills/<layer>/` directory into a host's skills folder is not
enough on its own — the layer's code refers to `skills._lib`, which has to come
along. Point your host at this repo, or install it as above.

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

Point `AI_RESEARCH_PROFILE` at a different file to use another profile. Every
setting has a working default, so a missing, partial, or even damaged file falls
back with a warning rather than stopping the pipeline.

## Running the tests

```bash
python -m pytest -q
```

## Status

All six layers are built, along with the foundation they share: record
schemas, SQLite storage with enforced referential integrity, the Fact contract,
a Decimal owner-earnings DCF with reverse-DCF and scenarios, and a Kelly sizing
solver that handles multi-outcome distributions rather than only the binary
case.

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
| `cn_equity` | Wind | a licensed Wind terminal |

```python
from skills._lib.data.adapters import configure, fetch, status_report

print(status_report(configure()))     # what is wired up and what can run
facts = fetch("us_equity", "KO")      # net income, D&A, capex, share count
```

Prices work with no configuration at all, which is the case that matters on a
fresh clone. The Wind adapter is written to Wind's documented interface but
**has not been verified against a live terminal** — WindPy ships with the paid
product and cannot be installed otherwise. Treat it as a starting point.

Saved screening profiles are specified but not yet implemented — intake runs a
general search.
