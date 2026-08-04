#!/usr/bin/env python
"""Fact — the input contract for the numeric adjudication layer.

Any number headed for a report, a post, or a model has to be declared as a Fact
before it can be verified. A bare float cannot get in, and that refusal is
itself the first gate: a figure with no stated source, unit, or as-of time is
not a figure anyone should act on.

Design principles:
  - Pure stdlib, no external dependencies
  - All timestamps ISO 8601 UTC
  - Validation on construction, so a malformed Fact fails here rather than
    downstream where the cause is no longer obvious

Usage:
    from skills._lib.factcontract import Fact, verify
    f = Fact(name="NVDA_chg_pct", value=-3.39, unit="pct",
             freq="daily", as_of="2026-07-31T20:15:00Z", source="sec-xbrl",
             entity="NVDA")
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

# ── Value domains ─────────────────────────────────────────────────
UNITS = ("pct", "usd", "shares", "ratio", "x", "count", "bps")
FREQS = ("intraday", "daily", "weekly", "monthly", "quarterly", "ttm", "annual", "point")

# ── Staleness limits: how old a value of each frequency may be ────
# `daily` gets 4 days to tolerate weekends and holidays — Friday's close is
# still the latest print on Tuesday morning.
# `point` is a static value (a strike price, a share structure) with no natural
# notion of going stale.
_DAY = 86400
STALENESS_LIMITS = {
    "intraday": 60 * 60,        # quotes: 1 hour (covers a ~15min feed delay plus slack)
    "daily": 4 * _DAY,          # daily bars and same-day moves
    "weekly": 10 * _DAY,
    "monthly": 45 * _DAY,
    "quarterly": 100 * _DAY,    # quarterly filings
    "ttm": 100 * _DAY,          # TTM rolls with each quarterly filing
    "annual": 400 * _DAY,
    "point": None,              # not checked
}

# ── Plausible magnitude ranges, by unit ───────────────────────────
# A hit is only a warning: an out-of-range number is not necessarily wrong, but
# it is usually a unit error or the wrong field being read.
MAGNITUDE_RANGES = {
    "pct":    (0.0, 500.0),        # a single-day move above 500% is almost always a split artifact
    "usd":    (1e-4, 1e13),        # above $10T or below a hundredth of a cent
    "shares": (1.0, 1e11),
    "ratio":  (0.0, 1000.0),
    "x":      (0.0, 1000.0),       # multiples such as P/E; negatives handled separately
    "count":  (0.0, 1e12),
    "bps":    (0.0, 100000.0),
}

# Jump detection: warn when a value exceeds this multiple of the median of its
# own history.
JUMP_RATIO_THRESHOLD = 10.0
# Below this many historical samples the baseline is not trustworthy enough to
# judge against.
JUMP_MIN_HISTORY = 3


class FactError(ValueError):
    """Fact construction failed validation."""


def parse_ts(ts) -> datetime:
    """Parse an ISO 8601 timestamp into an aware UTC datetime. Accepts a 'Z' suffix."""
    if isinstance(ts, datetime):
        dt = ts
    else:
        s = str(ts).strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(s)
        except ValueError as e:
            raise FactError(f"as_of is not a valid ISO 8601 timestamp: {ts!r}") from e
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Fact:
    """A number awaiting verification.

    name     stable identifier for the value; must be consistent across runs,
             since magnitude jump detection aligns history by it
    value    the number itself
    unit     one of UNITS
    freq     one of FREQS; determines the staleness limit and drives freq_align
    as_of    the moment the number describes, not the moment it was fetched
    source   provenance, e.g. "sec-xbrl" / "cboe" / a vendor name
    entity   the subject, typically a ticker; macro series can use the series name
    currency recorded but not yet checked, so enabling the check later needs no
             structural change
    group    Facts that feed the same formula share a group; freq_align only
             compares within a group
    note     free text, stored as given
    """

    name: str
    value: float
    unit: str
    freq: str
    as_of: str
    source: str
    entity: str = ""
    currency: str = ""
    group: str = ""
    note: str = ""
    _as_of_dt: datetime = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if not self.name or not str(self.name).strip():
            raise FactError("name cannot be empty")
        if self.value is None:
            raise FactError(f"{self.name}: value cannot be None")
        try:
            self.value = float(self.value)
        except (TypeError, ValueError) as e:
            raise FactError(f"{self.name}: value is not a number ({self.value!r})") from e
        if self.value != self.value:  # NaN
            raise FactError(f"{self.name}: value is NaN")
        if self.unit not in UNITS:
            raise FactError(f"{self.name}: unit={self.unit!r} not in {UNITS}")
        if self.freq not in FREQS:
            raise FactError(f"{self.name}: freq={self.freq!r} not in {FREQS}")
        if not self.source or not str(self.source).strip():
            raise FactError(
                f"{self.name}: source cannot be empty, every number needs a provenance"
            )
        self._as_of_dt = parse_ts(self.as_of)
        # Normalize to a canonical ISO string so stored values stay comparable.
        self.as_of = self._as_of_dt.isoformat()

    @property
    def as_of_dt(self) -> datetime:
        return self._as_of_dt

    def age_seconds(self, ref: datetime = None) -> float:
        return ((ref or now_utc()) - self._as_of_dt).total_seconds()

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("_as_of_dt", None)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Fact":
        allowed = {
            k: v for k, v in d.items()
            if k in cls.__dataclass_fields__ and k != "_as_of_dt"
        }
        missing = [
            k for k in ("name", "value", "unit", "freq", "as_of", "source")
            if k not in allowed
        ]
        if missing:
            raise FactError(f"Fact is missing fields: {', '.join(missing)}")
        return cls(**allowed)
