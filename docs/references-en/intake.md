# Stage 1 — Intake: finding candidates


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
cheap quality names in industrials"). Look for a saved criteria profile first:
apply it if there is one and record that honestly on the candidate; otherwise
run a general search with `screened=False` and an empty `profile_used`.

Do not invent a profile name to make the record look complete. `screened=False`
is an honest record; a name pointing at a profile that does not exist is not.

**Thesis-first** — the user states a view ("grid interconnect queues are the
real ceiling on AI capex") and wants the names that express it. Reason from the
thesis outward to specific tickers, using WebSearch to find who actually sits in
that value chain. This path has no fixed criteria list and is not supposed to:
the thesis is the filter.

## Saved screening criteria

```python
from airesearch.data.schema import ScreenProfile
from airesearch.data.screen_store import (
    save_screen_profile, get_screen_profile, list_screen_profiles,
    delete_screen_profile,
)

profile = get_screen_profile("quality-industrials")   # None if there is no such name
available = list_screen_profiles()                    # alphabetical; [] before any exist
```

`list_screen_profiles` raises `FileNotFoundError` before anything has ever been
saved — a fresh install has no such table. Catch it and treat it as "no profiles
yet" rather than surfacing a traceback.

Save when the user says to remember a set of criteria:

```python
save_screen_profile(ScreenProfile(
    name="quality-industrials",
    criteria={"market": "US", "sector": "industrials",
              "min_roic": 0.12, "max_net_debt_ebitda": 2.5},
    notes="industrials, judged on returns on capital and leverage, not multiple",
))
```

The keys in `criteria` are the user's own. Nothing here interprets them and
nothing checks them against a list of permitted metrics — a fixed vocabulary
would be the built-in screening checklist this pipeline promises not to impose.
So record what they said, rather than translating it into a canonical shape.

Saving under an existing name replaces it. A screen is a thing users revise — a
rule tightens, a threshold moves — and versioning that automatically would leave
`profile_used="quality-industrials"` pointing at several different sets of
criteria with no way to tell which one ran.

When a profile was applied, the candidate has to say so:

```python
candidate = Candidate(
    ..., entry_path="screen",
    source_note=profile.name,
    screened=True, profile_used=profile.name,
)
```

`screened=True` means **a written-down set of criteria was actually applied**.
Setting it after a general search makes "how did this name get here" unanswerable
months later, which is the only reason the field exists.

Deleting a profile leaves existing candidates alone: which criteria produced
which name is a historical fact, and rewriting it because the profile was later
deleted would edit the past.

## Producing the Candidate record

Build one `Candidate` per name and persist it. The dataclass in
`skills/investment-research/airesearch/data/schema.py` is the contract — it validates on construction, so
a malformed record fails here rather than three layers downstream.

```python
from airesearch.data.schema import Candidate
from airesearch.data.candidate_store import save_candidate

candidate = Candidate(
    ticker="NVDA",
    entry_path="screen",              # "screen" or "thesis"
    source_note="general search",     # or the thesis text, verbatim, if thesis-first
    market="US",                      # any market string the user's adapters support
    raw_rationale="One sentence on why this name surfaced.",
    discovered_at="2026-08-04T12:00:00Z",
)
row_id = save_candidate(candidate)    # also stamps candidate.id
```

Three fields carry more weight than they look:

- `screened=False` with an empty `profile_used` is a complete, normal record for
  a general search. It is not an unfinished one — do not invent a profile name
  to fill the gap. The reverse holds too: when a profile was applied, set both
  fields, or the screen may as well not have happened.
- `source_note` on the thesis path holds the user's thesis text verbatim. Later
  layers compare against it, so paraphrasing it loses the thing being tested.
- `id` is None until you save. After `save_candidate` it holds the row id, which
  is what `research-thesis` needs to attach its work to this candidate.

## Numbers

Any figure that reaches the user passes through the Fact contract in
`skills/investment-research/airesearch/factcontract/` first. It hard-stops on stale data and warns on
implausible units or magnitudes.

```python
from airesearch.factcontract import Fact, verify

verify([Fact(name="NVDA_chg_pct", value=-3.39, unit="pct", freq="daily",
             as_of="2026-08-04T20:15:00Z", source="sec-xbrl", entity="NVDA")])
```

Do not quote a price, a percentage, or a multiple from memory or from an article
of unknown vintage. Fetch it, declare it, verify it.

## Output

Write in the user's configured language:

```python
from airesearch.config import output_language

lang = output_language()   # "en" by default; "zh-CN", "ja", anything the model reads
```

Be exact about what that covers. Downstream layers select and compare on some of
these fields, so a translated value there does not fail loudly — it fails months
later when nothing matches.

**Translate:** your on-screen commentary and summary, and `raw_rationale`.

**Never translate:**

| Field | Why |
| --- | --- |
| `ticker` | It is an identifier, not prose |
| `market` | Adapters key off it. `"US"` stays `"US"`, never `"美股"` — nothing validates this field, so a translated value persists cleanly and then matches no adapter |
| `entry_path` | A fixed value: `"screen"` or `"thesis"`, in every language |
| `profile_used` | It names a file |
| `source_note` | On the thesis path this is the user's own words. `research-sellcheck` diffs against them later, and translation is paraphrase — it destroys the thing being tested. Keep it in whatever language they wrote it, regardless of `output_language` |

Present the candidates with their one-line rationale, and say which entry path
produced them — for screen-first, name the profile used, or say plainly that
none was configured and this was a general search.

Stop there. Deep research is `research-thesis`, a separate skill the user
invokes next; running it unasked spends their time and tokens on names they may
not want.
