#!/usr/bin/env python
"""Quotes, which the reverse DCF and position sizing are both ratios against.

Three entries, none needing a key, because a price is the input most likely to
be wanted on a machine nobody has configured.

Yahoo's chart endpoint is first because it is the one verified working when this
was written. It is unofficial and has changed shape before, which is why the
parser fails loudly with an explanation rather than returning something
plausible. The second entry is the same API on Yahoo's other host, which covers
a single host failing rather than the API changing.

Stooq is last. It publishes a plain CSV endpoint with no key and no rate limit,
which would make it a good primary, but it returned 404 for every symbol tried
from the network this was built on. It may work from yours; it is kept in the
chain rather than deleted so that it can, and placed last so that a dead primary
never becomes the normal case.

Both return a Fact at `intraday` frequency, so the Fact contract's one-hour
staleness limit applies. A price is the one number where being an hour late
matters, and it is also the number a valuation is most often quietly built on
top of hours after it was fetched.
"""

import csv
import io
import logging
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from .base import Adapter, AdapterError, as_fact
from .http import DEFAULT_TIMEOUT, get_json

_log = logging.getLogger(__name__)

DOMAIN = "price"

_STOOQ_URL = "https://stooq.com/q/l/?s={symbol}&f=sd2t2ohlcv&h&e=csv"
_YAHOO_URL = ("https://{host}/v8/finance/chart/{symbol}?interval=1d&range=1d")
_YAHOO_HOSTS = ("query1.finance.yahoo.com", "query2.finance.yahoo.com")

# Stooq wants a market suffix that most callers will not think to add.
_STOOQ_DEFAULT_SUFFIX = ".us"


class StooqAdapter(Adapter):
    """Free CSV quotes, no key required."""

    def __init__(self):
        super().__init__(name="stooq", domain=DOMAIN)

    def fetch(self, key: str, **kwargs) -> list:
        symbol = key.strip().lower()
        if "." not in symbol:
            symbol += _STOOQ_DEFAULT_SUFFIX
        url = _STOOQ_URL.format(symbol=urllib.parse.quote(symbol))

        try:
            with urllib.request.urlopen(url, timeout=DEFAULT_TIMEOUT) as response:
                text = response.read().decode("utf-8")
        except (urllib.error.URLError, urllib.error.HTTPError) as exc:
            raise AdapterError(f"could not reach Stooq for {key}: {exc}") from exc

        rows = list(csv.DictReader(io.StringIO(text)))
        if not rows:
            raise AdapterError(f"Stooq returned no rows for {symbol}")
        row = rows[0]
        close = row.get("Close")
        if close in (None, "", "N/D"):
            raise AdapterError(
                f"Stooq has no price for {symbol}. The symbol may need a market "
                f"suffix, e.g. 'nvda.us' or '600519.cn'."
            )

        # Stooq does not report a currency, so only its US market is trusted.
        # A .de or .jp symbol would come back in euros or yen labelled as
        # dollars, which is the same bug in a quieter form.
        if not symbol.endswith(_STOOQ_DEFAULT_SUFFIX):
            raise AdapterError(
                f"Stooq does not report a currency, so only US symbols are read "
                f"from it. {symbol} may not be in dollars; use a source that "
                f"states the currency."
            )

        as_of = _stooq_timestamp(row)
        return [as_fact(
            name=f"{key.upper()}_price",
            value=close,
            unit="usd",
            currency="USD",
            freq="intraday",
            as_of=as_of,
            source="stooq",
            entity=key.upper(),
            note=f"stooq:{symbol} close",
        )]


class YahooAdapter(Adapter):
    """Quotes from Yahoo's chart endpoint. Unofficial; shape changes happen."""

    def __init__(self, host: str = _YAHOO_HOSTS[0]):
        # The host is part of the name so a chain listing shows which one
        # answered, rather than two entries that look identical.
        super().__init__(name=f"yahoo:{host.split('.')[0]}", domain=DOMAIN)
        self.host = host

    def fetch(self, key: str, **kwargs) -> list:
        symbol = key.strip().upper()
        payload = get_json(
            _YAHOO_URL.format(host=self.host, symbol=urllib.parse.quote(symbol)),
            headers={"User-Agent": "ai-investment-research"},
        )
        try:
            result = payload["chart"]["result"][0]
            meta = result["meta"]
            price = meta["regularMarketPrice"]
            stamp = meta.get("regularMarketTime")
        except (KeyError, IndexError, TypeError) as exc:
            raise AdapterError(
                f"Yahoo's response for {symbol} did not have the expected shape. "
                f"This endpoint is unofficial and changes without notice."
            ) from exc
        if price is None:
            raise AdapterError(f"Yahoo returned no price for {symbol}")

        currency = (meta.get("currency") or "").upper()
        _require_usd(symbol, currency)

        as_of = (
            datetime.fromtimestamp(stamp, tz=timezone.utc).isoformat()
            if stamp else datetime.now(timezone.utc).isoformat()
        )
        return [as_fact(
            name=f"{symbol}_price",
            value=price,
            unit="usd",
            currency=currency or "USD",
            freq="intraday",
            as_of=as_of,
            source="yahoo",
            entity=symbol,
            note="yahoo:regularMarketPrice",
        )]


def _require_usd(symbol: str, currency: str) -> None:
    """Refuse a price that is not in dollars.

    The whole pipeline treats `unit="usd"` as meaning dollars. A London listing
    quotes in pence, so Shell comes back as 3356 and is read as $3,356 against a
    real price near $45 — and both position sizing and the reverse DCF are
    ratios against that number. Mislabelling is worse than having no price.
    """
    if not currency or currency == "USD":
        return
    hint = ""
    if currency == "GBP" or currency == "GBX" or currency == "GBP=X":
        hint = " London quotes are in pence, so the figure is also 100x out."
    raise AdapterError(
        f"{symbol} is quoted in {currency}, not USD, and this pipeline treats "
        f"every price as dollars.{hint} Convert it and supply the price "
        f"directly, or use a source that quotes this listing in dollars."
    )


def _stooq_timestamp(row: dict) -> str:
    """Stooq gives a date and a time in separate columns, in UTC."""
    date, clock = row.get("Date"), row.get("Time")
    if not date or date == "N/D":
        return datetime.now(timezone.utc).isoformat()
    try:
        stamp = datetime.strptime(f"{date} {clock or '00:00:00'}",
                                  "%Y-%m-%d %H:%M:%S")
    except ValueError:
        try:
            stamp = datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            return datetime.now(timezone.utc).isoformat()
    return stamp.replace(tzinfo=timezone.utc).isoformat()
