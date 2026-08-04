# AI Investment Research

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

## Status

Foundation build: shared record schemas, SQLite storage, the Fact contract, and
the `research-intake` layer. The remaining layers and the market data adapters
(SEC EDGAR, Wind, FRED, news/alt-data) land in subsequent releases.

## Running the tests

```bash
python -m pytest tests/ -v
```
