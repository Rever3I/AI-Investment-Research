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
4. **research-debate** — optional dissent/risk layer, produces a `Verdict` record
5. **research-portfolio** — position sizing (half-Kelly default), produces a `Portfolio` record
6. **research-sellcheck** — on-demand thesis-drift check at sell time, produces a `Sellcheck` record

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
  "debate_enabled": false
}
```

- `output_language` — **the language your research is written in** (thesis prose,
  valuation commentary, conclusions). Set it to `zh-CN` and the same code
  produces Chinese reports; any language tag works, there is no whitelist. It
  does not change the code's own logs and error messages, which stay English so
  a traceback is searchable by anyone.
- `sizing_method` — `half_kelly`, `full_kelly`, `fixed_pct`, or `custom` (read by
  research-portfolio, which ships later)
- `debate_enabled` — whether the optional dissent layer participates (read by
  research-debate, which ships later)

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

Built: shared record schemas, SQLite storage with enforced referential
integrity, the Fact contract, and the `research-intake` and `research-thesis`
layers. Valuation and everything downstream, plus the market data adapters
(SEC EDGAR, Wind, FRED, news/alt-data), land in subsequent releases. Saved
screening profiles are specified but not yet implemented — intake currently runs
a general search.
