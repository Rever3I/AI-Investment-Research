# Stage 5 — Sellcheck: what changed since you bought


Runs when the user is thinking about selling. There is deliberately no monitor
behind it — no polling, no alerts, no scheduled scan. Continuous monitoring was
considered and dropped: it produces a stream of notifications that trains you to
ignore it, and the moment that matters is the one where you are already
reconsidering.

## The question it answers

Not "should I sell". That is the user's call and this layer does not make it.

The question is **which of three things happened**, because the right response
to each is different and they are easy to confuse in the moment:

`facts_changed` — the world moved against the argument. A falsifier fired, a
number that the thesis depended on came in differently, a competitor did
something the thesis said they could not. This is the case where selling is a
decision the original reasoning supports.

`judgment_changed` — the facts are roughly as expected and you now read them
differently. Sometimes that is learning. Sometimes it is the price moving and
the story rearranging itself to fit. Worth naming as what it is, because the two
feel identical from inside.

`still_holds` — nothing material moved. The position is uncomfortable rather
than broken. Say so plainly; discomfort is not information.

## Reading the original argument

```python
from airesearch.data.thesis_store import get_thesis, get_thesis_for_candidate
from airesearch.data.sellcheck_store import list_sellchecks_for_thesis

thesis = get_thesis(thesis_id)
history = list_sellchecks_for_thesis(thesis.id)   # earlier rechecks, newest first
```

Read the earlier rechecks before writing a new one. A thesis rechecked three
times, each drifting a little further from the original argument, is a different
situation from one that failed today — and only the history shows that.

## The comparison

Work through the thesis as written, section by section, and for each say what is
now true and whether it differs:

1. **The falsifiers first.** They were written precisely so this moment would be
   simple. Has any of them fired? A falsifier that fired and was then argued
   around is the single most important thing to report.
2. **The variant perception.** Is the thing the market was supposedly missing
   still missing, or is it now priced? A thesis whose edge has been recognised
   has succeeded, not failed, and that is a different reason to sell.
3. **The risks.** Which of the ones listed have materialised, and which of the
   ones that hurt were never on the list? The second group is the more useful
   finding — it says something about how the thesis was constructed.
4. **The numbers.** Re-pull what the argument rested on. Every figure passes the
   Fact contract; a comparison against a remembered number is not a comparison.

## Saving

```python
from airesearch.data.schema import Sellcheck
from airesearch.data.sellcheck_store import save_sellcheck

sellcheck = Sellcheck(
    thesis_id=thesis.id,
    trigger="user_initiated",
    diff_summary="facts_changed: export licence revoked; the TAM assumption "
                 "the thesis rested on no longer applies.",
    rechecked_at=today_iso,
)
row_id = save_sellcheck(sellcheck)
```

Start `diff_summary` with one of `facts_changed`, `judgment_changed` or
`still_holds`, then say what specifically. The leading word is what makes a
sequence of rechecks readable later; the detail is what makes each one useful.

Every recheck is kept. Over time the sequence is the only evidence of whether
the falsifiers were any good, which is how the next thesis gets written better.

## Output language

Follow `output_language()` for the prose. Do not translate the leading verdict
word in `diff_summary` — `facts_changed` / `judgment_changed` / `still_holds`
are the tokens that make the history scannable across languages.

## Finishing

Lead with which of the three it is and the evidence for it. Then the falsifier
status, then what changed that nobody had listed.

Do not recommend selling or holding. Present what moved and what did not; the
decision, and the position, are the user's.
