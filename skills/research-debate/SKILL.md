---
name: research-debate
description: >
  An optional layer that puts a valued thesis under adversarial pressure before
  it becomes a position, and records what the pressure did not resolve. Runs as
  a structured checklist by default, or as a panel of named investor voices if
  the user chose that at setup. Use when the user wants a thesis challenged,
  stress-tested, argued against, or reviewed by a committee before sizing.
compatibility: claude-code opencode
allowed-tools:
  - WebSearch
  - Read
  - Write
  - Bash
---

# Research Debate (Layer 5, optional)

The one layer that does not have to run. Whether it does, and in what form, is
the user's choice in `config/research-profile.json`:

```python
from skills._lib.config import load_profile

profile = load_profile()
if not profile["debate_enabled"]:
    ...   # skip; go straight to research-portfolio
```

If `debate_enabled` is false and the user did not ask for this explicitly, say
so once and move on. Do not run it anyway because it seems thorough — a layer
the user switched off is a layer they decided the cost of.

## What this layer is for

Not to reach a conclusion. `research-valuation` already produced numbers and
`research-portfolio` will size them; a committee that merely restates the base
case adds ceremony and no information.

What it produces that nothing else does is the **dissent map**: the arguments
that survived contact with each other and were still not resolved, each tagged
with what would settle it. That is the part worth reading in a year, because it
names in advance where the thesis was fragile.

Preserving disagreement is the point. A layer that averages three views into one
verdict has destroyed the only output the reader could not have written
themselves.

## Two modes

`mode="checklist"` — the default, and what runs unless the user picked
otherwise. One analytical voice working through the pressure points:

- Which claim in the thesis is doing the most work, and what happens if it is
  wrong?
- What does the bear case need to be true, and how would you know early?
- Which falsifier from the thesis is closest to firing right now?
- Where does the valuation's terminal share sit, and does the story justify it?
- What would someone who has held the other side of this trade for a year say?

`mode="persona_debate"` — a panel of named investor voices, if the user chose it
at setup. Each voice argues from its own discipline rather than performing a
personality: a quality-and-moat voice, a margin-of-safety voice, a
what-am-I-missing voice, a macro-regime voice. Two rounds is usually enough —
one to state positions, one to respond to the strongest objection raised against
them.

Whichever mode runs, the useful output is the same: where the voices agreed,
where they did not, and what evidence would move each unresolved point.

## Reading the inputs

```python
from skills._lib.data.thesis_store import get_thesis
from skills._lib.data.valuation_store import get_valuation

valuation = get_valuation(valuation_id)
thesis = get_thesis(valuation.thesis_id)
```

Both raise `FileNotFoundError` on a fresh install. Catch it and say which layer
to run first.

## Numbers

Any figure introduced during the debate goes through the Fact contract like
every other number in this pipeline. A bear case built on a remembered
percentage is not a bear case, it is a mood.

## Saving

```python
from skills._lib.data.schema import Verdict
from skills._lib.data.verdict_store import save_verdict

verdict = Verdict(
    valuation_id=valuation.id,
    mode="checklist",                      # or "persona_debate"
    votes=[{"voice": "...", "call": "...", "why": "..."}],
    dissent_map="What was not resolved, and what would settle each point.",
    authored_at=today_iso,
)
row_id = save_verdict(verdict)
```

`votes` may be empty in checklist mode. `dissent_map` should not be — "no
unresolved disagreement" is itself a finding worth stating explicitly, and an
empty string reads as an omission rather than a conclusion.

## Output language

Follow `output_language()` for the prose, including the dissent map and each
vote's reasoning. Do not translate `mode` — it is `"checklist"` or
`"persona_debate"`, and the record validates against those exact values.

## Finishing

Lead with what was not resolved, not with the verdict. Report the row id, and
stop — sizing is `research-portfolio`.

Do not turn the dissent into a recommendation to buy or sell. The layer's job is
to make the disagreement legible; deciding is the user's.
