#!/usr/bin/env python
"""Shared data-record schemas — the real interface between research-* skills.

Each layer of the pipeline hands the next one a validated record rather than
prose. That is what lets a candidate sourced from a quantitative screen and one
sourced from a macro thesis flow through the same downstream stages.

Records validate on construction, so a malformed record cannot reach the layer
that consumes it. Timestamps normalize to UTC ISO 8601 on the way in.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

ENTRY_PATHS = ("screen", "thesis")
MARKETS = ("US", "CN")
SIZING_METHODS = ("half_kelly", "full_kelly", "fixed_pct", "custom")
DEBATE_MODES = ("checklist", "persona_debate")
DIFF_VERDICTS = ("facts_changed", "judgment_changed", "still_holds")

# Scenario probabilities are author-supplied and often rounded to 3 decimals,
# so exact equality to 1.0 would reject legitimate input.
_PROBABILITY_TOLERANCE = 0.01


class SchemaError(ValueError):
    """Record construction failed validation."""


def _parse_ts(ts, record_name: str, field_name: str) -> str:
    """Normalize an ISO 8601 timestamp to UTC. Naive input is assumed UTC."""
    if isinstance(ts, datetime):
        dt = ts
    else:
        s = str(ts).strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(s)
        except ValueError as e:
            raise SchemaError(
                f"{record_name}: {field_name} is not a valid ISO 8601 timestamp: {ts!r}"
            ) from e
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _require(value, field_name: str, record_name: str) -> None:
    if value is None or (isinstance(value, str) and not value.strip()):
        raise SchemaError(f"{record_name}: {field_name} is required")


def _require_choice(value, choices, field_name: str, record_name: str) -> None:
    if value not in choices:
        raise SchemaError(f"{record_name}: {field_name}={value!r} not in {choices}")


class _Record:
    """Shared dict conversion for every record type."""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict):
        allowed = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**allowed)


@dataclass
class Candidate(_Record):
    """Produced by research-intake (Layer 1-2). Entry point for the pipeline.

    `screened` is True only when a saved criteria profile was actually applied.
    A candidate from a general open search is a normal, complete record — an
    empty `profile_used` is not an unfinished one.
    """

    ticker: str
    entry_path: str          # "screen" | "thesis"
    source_note: str         # profile name, or the thesis text if thesis-first
    market: str              # "US" | "CN"
    raw_rationale: str
    discovered_at: str
    screened: bool = False
    profile_used: str = ""

    def __post_init__(self):
        _require(self.ticker, "ticker", "Candidate")
        _require_choice(self.entry_path, ENTRY_PATHS, "entry_path", "Candidate")
        _require_choice(self.market, MARKETS, "market", "Candidate")
        _require(self.raw_rationale, "raw_rationale", "Candidate")
        self.discovered_at = _parse_ts(self.discovered_at, "Candidate", "discovered_at")


@dataclass
class Thesis(_Record):
    """Produced by research-thesis (Layer 3).

    `variant_perception` and `falsifiers` are what separate this from a summary:
    what the author believes that the market does not, and what would prove it
    wrong.
    """

    candidate_id: int
    business_overview: str
    management: str
    competitors: str
    tam: str
    risks: list = field(default_factory=list)
    variant_perception: str = ""
    falsifiers: list = field(default_factory=list)
    data_sources: list = field(default_factory=list)
    authored_at: str = ""

    def __post_init__(self):
        _require(self.candidate_id, "candidate_id", "Thesis")
        _require(self.business_overview, "business_overview", "Thesis")
        if not self.risks:
            raise SchemaError("Thesis: risks must have at least one entry")
        if self.authored_at:
            self.authored_at = _parse_ts(self.authored_at, "Thesis", "authored_at")


@dataclass
class Valuation(_Record):
    """Produced by research-valuation (Layer 4).

    Scenario probabilities must sum to 1: research-portfolio reads them directly
    as Kelly inputs, so a set that does not sum to 1 would silently corrupt
    position sizing downstream.
    """

    thesis_id: int
    scenarios: list          # [{name, price_target, probability, assumptions}]
    discount_rate_source: str
    html_artifact_path: str = ""
    valued_at: str = ""

    def __post_init__(self):
        _require(self.thesis_id, "thesis_id", "Valuation")
        if not self.scenarios:
            raise SchemaError("Valuation: scenarios must have at least one entry")
        total = sum(s.get("probability", 0) for s in self.scenarios)
        if abs(total - 1.0) > _PROBABILITY_TOLERANCE:
            raise SchemaError(
                f"Valuation: scenario probabilities must sum to 1.0, got {total}"
            )
        if self.valued_at:
            self.valued_at = _parse_ts(self.valued_at, "Valuation", "valued_at")


@dataclass
class Verdict(_Record):
    """Produced by research-debate (Layer 5), only when that layer is enabled.

    `dissent_map` is deliberately preserved rather than resolved into a single
    call — unresolved disagreement is the output, not a failure to converge.
    """

    valuation_id: int
    mode: str                # "checklist" | "persona_debate"
    votes: list = field(default_factory=list)
    dissent_map: str = ""
    authored_at: str = ""

    def __post_init__(self):
        _require(self.valuation_id, "valuation_id", "Verdict")
        _require_choice(self.mode, DEBATE_MODES, "mode", "Verdict")
        if self.authored_at:
            self.authored_at = _parse_ts(self.authored_at, "Verdict", "authored_at")


@dataclass
class Portfolio(_Record):
    """Produced by research-portfolio (Layer 6)."""

    valuation_id: int
    sizing_method: str       # one of SIZING_METHODS
    recommended_position_pct: float
    kelly_inputs: dict = field(default_factory=dict)
    sized_at: str = ""

    def __post_init__(self):
        _require(self.valuation_id, "valuation_id", "Portfolio")
        _require_choice(self.sizing_method, SIZING_METHODS, "sizing_method", "Portfolio")
        if self.recommended_position_pct < 0:
            raise SchemaError("Portfolio: recommended_position_pct cannot be negative")
        if self.sized_at:
            self.sized_at = _parse_ts(self.sized_at, "Portfolio", "sized_at")


@dataclass
class Sellcheck(_Record):
    """Produced by research-sellcheck (Layer 7-8), on demand at sell time.

    `diff_summary` reports which of DIFF_VERDICTS applies and elaborates on it:
    whether the facts moved, the author's judgment moved, or the thesis stands.
    """

    thesis_id: int
    trigger: str             # "user_initiated" in v1
    diff_summary: str
    rechecked_at: str = ""

    def __post_init__(self):
        _require(self.thesis_id, "thesis_id", "Sellcheck")
        _require(self.trigger, "trigger", "Sellcheck")
        _require(self.diff_summary, "diff_summary", "Sellcheck")
        if self.rechecked_at:
            self.rechecked_at = _parse_ts(self.rechecked_at, "Sellcheck", "rechecked_at")
