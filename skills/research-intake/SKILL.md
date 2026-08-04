---
name: research-intake
description: >
  Dual-entry candidate discovery for investment research — either screen-first
  (narrow a universe using saved, user-defined criteria) or thesis-first (start
  from a macro or structural view and find the tickers that express it). Both
  paths converge on a single Candidate record that feeds the rest of the
  pipeline. Use when the user wants to find stock ideas, screen for candidates,
  or work out which tickers express a market view they hold.
compatibility: claude-code opencode
allowed-tools:
  - WebSearch
  - Read
  - Write
  - Bash
---

# Research Intake (Layer 1-2)

The entry point of the pipeline. Whatever route a name arrives by, it leaves
here as a `Candidate` record, so everything downstream judges screen-sourced and
thesis-sourced ideas by the same standard.

## Default behaviour: general open search

There is no built-in screening checklist, no red lines, no quality scorecard.
Unless the user has saved their own criteria profile, run an open exploratory
search guided by what they actually asked for.

This is a deliberate design choice. Applying an opinionated filter the user
never configured would silently drop names for reasons they cannot see. If you
find yourself about to reject a candidate on a rule nobody set, stop — surface
the observation to the user instead and let them decide whether it becomes a
saved criterion.

## The two entry paths

**Screen-first** — the user wants candidates out of a universe ("find me some
cheap quality names in industrials"). Check `config/screen-profiles/` for a
saved profile. If one applies, use it and record which. If the directory is
empty, search generally and mention once, without nagging: they can save a
criteria profile any time, and until then this is a general search.

**Thesis-first** — the user states a view ("grid interconnect queues are the
real ceiling on AI capex") and wants the names that express it. Reason from the
thesis outward to specific tickers, using WebSearch to find who actually sits in
that value chain. This path has no fixed criteria list and is not supposed to:
the thesis is the filter.

## Producing the Candidate record

Build one `Candidate` per name and persist it. The dataclass in
`skills/_lib/data/schema.py` is the contract — it validates on construction, so
a malformed record fails here rather than three layers downstream.

```python
from skills._lib.data.schema import Candidate
from skills._lib.data.candidate_store import save_candidate

candidate = Candidate(
    ticker="NVDA",
    entry_path="screen",              # "screen" or "thesis"
    source_note="deep-value profile", # or the thesis text, verbatim, if thesis-first
    market="US",                      # "US" or "CN"
    raw_rationale="One sentence on why this name surfaced.",
    discovered_at="2026-08-04T12:00:00Z",
    screened=True,                    # True only if a saved profile was applied
    profile_used="deep-value",        # the profile name, else ""
)
row_id = save_candidate(candidate)
```

Two fields carry more weight than they look:

- `screened=False` with an empty `profile_used` is a complete, normal record for
  a general search. It is not an unfinished one — do not invent a profile name
  to fill the gap.
- `source_note` on the thesis path holds the user's thesis text verbatim. Later
  layers compare against it, so paraphrasing it loses the thing being tested.

## Numbers

Any figure that reaches the user passes through the Fact contract in
`skills/_lib/factcontract/` first. It hard-stops on stale data and warns on
implausible units or magnitudes.

```python
from skills._lib.factcontract import Fact, verify

verify([Fact(name="NVDA_chg_pct", value=-3.39, unit="pct", freq="daily",
             as_of="2026-08-04T20:15:00Z", source="yfinance", entity="NVDA")])
```

Do not quote a price, a percentage, or a multiple from memory or from an article
of unknown vintage. Fetch it, declare it, verify it.

## Output

Present the candidates with their one-line rationale, and say which entry path
produced them — for screen-first, name the profile used, or say plainly that
none was configured and this was a general search.

Stop there. Deep research is `research-thesis`, a separate skill the user
invokes next; running it unasked spends their time and tokens on names they may
not want.
