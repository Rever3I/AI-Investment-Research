#!/usr/bin/env python
"""Market data adapters, wired into chains from the user's profile.

`configure()` is the one call a skill needs. It reads whatever credentials the
installation has, builds a chain per domain, and returns a report of what can
actually run — so a layer that cannot get data says which key is missing rather
than failing at the point of use with something unhelpful.

Nothing here fetches at import. An installation with no credentials configured
imports fine and reports itself honestly; that is what lets the pipeline run on
a fresh clone and tell the user what to set up.
"""

from ...config import load_profile
from .base import (
    Adapter,
    AdapterError,
    AdapterUnavailable,
    Chain,
    describe,
    get_chain,
    register,
    registered_domains,
)

__all__ = [
    "Adapter",
    "AdapterError",
    "AdapterUnavailable",
    "Chain",
    "configure",
    "describe",
    "fetch",
    "get_chain",
    "register",
    "registered_domains",
    "status_report",
]


def configure(profile: dict = None, db_path=None) -> list:
    """Register every adapter chain, and report what can run.

    Imports are inside the function so that an adapter whose optional dependency
    is missing cannot break the package for everyone else.
    """
    profile = profile if profile is not None else load_profile()

    from .cn_eastmoney import EastmoneyAdapter
    from .cn_wind import WindAdapter
    from .macro_fred import FREDAdapter
    from .prices import _YAHOO_HOSTS, StooqAdapter, YahooAdapter
    from .us_sec import SECAdapter

    register(Chain(domain="us_equity", adapters=[
        SECAdapter(contact=profile.get("sec_contact", ""), db_path=db_path),
    ]))
    # Eastmoney first because it needs no licence: with Wind alone this domain
    # was unreachable for everyone without a paid terminal, which is most
    # people. Wind stays behind it as the source with a support contract.
    register(Chain(domain="cn_equity", adapters=[
        EastmoneyAdapter(db_path=db_path),
        WindAdapter(),
    ]))
    register(Chain(domain="macro", adapters=[
        FREDAdapter(api_key=profile.get("fred_api_key", ""), db_path=db_path),
    ]))
    # The domain with real redundancy, because a price is the number most often
    # wanted on an unconfigured machine and none of these need a key. Order is
    # what was verified working, not what would be nicest to depend on.
    register(Chain(domain="price", adapters=[
        YahooAdapter(_YAHOO_HOSTS[0]),
        YahooAdapter(_YAHOO_HOSTS[1]),
        StooqAdapter(),
    ]))
    return describe()


def fetch(domain: str, key: str, **kwargs) -> list:
    """Fetch from a domain's chain, falling back through it as needed."""
    return get_chain(domain).fetch(key, **kwargs)


def status_report(rows=None) -> str:
    """A human-readable summary of what is wired up and what can run.

    Written for the case where something is missing, since that is when anyone
    reads it: each unavailable adapter says what to configure.
    """
    rows = rows if rows is not None else describe()
    if not rows:
        return "No adapters registered. Call configure() first."

    lines = []
    for row in rows:
        mark = "ready" if row["available"] else "not configured"
        lines.append(f"  {row['domain']:<10} {row['adapter']:<8} "
                     f"{row['role']:<10} {mark}")
        if row["reason"]:
            lines.append(f"      {row['reason']}")

    usable = {row["domain"] for row in rows if row["available"]}
    missing = sorted({row["domain"] for row in rows} - usable)
    header = f"Adapters: {len(usable)} of {len(usable) + len(missing)} domains ready"
    if missing:
        header += f"; no source for {', '.join(missing)}"

    # Every unavailable adapter's fix is a line in this file, and the file's
    # location depends on the install. Naming it once, here, is what stops the
    # reader from having to work that out from a message about SEC or FRED.
    # `profile_path` and not `ensure_profile`: a report that writes to the
    # user's home as a side effect of being read is its own surprise.
    from ...config import profile_path  # noqa: PLC0415 - avoids an import cycle
    settings = profile_path()
    state = "" if settings.is_file() else "  (not created yet — ensure_profile())"
    return header + "\n" + "\n".join(lines) + f"\nSettings: {settings}{state}"
