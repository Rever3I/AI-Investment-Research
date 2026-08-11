#!/usr/bin/env python
"""US filings, from SEC EDGAR's XBRL company facts.

This is the reference adapter: free, no key, and a primary source rather than
somebody's summary of one. What comes out is what the company told the
regulator, which is the standard the rest of the pipeline is built to.

The work is not fetching, it is **tag selection**. US GAAP offers several tags
for the same economic quantity and companies do not agree on which to use, so
each concept here carries an ordered list of candidates and reports which one
answered. A number whose tag nobody can see is a number nobody can check.

SEC requires a descriptive User-Agent with contact details and rate-limits to
ten requests a second. Both are handled: the contact string comes from the
profile, and an installation that has not set one is told so rather than being
quietly blocked.
"""

import logging
from datetime import datetime, timezone

from ..store_support import resolve
from .base import Adapter, AdapterError, AdapterUnavailable, as_fact
from .http import cache_get, cache_put, get_json

_log = logging.getLogger(__name__)

_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"

SOURCE = "sec-xbrl"
DOMAIN = "us_equity"

# Ordered candidates per concept. Companies differ on which tag they file under,
# and the first one present wins — so the order is a judgment about which tag
# means what we want, not just which is common.
CONCEPTS = {
    "net_income": (
        ["NetIncomeLoss",
         "ProfitLoss",
         "NetIncomeLossAvailableToCommonStockholdersBasic"],
        "usd",
    ),
    "depreciation_amortisation": (
        ["DepreciationDepletionAndAmortization",
         "DepreciationAmortizationAndAccretionNet",
         "DepreciationAndAmortization",
         "Depreciation"],
        "usd",
    ),
    "capital_expenditure": (
        ["PaymentsToAcquirePropertyPlantAndEquipment",
         "PaymentsToAcquireProductiveAssets",
         "PaymentsToAcquirePropertyPlantAndEquipmentAndIntangibleAssets"],
        "usd",
    ),
    "shares_outstanding": (
        ["CommonStockSharesOutstanding",
         "WeightedAverageNumberOfDilutedSharesOutstanding",
         "WeightedAverageNumberOfSharesOutstandingBasic"],
        "shares",
    ),
}

# The four quarterly filings that make a trailing twelve months.
_TTM_QUARTERS = 4


def _headers(contact: str) -> dict:
    return {
        "User-Agent": contact,
        "Accept": "application/json",
        "Accept-Encoding": "gzip, deflate",
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
        return (
            "SEC requires a User-Agent naming a contact email. Set "
            "`sec_contact` in config/research-profile.json, e.g. "
            '"Jane Roe jane@example.com". Without it SEC returns 403.'
        )

    # ── ticker resolution ─────────────────────────────────────────

    def cik_for(self, ticker: str) -> str:
        """The ten-digit CIK for a ticker.

        Cached because the whole map is one download that changes rarely, and
        re-fetching it for every lookup is the kind of thing that gets an
        installation rate-limited.
        """
        ticker = ticker.upper().strip()
        cached = cache_get("sec:ticker-map", DOMAIN, db_path=self.db_path)
        mapping = cached["value"] if cached else None

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
        frequency check catches a quarterly figure that wandered into a
        trailing-twelve-month calculation — the classic way a valuation comes
        out four times too small.
        """
        if not self.available():
            raise AdapterUnavailable(self.unavailable_reason())

        ticker = key.upper().strip()
        cik = self.cik_for(ticker)
        payload = get_json(_FACTS_URL.format(cik=cik),
                           headers=_headers(self.contact))
        us_gaap = payload.get("facts", {}).get("us-gaap", {})
        dei = payload.get("facts", {}).get("dei", {})
        if not us_gaap:
            raise AdapterError(f"SEC returned no us-gaap facts for {ticker}")

        facts = []
        for concept, (candidates, unit) in CONCEPTS.items():
            found = _first_available(us_gaap, dei, candidates, unit)
            if found is None:
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
                group="owner_earnings",
                # The tag is the audit trail: two companies reporting the same
                # concept under different tags are not always comparable, and
                # the reader can only notice that if the tag is visible.
                note=f"us-gaap:{tag}",
            ))

        if not facts:
            raise AdapterError(
                f"SEC has facts for {ticker} but none under the tags this "
                f"adapter knows. Add the tag it does use to CONCEPTS."
            )
        return facts


def _first_available(us_gaap: dict, dei: dict, candidates, unit: str):
    """The best value across the candidate tags, preferring the freshest.

    Order in the candidate list breaks ties; it does not override recency.
    Companies migrate between tags — NVDA stopped filing capital expenditure
    under PaymentsToAcquirePropertyPlantAndEquipment in 2020 and moved to
    PaymentsToAcquireProductiveAssets — and a first-match rule silently returns
    the abandoned tag's last value, six years stale, looking entirely normal.
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
        result = _latest_value(series, tag)
        if result is None:
            continue
        as_of = result[1]
        if best is None or (as_of, -rank) > (best[1], -best[4]):
            best = (*result, rank)
    return best[:4] if best else None


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
# trailing twelve months, it is roughly triple one. Fiscal quarters and years
# also vary by a few days, hence ranges rather than exact figures.
_QUARTER_DAYS = (80, 100)
_ANNUAL_DAYS = (340, 400)


def _in_range(days, bounds):
    return days is not None and bounds[0] <= days <= bounds[1]


def _latest_value(series, tag: str):
    """The most recent usable figure from an XBRL unit series.

    Prefers a trailing twelve months built from four discrete quarters, because
    that is both the freshest view and the one the valuation layer wants. Falls
    back to the latest annual filing, and then to a point-in-time value for the
    balance-sheet quantities that have no period at all.
    """
    dated = [e for e in series if e.get("end") and e.get("val") is not None]
    if not dated:
        return None
    dated.sort(key=lambda e: e["end"])

    quarters = [e for e in dated if _in_range(_duration_days(e), _QUARTER_DAYS)]
    annuals = [e for e in dated if _in_range(_duration_days(e), _ANNUAL_DAYS)]
    instants = [e for e in dated if _duration_days(e) is None]

    ttm = _trailing_twelve(quarters)
    latest_annual = annuals[-1] if annuals else None

    if ttm is not None and (latest_annual is None or ttm[1] > latest_annual["end"]):
        return ttm[0], _to_iso(ttm[1]), tag, "ttm"
    if latest_annual is not None:
        return latest_annual["val"], _to_iso(latest_annual["end"]), tag, "annual"
    if ttm is not None:
        return ttm[0], _to_iso(ttm[1]), tag, "ttm"
    if instants:
        # Shares outstanding and other balance-sheet quantities: a level, not a
        # flow, so there is nothing to sum and nothing to annualise.
        latest = instants[-1]
        return latest["val"], _to_iso(latest["end"]), tag, "point"
    if quarters:
        latest = quarters[-1]
        return latest["val"], _to_iso(latest["end"]), tag, "quarterly"
    return None


def _trailing_twelve(quarters):
    """Sum four consecutive discrete quarters, or None if they are not there.

    Deduplicates by period end because XBRL restates: the same quarter appears
    in several filings, and counting each occurrence multiplies the answer.
    Also checks the four are actually consecutive — four quarters with a gap is
    not a year, and silently treating it as one understates every ratio built
    on top.
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
