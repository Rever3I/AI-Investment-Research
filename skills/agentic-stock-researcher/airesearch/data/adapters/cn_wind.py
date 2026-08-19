#!/usr/bin/env python
"""Chinese listings via Wind.

**This adapter is written but not verified against a live terminal.** Wind is
licensed software: `WindPy` ships with an installed Wind Financial Terminal and
cannot be obtained, installed, or exercised without a subscription. Everything
here is written to Wind's documented `w.wsd`/`w.wss` interface, and the parts
that do not need Wind — availability reporting, tag mapping, Fact construction
from a response — are tested with a stubbed client.

Treat it as a starting point rather than a finished integration. If you have a
terminal, run it, and open an issue with what came back if it differs; that is a
better contribution than a guess made without one.

The import is deliberately lazy. An installation without Wind must not fail at
import time, because that would break the pipeline for every user who is only
looking at US listings.
"""

import logging
from datetime import datetime, timezone

from .base import Adapter, AdapterError, AdapterUnavailable, as_fact

_log = logging.getLogger(__name__)

SOURCE = "wind"
DOMAIN = "cn_equity"

# Wind field codes for the owner-earnings inputs, keyed to the same concept
# names the SEC adapter uses, so downstream code does not care which market a
# name is listed in.
FIELDS = {
    "net_income": ("np_belongto_parcomsh", "usd"),
    "depreciation_amortisation": ("depr_fa_coga_dpba", "usd"),
    "capital_expenditure": ("cash_pay_acq_const_fiolta", "usd"),
    "shares_outstanding": ("total_shares", "shares"),
}


def _load_windpy():
    """Import WindPy on demand, translating its absence into a clear message."""
    try:
        from WindPy import w  # noqa: PLC0415 - deliberately lazy
    except ImportError as exc:
        raise AdapterUnavailable(
            "WindPy is not installed. It ships with a licensed Wind Financial "
            "Terminal and cannot be installed from PyPI. Without it, Chinese "
            "listings have no data source configured."
        ) from exc
    return w


class WindAdapter(Adapter):
    """Wind Financial Terminal.

    NOTE: unverified against a live terminal. See the module docstring.
    """

    def __init__(self, client=None, currency: str = "CNY"):
        super().__init__(name=SOURCE, domain=DOMAIN)
        self._client = client
        self.currency = currency

    def client(self):
        if self._client is None:
            self._client = _load_windpy()
            if not self._client.isconnected():
                started = self._client.start()
                if getattr(started, "ErrorCode", 0) != 0:
                    raise AdapterUnavailable(
                        f"WindPy is installed but would not start "
                        f"(ErrorCode {started.ErrorCode}). Check that the "
                        f"terminal is running and logged in."
                    )
        return self._client

    def available(self) -> bool:
        try:
            self.client()
            return True
        except AdapterUnavailable:
            return False

    def unavailable_reason(self) -> str:
        try:
            self.client()
            return ""
        except AdapterUnavailable as exc:
            return str(exc)

    def fetch(self, key: str, **kwargs) -> list:
        """Return owner-earnings inputs for a Wind code, as Facts.

        `key` is a Wind security code, e.g. "600519.SH" or "000651.SZ".
        """
        client = self.client()
        codes = ",".join(field for field, _ in FIELDS.values())
        response = client.wss(key, codes, "unit=1")

        error = getattr(response, "ErrorCode", 0)
        if error != 0:
            raise AdapterError(
                f"Wind returned ErrorCode {error} for {key}. Code 40520007 is "
                f"usually an unknown security; -40520401 is a lost connection."
            )

        fields = [str(f).lower() for f in getattr(response, "Fields", [])]
        data = getattr(response, "Data", [])
        if not fields or not data:
            raise AdapterError(f"Wind returned an empty response for {key}")

        as_of = _response_time(response)
        facts = []
        for concept, (field, unit) in FIELDS.items():
            if field.lower() not in fields:
                _log.warning("Wind did not return %s for %s", field, key)
                continue
            row = data[fields.index(field.lower())]
            value = row[0] if isinstance(row, (list, tuple)) else row
            if value is None:
                _log.warning("Wind returned no value for %s on %s", field, key)
                continue
            facts.append(as_fact(
                name=f"{key}_{concept}",
                value=value,
                unit=unit,
                # `unit="usd"` is the pipeline's tag for a money amount; the
                # currency field is what says which money. Leaving it unset
                # here meant yuan financials looked like dollars to everything
                # downstream, including the check that exists to catch that.
                currency=self.currency if unit == "usd" else "",
                freq="ttm",
                as_of=as_of,
                source=SOURCE,
                entity=key,
                group="owner_earnings",
                note=f"wind:{field}",
            ))

        if not facts:
            raise AdapterError(f"Wind returned no usable fields for {key}")
        return facts


def _response_time(response) -> str:
    """When the response describes. Wind returns datetimes; fall back to now."""
    times = getattr(response, "Times", None)
    if times:
        stamp = times[0]
        if isinstance(stamp, datetime):
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            return stamp.astimezone(timezone.utc).isoformat()
    return datetime.now(timezone.utc).isoformat()
