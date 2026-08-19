#!/usr/bin/env python
"""A small HTTP client, and the cache that keeps adapters from re-asking.

stdlib urllib rather than requests, because this package ships with no
dependencies and a research tool that cannot be installed offline is a research
tool nobody installs.

Rate limiting is per host and enforced here rather than in each adapter. SEC
publishes a limit and blocks on it; getting that wrong once means a blocked IP
rather than a slow query, so it is not left to whoever writes the next adapter
to remember.
"""

import json
import logging
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import closing
from pathlib import Path

from ..store_support import connect, dumps, loads, open_for_write, resolve
from .base import AdapterError

_log = logging.getLogger(__name__)

# Minimum seconds between requests to the same host. SEC asks for 10 per second
# and enforces it; the rest is politeness.
_RATE_LIMITS = {
    "www.sec.gov": 0.12,
    "data.sec.gov": 0.12,
    "api.stlouisfed.org": 0.10,
}
_DEFAULT_RATE_LIMIT = 0.25

_last_request = {}

DEFAULT_TIMEOUT = 30


def get_json(url: str, headers: dict = None, timeout: int = DEFAULT_TIMEOUT) -> dict:
    """GET and parse JSON, with one retry on a server-side failure.

    Retries a 5xx once and nothing else: a 404 will still be a 404, and a 403
    from a provider that wants a User-Agent will not fix itself either.
    """
    host = urllib.parse.urlparse(url).netloc
    delay = _RATE_LIMITS.get(host, _DEFAULT_RATE_LIMIT)
    elapsed = time.monotonic() - _last_request.get(host, 0.0)
    if elapsed < delay:
        time.sleep(delay - elapsed)

    request = urllib.request.Request(url, headers=headers or {})
    for attempt in (1, 2):
        try:
            _last_request[host] = time.monotonic()
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read()
                if response.headers.get("Content-Encoding") == "gzip":
                    import gzip
                    raw = gzip.decompress(raw)
                return json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code >= 500 and attempt == 1:
                time.sleep(1.0)
                continue
            raise AdapterError(f"{url} returned HTTP {exc.code}: {exc.reason}") from exc
        except urllib.error.URLError as exc:
            if attempt == 1:
                time.sleep(1.0)
                continue
            raise AdapterError(f"could not reach {url}: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise AdapterError(f"{url} did not return JSON: {exc}") from exc
    raise AdapterError(f"could not reach {url}")


# ── the cache ─────────────────────────────────────────────────────

def cache_get(key: str, domain: str, db_path: Path = None):
    """The most recent cached value for a key, or None.

    Returns whatever was stored along with its `as_of`, and leaves the decision
    about whether that is too old to the Fact contract — which is the component
    that already knows what "too old" means for each frequency, and is the one
    that will hard-stop on it.
    """
    path = resolve(db_path)
    if not Path(path).exists():
        return None
    try:
        with closing(connect(path)) as conn:
            row = conn.execute(
                "SELECT value_json, as_of, source, freq FROM market_cache "
                "WHERE key = ? AND domain = ? ORDER BY as_of DESC, id DESC LIMIT 1",
                (key, domain),
            ).fetchone()
    except sqlite3.OperationalError as exc:
        # A fresh install has the file but not this table: the Fact contract
        # creates the database holding only fact_log. That is a cache miss, not
        # a fault, and reporting it with a traceback made every first run open
        # with a screenful of red.
        if "no such table" in str(exc):
            return None
        _log.warning("Could not read the market cache at %s", path, exc_info=True)
        return None
    except sqlite3.Error:
        _log.warning("Could not read the market cache at %s", path, exc_info=True)
        return None
    if row is None:
        return None
    return {
        "value": loads(row["value_json"], dict),
        "as_of": row["as_of"],
        "source": row["source"],
        "freq": row["freq"],
    }


def cache_put(key: str, domain: str, value: dict, as_of: str, source: str,
              freq: str, db_path: Path = None) -> None:
    """Store an observation. Re-fetching the same one replaces it.

    INSERT OR REPLACE against the UNIQUE(key, domain, as_of) the schema declares,
    so a repeated fetch does not accumulate rows that a later lookup might pick
    the oldest of.
    """
    path = open_for_write(db_path)
    try:
        with closing(connect(path)) as conn:
            conn.execute(
                """INSERT OR REPLACE INTO market_cache
                   (key, domain, value_json, as_of, source, freq)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (key, domain, dumps(value), as_of, source, freq),
            )
            conn.commit()
    except sqlite3.Error:
        # A cache that cannot write is slower, not wrong.
        _log.warning("Could not write the market cache at %s", path, exc_info=True)
