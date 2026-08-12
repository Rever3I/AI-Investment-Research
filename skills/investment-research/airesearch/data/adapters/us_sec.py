#!/usr/bin/env python
"""US filings, from SEC EDGAR's XBRL company facts.

This is the reference adapter: free, no key, and a primary source rather than
somebody's summary of one. What comes out is what the company told the
regulator, which is the standard the rest of the pipeline is built to.

The work is not fetching, it is **tag selection**. US GAAP offers several tags
for the same economic quantity, companies disagree about which to use, abandon
one for another mid-decade, and file some quantities in millions. Every rule
below exists because a live company broke a simpler one, and each produced a
figure that looked entirely ordinary on the way to a valuation.

SEC requires a descriptive User-Agent with contact details and rate-limits to
ten requests a second. Both are handled: the contact string comes from the
profile, and an installation that has not set one is told so rather than being
quietly blocked.
"""

import logging
from datetime import datetime, timezone

from .base import Adapter, AdapterError, AdapterUnavailable, as_fact
from .http import cache_get, cache_put, get_json

_log = logging.getLogger(__name__)

_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"

SOURCE = "sec-xbrl"
DOMAIN = "us_equity"

# `kind` is the difference between a quantity you may sum and one you may not.
# A flow accumulates over a period, so four quarters make a year. A stock is a
# level at a moment: adding four quarterly share counts gives four times the
# company, and the result is still a plausible number of shares, so nothing
# downstream objects.
FLOW, STOCK = "flow", "stock"

CONCEPTS = {
    "net_income": (
        ["NetIncomeLoss",
         "ProfitLoss",
         "NetIncomeLossAvailableToCommonStockholdersBasic"],
        "usd", FLOW,
    ),
    "depreciation_amortisation": (
        ["DepreciationDepletionAndAmortization",
         "DepreciationAmortizationAndAccretionNet",
         "DepreciationAndAmortization",
         "Depreciation"],
        "usd", FLOW,
    ),
    "capital_expenditure": (
        ["PaymentsToAcquirePropertyPlantAndEquipment",
         "PaymentsToAcquireProductiveAssets",
         "PaymentsToAcquirePropertyPlantAndEquipmentAndIntangibleAssets"],
        "usd", FLOW,
    ),
    "shares_outstanding": (
        ["CommonStockSharesOutstanding",
         "EntityCommonStockSharesOutstanding",
         "WeightedAverageNumberOfDilutedSharesOutstanding",
         "WeightedAverageNumberOfSharesOutstandingBasic"],
        "shares", STOCK,
    ),
}

# The concepts owner earnings is computed from. A partial set is worse than
# none: the documented formula is net income plus depreciation less capital
# expenditure, and a missing term reads as zero, which flatters exactly the
# capital-intensive businesses where capital expenditure matters most.
_OWNER_EARNINGS = ("net_income", "depreciation_amortisation", "capital_expenditure")

# A listed issuer with fewer shares than this is not reporting a share count.
# Several filers tag the figure in millions, and the plausible range for a share
# count is wide enough that a company with seven hundred shares outstanding
# passes every check downstream while producing a per-share value in the
# millions.
_MIN_PLAUSIBLE_SHARES = 100_000

# The four quarterly filings that make a trailing twelve months.
_TTM_QUARTERS = 4

# How stale a figure may be before it is not worth returning. The Fact contract
# checks this for dated frequencies, but never for `point`, so a share count
# from 2014 would otherwise pass unexamined.
_MAX_AGE_DAYS = 500


def _headers(contact: str) -> dict:
    return {
        "User-Agent": contact,
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
    }


