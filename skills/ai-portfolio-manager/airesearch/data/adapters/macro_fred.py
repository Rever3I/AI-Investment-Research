#!/usr/bin/env python
"""Macro series from FRED, mostly so the discount rate has a source.

`research-valuation` refuses to assume a discount rate, which means somebody has
to supply one and say where it came from. A risk-free yield plus an equity risk
premium is the usual construction, and this is where the first half of that
comes from with a date attached instead of from memory.

A free API key is required. Without one the adapter reports itself unavailable
rather than failing at fetch time, so a fallback can take over and the user is
told what to configure.
"""

from datetime import datetime, timezone

from .base import Adapter, AdapterError, AdapterUnavailable, as_fact
from .http import cache_get, cache_put, get_json

SOURCE = "fred"
DOMAIN = "macro"

_URL = ("https://api.stlouisfed.org/fred/series/observations"
        "?series_id={series}&api_key={key}&file_type=json"
        "&sort_order=desc&limit=1")

# The series this pipeline actually asks for, with the unit each is published
# in. FRED returns percent for yields, so a 4.2% yield arrives as 4.2 and is
# stored as such: converting to a fraction here would hide the unit from the
# Fact contract, which is the thing that catches unit errors.
SERIES = {
    "us_10y": ("DGS10", "pct", "daily",
               "US 10-year Treasury constant maturity yield"),
    "us_2y": ("DGS2", "pct", "daily", "US 2-year Treasury yield"),
    "us_3m": ("DGS3MO", "pct", "daily", "US 3-month Treasury yield"),
    "cpi_yoy": ("CPIAUCSL", "count", "monthly",
                "US CPI, all urban consumers, index level"),
    "fed_funds": ("DFF", "pct", "daily", "Effective federal funds rate"),
}


class FREDAdapter(Adapter):
    """Federal Reserve Economic Data."""

    def __init__(self, api_key: str = "", db_path=None):
        super().__init__(name=SOURCE, domain=DOMAIN)
        self.api_key = (api_key or "").strip()
        self.db_path = db_path

    def available(self) -> bool:
        return bool(self.api_key)

    def unavailable_reason(self) -> str:
        if self.available():
            return ""
        from ...config import profile_path  # noqa: PLC0415 - avoids a cycle
        return (
            "FRED needs a free API key. Register at "
            "https://fredaccount.stlouisfed.org/apikeys and set `fred_api_key` "
            f"in {profile_path()} (create the file if it is not there)."
        )

    def fetch(self, key: str, **kwargs) -> list:
        """Return the latest observation of a named series, as a Fact."""
        if not self.available():
            raise AdapterUnavailable(self.unavailable_reason())
        if key not in SERIES:
            raise AdapterError(
                f"unknown macro series {key!r}; this adapter knows "
                f"{sorted(SERIES)}"
            )

        series_id, unit, freq, description = SERIES[key]
        payload = get_json(_URL.format(series=series_id, key=self.api_key))
        observations = payload.get("observations") or []
        if not observations:
            raise AdapterError(f"FRED returned no observations for {series_id}")

        latest = observations[0]
        raw = latest.get("value")
        if raw in (None, "", "."):
            # FRED writes "." for a day with no print, such as a market holiday.
            raise AdapterError(
                f"FRED's latest {series_id} observation ({latest.get('date')}) "
                f"has no value; markets were probably closed."
            )

        as_of = _to_iso(latest["date"])
        cache_put(f"fred:{key}", DOMAIN, {"value": raw, "date": latest["date"]},
                  as_of=as_of, source=SOURCE, freq=freq, db_path=self.db_path)

        return [as_fact(
            name=key,
            value=raw,
            unit=unit,
            freq=freq,
            as_of=as_of,
            source=SOURCE,
            entity=series_id,
            note=description,
        )]

    def cached(self, key: str):
        """The last stored observation, without a network call."""
        return cache_get(f"fred:{key}", DOMAIN, db_path=self.db_path)


def _to_iso(date: str) -> str:
    try:
        parsed = datetime.strptime(date, "%Y-%m-%d")
    except (TypeError, ValueError) as exc:
        raise AdapterError(f"FRED returned an unparseable date {date!r}") from exc
    return parsed.replace(tzinfo=timezone.utc).isoformat()
