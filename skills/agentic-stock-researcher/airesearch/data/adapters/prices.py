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

A quote comes back as `intraday` while it is a live print and as `daily` once
it is that session's close — see `_classify`. Labelling every quote `intraday`
put a one-hour staleness limit on the close too, which made the pipeline
unusable outside market hours: an evening research session, or any A-share seen
from another timezone, hard-stopped on the price before it could value
anything.
"""

import csv
import io
import logging
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

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
        freq, state = _classify(as_of)
        return [as_fact(
            name=f"{key.upper()}_price",
            value=close,
            unit="usd",
            currency="USD",
            freq=freq,
            as_of=as_of.isoformat(),
            source="stooq",
            entity=key.upper(),
            note=f"stooq:{symbol} close, {state}",
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
            headers={"User-Agent": "agentic-stock-researcher"},
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
        _check_quote_currency(symbol, currency)

        as_of = (
            datetime.fromtimestamp(stamp, tz=timezone.utc)
            if stamp else datetime.now(timezone.utc)
        )
        freq, note = _classify(as_of)
        return [as_fact(
            name=f"{symbol}_price",
            value=price,
            unit="usd",
            currency=currency,
            freq=freq,
            as_of=as_of.isoformat(),
            source="yahoo",
            entity=symbol,
            note=f"yahoo:regularMarketPrice, {note}",
        )]


# Quote units that are a fraction of their own currency. Yahoo reports London
# in GBp, and the number is 100x the price in pounds, so it is wrong while
# still carrying a currency label that agrees with the filings.
_SUBDIVIDED = {"GBP", "GBX", "GBP=X", "ZAC", "ILA"}

# Beyond this, a quote is no longer a live print; it is that session's close.
_LIVE_WINDOW = timedelta(hours=1)


def _classify(as_of: datetime):
    """Whether this quote is a live print or a settled close.

    Both come back from the same field, and calling everything `intraday` made
    the pipeline unusable outside market hours: the Fact contract allows an
    intraday figure one hour, so any research done in the evening — or on an
    A-share from another timezone, which is the normal case — hard-stopped on
    the price before it could value anything.

    A close is not stale data. It is the last print there is, and it stays that
    way until the next session, which is what the `daily` limit already exists
    to allow ("Friday's close is still the latest print on Tuesday morning").

    The one thing this cannot distinguish is a genuinely closed market from a
    feed stuck hours behind during an open one. Yahoo's chart endpoint reports
    no market state, so nothing here can. The exposure is a price a few hours
    out inside a ten-year discounted cash flow, which is a rounding error
    against the growth assumption it sits next to.
    """
    age = datetime.now(timezone.utc) - as_of
    if age <= _LIVE_WINDOW:
        return "intraday", "live print"
    return "daily", "session close"


def _check_quote_currency(symbol: str, currency: str) -> None:
    """Refuse a price whose currency is unknown or quoted in subunits.

    A non-dollar price is fine. A Shanghai listing valued in yuan against yuan
    financials is a correct valuation, and refusing it would shut out every
    market this pipeline claims to reach. What the currency check protects
    against is mixing, and that is caught downstream: the Fact contract hard-
    stops when one entity carries money in two currencies, because nothing here
    converts between them.

    Two cases still have to be refused here, because no later check can see
    them. A quote with no currency stated cannot be aligned against anything.
    And a quote in a subunit is wrong inside its own label: London quotes in
    pence, so Shell comes back as 3356 against a real price near GBP 45, and
    both position sizing and the reverse DCF are ratios against that number.
    """
    if not currency:
        raise AdapterError(
            f"{symbol} came back with no currency stated, so there is no way to "
            f"tell what the figure means. Use a source that states one."
        )
    if currency in _SUBDIVIDED:
        raise AdapterError(
            f"{symbol} is quoted in {currency}, a subunit rather than the "
            f"currency itself, so the figure is 100x the real price. Use a "
            f"listing quoted in the main unit, or supply the price directly."
        )


def _stooq_timestamp(row: dict) -> datetime:
    """Stooq gives a date and a time in separate columns, in UTC.

    Returns a datetime rather than a string because `_classify` has to compare
    it against now to tell a live print from a close.
    """
    date, clock = row.get("Date"), row.get("Time")
    if not date or date == "N/D":
        return datetime.now(timezone.utc)
    try:
        stamp = datetime.strptime(f"{date} {clock or '00:00:00'}",
                                  "%Y-%m-%d %H:%M:%S")
    except ValueError:
        try:
            stamp = datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            return datetime.now(timezone.utc)
    return stamp.replace(tzinfo=timezone.utc)