class SECAdapter(Adapter):
    """SEC EDGAR company facts."""

    def __init__(self, contact: str = "", db_path=None):
        super().__init__(name=SOURCE, domain=DOMAIN)
        self.contact = (contact or "").strip()
        self.db_path = db_path

    def available(self) -> bool:
        return "@" in self.contact

    def unavailable_reason(self) -> str:
        if self.available():
            return ""
        from ...config import profile_path  # noqa: PLC0415 - avoids a cycle
        return (
            "SEC requires a User-Agent naming a contact email. Set "
            f"`sec_contact` in {profile_path()} (create the file if it is not "
            'there), e.g. "Jane Roe jane@example.com". Without it SEC '
            "returns 403."
        )

    # ── ticker resolution ─────────────────────────────────────────

    def cik_for(self, ticker: str) -> str:
        """The ten-digit CIK for a ticker.

        Cached, but with an age limit rather than forever: CIKs get reassigned
        and successor registrants appear, and a pinned map would keep serving
        another entity's financials under a familiar ticker.
        """
        ticker = ticker.upper().strip()
        cached = cache_get("sec:ticker-map", DOMAIN, db_path=self.db_path)
        mapping = None
        if cached and not _older_than(cached.get("as_of"), _TICKER_MAP_MAX_AGE_DAYS):
            mapping = cached["value"]

        if not mapping or ticker not in mapping:
            raw = get_json(_TICKERS_URL, headers=_headers(self.contact))
            mapping = {
                entry["ticker"].upper(): str(entry["cik_str"]).zfill(10)
                for entry in raw.values()
                if entry.get("ticker")
            }
            cache_put("sec:ticker-map", DOMAIN, mapping,
                      as_of=_now_iso(), source=SOURCE, freq="point",
                      db_path=self.db_path)

        if ticker not in mapping:
            raise AdapterError(
                f"{ticker} is not in SEC's ticker list. It may be a foreign "
                f"issuer that files on a different form, or the ticker may be "
                f"wrong."
            )
        return mapping[ticker]

    # ── the fetch ─────────────────────────────────────────────────

    def fetch(self, key: str, **kwargs) -> list:
        """Return owner-earnings inputs for a ticker, as Facts.

        Each Fact carries `group="owner_earnings"`, so the Fact contract's
        frequency check has something to compare within.
        """
        if not self.available():
            raise AdapterUnavailable(self.unavailable_reason())

        ticker = key.upper().strip()
        cik = self.cik_for(ticker)
        try:
            payload = get_json(_FACTS_URL.format(cik=cik),
                               headers=_headers(self.contact))
        except AdapterError as exc:
            if "403" in str(exc):
                raise AdapterError(
                    f"SEC refused the request for {ticker}: {exc}. This is "
                    f"almost always the User-Agent. {self.unavailable_reason()} "
                    f"Current value: {self.contact!r}"
                ) from exc
            raise

        us_gaap = payload.get("facts", {}).get("us-gaap", {})
        dei = payload.get("facts", {}).get("dei", {})
        if not us_gaap:
            raise AdapterError(
                f"SEC returned no us-gaap facts for {ticker}. Foreign private "
                f"issuers file under IFRS (ifrs-full), which this adapter does "
                f"not read."
            )

        facts, missing = [], []
        for concept, (candidates, unit, kind) in CONCEPTS.items():
            found = _select(us_gaap, dei, candidates, unit, kind)
            if found is None:
                missing.append(concept)
                _log.warning("No usable tag for %s on %s; tried %s",
                             concept, ticker, candidates)
                continue
            value, as_of, tag, freq = found
            facts.append(as_fact(
                name=f"{ticker}_{concept}",
                value=value,
                unit=unit,
                freq=freq,
                as_of=as_of,
                source=SOURCE,
                entity=ticker,
                currency="USD",
                group="owner_earnings",
                # The tag is the audit trail: two companies reporting the same
                # concept under different tags are not always comparable, and a
                # reader can only notice that if the tag is visible.
                note=f"us-gaap:{tag}",
            ))

        absent = [c for c in _OWNER_EARNINGS if c in missing]
        if absent:
            raise AdapterError(
                f"cannot assemble owner earnings for {ticker}: no usable tag "
                f"for {', '.join(absent)}. Returning the rest would be worse "
                f"than returning nothing, because the formula is net income "
                f"plus depreciation less capital expenditure and a missing term "
                f"reads as zero. Banks and REITs often genuinely lack a capital "
                f"expenditure line, which says an owner-earnings DCF does not "
                f"fit the business rather than that there is a gap to paper over."
            )
        if not facts:
            raise AdapterError(
                f"SEC has facts for {ticker} but none under the tags this "
                f"adapter knows. Add the tag it does use to CONCEPTS."
            )
        return facts


# A week is plenty: the map changes when listings do, and re-downloading it
# occasionally costs one request.
_TICKER_MAP_MAX_AGE_DAYS = 7


def _older_than(as_of, days) -> bool:
    if not as_of:
        return True
    try:
        stamp = datetime.fromisoformat(str(as_of).replace("Z", "+00:00"))
    except ValueError:
        return True
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - stamp).days > days


