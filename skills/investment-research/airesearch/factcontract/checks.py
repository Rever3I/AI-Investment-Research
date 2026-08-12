#!/usr/bin/env python
"""The three checkers plus verify(), the adjudication entry point.

Severity is deliberately uneven:
    staleness   -> hard stop (raises FactCheckError)
    freq_align  -> warning
    magnitude   -> warning

Warnings get ignored; hard stops do not. Stale data is the failure mode that
actually burns you, so it is the one that has to be able to halt the pipeline.

Usage:
    from airesearch.factcontract import Fact, verify
    report = verify([f1, f2])                        # raises if anything is stale
    report = verify(facts, raise_on_error=False)     # adjudicate without halting
"""

import logging
from collections import defaultdict
from datetime import datetime
from statistics import median

from .fact import (
    CLOCK_SKEW_TOLERANCE,
    JUMP_MIN_HISTORY,
    JUMP_RATIO_THRESHOLD,
    MAGNITUDE_RANGES,
    STALENESS_LIMITS,
    Fact,
    now_utc,
)

_log = logging.getLogger(__name__)


class FactCheckError(Exception):
    """Hard stop: at least one Fact failed an error-level check."""

    def __init__(self, errors):
        self.errors = errors
        lines = "\n".join(f"  - [{e['check']}] {e['fact']}: {e['message']}" for e in errors)
        super().__init__(f"Fact check failed ({len(errors)} hard stops):\n{lines}")


def _issue(level, check, fact, message, **extra):
    d = {
        "level": level,
        "check": check,
        "fact": fact.name,
        "entity": fact.entity,
        "value": fact.value,
        "message": message,
    }
    d.update(extra)
    return d


# ══════════════════════════════════════════════════════════════════
#  check 1: staleness -- hard stop
# ══════════════════════════════════════════════════════════════════

def check_staleness(facts, ref: datetime = None):
    """No Fact may be older than its frequency allows.

    This is the guard against quoting an old number as current: a move copied
    from a days-old article and presented as today's is the canonical way a
    research pipeline loses credibility.
    """
    ref = ref or now_utc()
    issues = []
    for f in facts:
        limit = STALENESS_LIMITS.get(f.freq)
        if limit is None:
            continue
        age = f.age_seconds(ref)
        if age < -CLOCK_SKEW_TOLERANCE:
            # Far in the future is a timezone mistake, and it should not pass
            # just because it is not old. A few minutes ahead is clock skew
            # between the provider and this machine, which would otherwise
            # hard-stop on a quote fetched this second.
            issues.append(_issue(
                "error", "staleness", f,
                f"as_of is {abs(age)/3600:.1f} hours in the future "
                f"(as_of={f.as_of}), check the timezone",
                age_seconds=age, limit_seconds=limit,
            ))
            continue
        if age > limit:
            issues.append(_issue(
                "error", "staleness", f,
                f"data is {_human(age)} old (freq={f.freq} allows {_human(limit)}, "
                f"as_of={f.as_of}, source={f.source})",
                age_seconds=round(age), limit_seconds=limit,
            ))
    return issues


def _human(seconds: float) -> str:
    seconds = float(seconds)
    if seconds < 3600:
        return f"{seconds/60:.0f} minutes"
    if seconds < 86400:
        return f"{seconds/3600:.1f} hours"
    return f"{seconds/86400:.1f} days"


# ══════════════════════════════════════════════════════════════════
#  check 2: freq_align -- warning
# ══════════════════════════════════════════════════════════════════

def check_freq_align(facts):
    """Facts in the same group must share a frequency.

    This catches the most common valuation error there is: a numerator taken
    from one quarter divided by a denominator taken from the trailing twelve
    months. Facts with no group are exempt, because the caller declares the
    relationship rather than the checker guessing at it.
    """
    groups = defaultdict(list)
    for f in facts:
        if f.group:
            groups[f.group].append(f)

    issues = []
    for gname, members in groups.items():
        freqs = {f.freq for f in members}
        if len(freqs) <= 1:
            continue
        # The minority frequency is the more likely mistake.
        counts = defaultdict(list)
        for f in members:
            counts[f.freq].append(f)
        majority = max(counts, key=lambda k: len(counts[k]))
        for freq, offenders in counts.items():
            if freq == majority:
                continue
            for f in offenders:
                issues.append(_issue(
                    "warning", "freq_align", f,
                    f"group '{gname}' mixes frequencies: this Fact is {freq}, "
                    f"most of the group is {majority}, one formula cannot span frequencies",
                    group=gname, group_freqs=sorted(freqs),
                ))
    return issues


# ══════════════════════════════════════════════════════════════════
#  check 3: magnitude -- warning
# ══════════════════════════════════════════════════════════════════

