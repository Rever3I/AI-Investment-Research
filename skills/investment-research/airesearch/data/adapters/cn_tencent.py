#!/usr/bin/env python
"""Quotes from Tencent's 自选股 endpoint, and the share count they imply.

Free, no key, and it answered every time Eastmoney's quote endpoint was
returning 502 while this was being built — which is why it is here rather than
in a list of things that could be added later. Two sources that fail
independently is the whole reason the adapter layer is chains.

The response is a `~`-delimited array behind `v_<code>=`, encoded GBK. Field
positions are verified against live data rather than taken from a blog post,
and the ones this reads are cross-checked against a second source in the tests:

    [1]  name          [3]  last price
    [30] timestamp     [45] total market capitalisation, in 亿 (1e8) CNY

Shares outstanding is `[45] * 1e8 / [3]`. That is a derived figure and it is
derived deliberately: it is the count **now**, where the balance sheet's
registered capital is the count at the last year end, and a per-share number
quoted today should divide by the former. For Kweichow Moutai the two are
1,250,082,000 against 1,250,081,601 — the rounding in a figure published to two
decimal places, and nothing else.
"""

import logging
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

from .base import Adapter, AdapterError, as_fact
from .http import DEFAULT_TIMEOUT

_log = logging.getLogger(__name__)

SOURCE = "tencent"
DOMAIN = "price"

_URL = "https://qt.gtimg.cn/q={code}"
_HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://gu.qq.com/"}

# Field positions in the ~-delimited payload.
_NAME, _PRICE, _STAMP, _MARKET_CAP = 1, 3, 30, 45
_MIN_FIELDS = 46

# Prefixes this endpoint serves, and what each quotes in. Anything else is
# refused rather than assumed: a quote whose currency is guessed is the Shell
# bug in a different market.
_MARKETS = {"sh": "CNY", "sz": "CNY", "bj": "CNY", "hk": "HKD", "us": "USD"}

# China keeps one timezone year-round and does not observe daylight saving, so
# a fixed offset is exact here. zoneinfo would need the tzdata package on
# Windows, and this project ships no dependencies.
_BEIJING = timezone(timedelta(hours=8))

_LIVE_WINDOW = timedelta(hours=1)
_MIN_PLAUSIBLE_SHARES = 1_000_000


def normalise(code: str) -> str:
    """Turn any of the usual spellings into Tencent's `sh600519` form."""
    raw = str(code).strip().lower().replace(" ", "")
    for prefix in _MARKETS:
        if raw.startswith(prefix) and raw[len(prefix):].isdigit():
            return raw
    digits, sep, suffix = raw.partition(".")
    market = {"sh": "sh", "ss": "sh", "sz": "sz", "bj": "bj"}.get(suffix)
    if sep and market is None:
        # A suffix that is present and unrecognised must not fall through to
        # guessing from the digits: `000651.SH` would resolve to sh000651, a
        # Shanghai index, and return a different instrument's price.
        raise AdapterError(
            f"{code!r} carries an exchange suffix this endpoint does not "
            f"recognise. Use .SH, .SS, .SZ or .BJ, or drop the suffix."
        )
    if market is None and digits.isdigit() and len(digits) == 6:
        if digits[:2] in ("60", "68") or digits[0] == "9":
            market = "sh"
        elif digits[:2] in ("00", "30", "20"):
            market = "sz"
        elif digits[:2] in ("43", "83", "87", "88", "92"):
            market = "bj"
    if market is None or not digits.isdigit():
        raise AdapterError(
            f"{code!r} is not a code this endpoint serves. Expected a six-digit "
            f"A-share code, optionally suffixed, e.g. '600519.SH'."
        )
    return f"{market}{digits}"


def _fetch_fields(code: str) -> list:
    url = _URL.format(code=code)
    request = urllib.request.Request(url, headers=_HEADERS)
    try:
        with urllib.request.urlopen(request, timeout=DEFAULT_TIMEOUT) as response:
            # GBK, not UTF-8. Decoding as UTF-8 corrupts the name field, and a
            # corrupted name is the kind of thing that reaches a report.
            body = response.read().decode("gbk", "replace")
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
        raise AdapterError(f"could not reach Tencent for {code}: {exc}") from exc

    _, _, payload = body.partition("=")
    fields = payload.strip().rstrip(";").strip('"').split("~")
    if len(fields) < _MIN_FIELDS or not fields[_PRICE]:
        raise AdapterError(
            f"Tencent returned nothing usable for {code}. The code may not "
            f"exist, or the endpoint's shape has changed — it is unofficial."
        )
    return fields


def _price(fields: list, code: str) -> float:
    try:
        value = float(fields[_PRICE])
    except (TypeError, ValueError) as exc:
        raise AdapterError(
            f"Tencent's price for {code} is not a number: {fields[_PRICE]!r}"
        ) from exc
    if value <= 0:
        raise AdapterError(
            f"Tencent reports {code} at {value}, which means suspended or "
            f"delisted rather than free. Every per-share figure is a ratio "
            f"against this."
        )
    return value


def _as_of(fields: list) -> datetime:
    """The stamp is Beijing local time, `YYYYMMDDHHMMSS`, with no zone marker."""
    raw = (fields[_STAMP] or "").strip()
    try:
        naive = datetime.strptime(raw[:14], "%Y%m%d%H%M%S")
    except ValueError:
        return datetime.now(timezone.utc)
    return naive.replace(tzinfo=_BEIJING).astimezone(timezone.utc)


def shares_outstanding(code: str):
    """Shares implied by market capitalisation over price, or None.

    Returns None rather than raising: this is a fallback for another adapter's
    share count, and a source that cannot answer should let the next one try.
    """
    try:
        symbol = normalise(code)
        fields = _fetch_fields(symbol)
        cap_yi = float(fields[_MARKET_CAP])
        shares = cap_yi * 1e8 / _price(fields, symbol)
    except (AdapterError, TypeError, ValueError, IndexError) as exc:
        _log.warning("Tencent could not supply a share count for %s (%s)", code, exc)
        return None
    return shares if shares >= _MIN_PLAUSIBLE_SHARES else None


class TencentAdapter(Adapter):
    """A-share, Hong Kong and US quotes, free and without a key."""

    def __init__(self):
        super().__init__(name=SOURCE, domain=DOMAIN)

    def fetch(self, key: str, **kwargs) -> list:
        symbol = normalise(key)
        currency = _MARKETS[symbol[:2]]
        fields = _fetch_fields(symbol)
        price = _price(fields, symbol)
        as_of = _as_of(fields)

        # Same rule as the Yahoo adapter: a live print gets the one-hour limit,
        # a settled close gets the daily one, because a close is the last price
        # there is until the next session rather than a stale one.
        age = datetime.now(timezone.utc) - as_of
        freq, state = (("intraday", "live print") if age <= _LIVE_WINDOW
                       else ("daily", "session close"))

        return [as_fact(
            name=f"{key.strip().upper()}_price",
            value=price,
            unit="usd",
            currency=currency,
            freq=freq,
            as_of=as_of.isoformat(),
            source=SOURCE,
            entity=key.strip().upper(),
            note=f"tencent:{symbol}, {state}",
        )]