def _select(us_gaap: dict, dei: dict, candidates, unit: str, kind: str):
    """The best value across candidate tags, by period quality then freshness.

    Freshest wins; list order only breaks ties, so a tag a company abandoned in
    2020 loses to the one it files under now.

    Period quality is not a factor here because it is settled earlier:
    _latest_value refuses to return a bare quarter for a flow at all. That is
    what stops Starbucks, which files an annual DepreciationDepletionAndAmortization
    and a much fresher single-quarter Depreciation, from being valued off a
    figure five times too small.
    """
    unit_key = "USD" if unit == "usd" else "shares"
    best = None
    for rank, tag in enumerate(candidates):
        node = us_gaap.get(tag) or dei.get(tag)
        if not node:
            continue
        series = node.get("units", {}).get(unit_key)
        if not series:
            continue
        result = _latest_value(series, tag, kind)
        if result is None:
            continue
        value, as_of, _, _ = result
        if kind == STOCK and unit == "shares" and value < _MIN_PLAUSIBLE_SHARES:
            # Some filers tag the count in millions. A company with seven
            # hundred shares outstanding produces a per-share value in the
            # millions, and nothing downstream finds that implausible.
            _log.warning("Rejecting share count %s from %s: filed in millions, "
                         "or not a share count", value, tag)
            continue
        if _older_than(as_of, _MAX_AGE_DAYS):
            _log.warning("Rejecting %s from %s: %s is beyond the age limit",
                         tag, unit, as_of)
            continue
        score = (as_of, -rank)
        if best is None or score > best[0]:
            best = (score, result)
    return best[1] if best else None


def _duration_days(entry):
    """Length of the period an entry covers, or None for a point-in-time value."""
    start, end = entry.get("start"), entry.get("end")
    if not start or not end:
        return None
    try:
        return (datetime.strptime(end, "%Y-%m-%d")
                - datetime.strptime(start, "%Y-%m-%d")).days
    except (TypeError, ValueError):
        return None


# XBRL duration entries are not all discrete periods: a "Q3" filing often covers
# the nine months from the start of the year. Summing four of those is not a
# trailing twelve months, it is roughly triple one. Real fiscal calendars vary,
# so these are ranges: a 13-week quarter is 91 days, a 14-week quarter 98, and a
# 53-week year 371.
_QUARTER_DAYS = (80, 100)
_ANNUAL_DAYS = (340, 400)


def _in_range(days, bounds):
    return days is not None and bounds[0] <= days <= bounds[1]


def _latest_value(series, tag: str, kind: str):
    """The most recent usable figure from an XBRL unit series."""
    dated = [e for e in series if e.get("end") and e.get("val") is not None]
    if not dated:
        return None
    dated.sort(key=lambda e: e["end"])

    instants = [e for e in dated if _duration_days(e) is None]
    annuals = [e for e in dated if _in_range(_duration_days(e), _ANNUAL_DAYS)]

    if kind == STOCK:
        # A level, not a flow. Four quarterly weighted-average share counts sum
        # to four times the company, and the answer is still a plausible number
        # of shares, so nothing catches it.
        source = instants or annuals
        if not source:
            return None
        latest = source[-1]
        return latest["val"], _to_iso(latest["end"]), tag, "point"

    quarters = [e for e in dated if _in_range(_duration_days(e), _QUARTER_DAYS)]
    ttm = _trailing_twelve(quarters)
    latest_annual = annuals[-1] if annuals else None

    if ttm is not None and (latest_annual is None or ttm[1] > latest_annual["end"]):
        return ttm[0], _to_iso(ttm[1]), tag, "ttm"
    if latest_annual is not None:
        return latest_annual["val"], _to_iso(latest_annual["end"]), tag, "annual"
    if ttm is not None:
        return ttm[0], _to_iso(ttm[1]), tag, "ttm"
    # A single quarter is deliberately not returned for a flow. Dropped into a
    # group the valuation layer reads as annual, it is a fourfold error that the
    # frequency check only warns about.
    return None


def _trailing_twelve(quarters):
    """Sum four consecutive discrete quarters, or None if they are not there.

    Deduplicates by period end because XBRL restates: the same quarter appears
    in several filings, and counting each occurrence multiplies the answer.
    Also checks the four are consecutive — four quarters with a gap between them
    is not a year, and treating it as one understates every ratio built on top.
    """
    if not quarters:
        return None
    seen = {}
    for entry in quarters:
        seen[entry["end"]] = entry["val"]
    ends = sorted(seen)[-_TTM_QUARTERS:]
    if len(ends) < _TTM_QUARTERS:
        return None

    span = (datetime.strptime(ends[-1], "%Y-%m-%d")
            - datetime.strptime(ends[0], "%Y-%m-%d")).days
    # Three gaps between four quarter-ends is about nine months.
    if not 240 <= span <= 320:
        return None
    return sum(seen[end] for end in ends), ends[-1]


def _to_iso(end: str) -> str:
    """XBRL dates are YYYY-MM-DD; the Fact contract wants a UTC timestamp."""
    try:
        parsed = datetime.strptime(end, "%Y-%m-%d")
    except (TypeError, ValueError) as exc:
        raise AdapterError(f"SEC returned an unparseable period end {end!r}") from exc
    return parsed.replace(tzinfo=timezone.utc).isoformat()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