def check_magnitude(facts, history_fn=None):
    """Two passes: an absolute range per unit, and a jump against own history.

    history_fn(name, entity) -> [float, ...] supplies past values, normally from
    the store. Passing None runs the absolute check only. The jump baseline is a
    median so a single outlier cannot move it.
    """
    issues = []
    for f in facts:
        lo, hi = MAGNITUDE_RANGES.get(f.unit, (None, None))
        av = abs(f.value)
        if hi is not None and av > hi:
            issues.append(_issue(
                "warning", "magnitude", f,
                f"absolute value {av:g} exceeds the plausible ceiling {hi:g} for "
                f"unit={f.unit}, likely a unit error or the wrong field",
                bound="upper", limit=hi,
            ))
        elif lo is not None and av != 0 and av < lo:
            issues.append(_issue(
                "warning", "magnitude", f,
                f"absolute value {av:g} is below the plausible floor {lo:g} for "
                f"unit={f.unit}, check the scaling",
                bound="lower", limit=lo,
            ))

        if history_fn is None:
            continue
        try:
            hist = [abs(v) for v in (history_fn(f.name, f.entity) or []) if v is not None]
        except Exception:
            _log.warning("Fact history lookup failed for %s, "
                         "jump detection skipped for this Fact", f.name, exc_info=True)
            hist = []
        hist = [v for v in hist if v > 0]
        if len(hist) < JUMP_MIN_HISTORY:
            continue
        base = median(hist)
        if base <= 0:
            continue
        if av > base * JUMP_RATIO_THRESHOLD:
            issues.append(_issue(
                "warning", "magnitude", f,
                f"jumped {av/base:.1f}x against its own history "
                f"(median {base:g}, n={len(hist)}), past the {JUMP_RATIO_THRESHOLD:g}x threshold",
                jump_ratio=round(av / base, 2), history_median=base, history_n=len(hist),
            ))
    return issues


# ══════════════════════════════════════════════════════════════════
#  verify -- adjudication entry point
# ══════════════════════════════════════════════════════════════════

def verify(facts, raise_on_error=True, record=True, ref=None):
    """Run every check and return the adjudication report.

    facts           Facts, or dicts that convert to them
    raise_on_error  raise FactCheckError when any error-level issue is found
    record          persist passing Facts to the fact_log, which is what grows
                    the magnitude baseline over time
    ref             comparison time, for tests

    Returns {"ok", "errors", "warnings", "checked", "facts"}
    """
    facts = [f if isinstance(f, Fact) else Fact.from_dict(f) for f in facts]

    # The store is an optional dependency. If it cannot be reached, degrade to
    # absolute-range checking rather than letting a storage problem take down
    # verification itself.
    try:
        from . import store as _store
        store = _store
        history_fn = _store.history
    except Exception:
        _log.warning("Fact store unavailable, magnitude jump detection disabled",
                     exc_info=True)
        store = None
        history_fn = None

    issues = []
    issues += check_staleness(facts, ref=ref)
    issues += check_freq_align(facts)
    issues += check_magnitude(facts, history_fn=history_fn)

    errors = [i for i in issues if i["level"] == "error"]
    warnings = [i for i in issues if i["level"] == "warning"]

    # Only record Facts that cleared the hard stop: stale data must not pollute
    # the baseline that magnitude checking is judged against.
    if record and store is not None:
        bad = {i["fact"] for i in errors}
        keepers = [f for f in facts if f.name not in bad]
        if keepers and store.record_many(keepers) == 0:
            _log.warning("Fact store accepted no rows, the magnitude baseline "
                         "is not being updated")

    report = {
        "ok": not errors,
        "checked": len(facts),
        "errors": errors,
        "warnings": warnings,
        "facts": [f.to_dict() for f in facts],
    }
    if errors and raise_on_error:
        raise FactCheckError(errors)
    return report


def format_report(report) -> str:
    """Render an adjudication report for a human.

    ASCII only, deliberately: this gets printed to whatever console the host
    happens to have, and a non-UTF-8 Windows terminal raises UnicodeEncodeError
    on emoji, which would turn the verifier itself into the crash.
    """
    lines = []
    n, ne, nw = report["checked"], len(report["errors"]), len(report["warnings"])
    if report["ok"] and not nw:
        head = "[OK] all clear"
    elif ne:
        head = "[STOP] hard stops present"
    else:
        head = "[WARN] warnings present"
    lines.append(f"{head} - checked {n}, hard stops {ne}, warnings {nw}")
    for i in report["errors"]:
        lines.append(f"  [STOP] [{i['check']}] {i['fact']} = {i['value']}: {i['message']}")
    for i in report["warnings"]:
        lines.append(f"  [WARN] [{i['check']}] {i['fact']} = {i['value']}: {i['message']}")
    return "\n".join(lines)
