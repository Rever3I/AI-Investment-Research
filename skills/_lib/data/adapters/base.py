#!/usr/bin/env python
"""What a market data adapter is, and the rules every one of them follows.

An adapter's job is to return **Facts**, never bare numbers. That is the whole
point of the layer: a figure that arrives without a source, a unit and an as-of
time cannot be verified downstream, and by the time it reaches a valuation
nobody remembers where it came from. Returning `Fact` makes the omission
impossible rather than discouraged.

Two rules that are not optional:

1. **Every domain declares a fallback.** A single source is a single point of
   failure, and the failure mode is not an outage — it is one number quietly
   missing from a report that still looks complete. Adapters are registered in
   chains, and `fetch` walks the chain until something answers.
2. **Nothing is fetched twice inside its own staleness window.** The cache keys
   on what was asked for and when the answer was as of, so a re-run costs
   nothing and a provider's rate limit is not a thing the caller has to think
   about.
"""

import logging
from dataclasses import dataclass, field

from ...factcontract import Fact

_log = logging.getLogger(__name__)


class AdapterError(Exception):
    """An adapter could not answer. The chain moves on to the next one."""


class AdapterUnavailable(AdapterError):
    """The adapter cannot run at all here: no credentials, missing dependency.

    Separate from a fetch failure because it is not worth retrying and the fix
    is a configuration change rather than a wait.
    """


@dataclass
class Adapter:
    """One source for one domain.

    name      short identifier that ends up in `Fact.source`, so provenance is
              legible in the record: "sec-xbrl", "fred", "wind"
    domain    what it serves: "us_equity", "cn_equity", "macro", "news"
    """

    name: str
    domain: str

    def available(self) -> bool:
        """Whether this adapter can run at all in this installation."""
        return True

    def unavailable_reason(self) -> str:
        return ""

    def fetch(self, key: str, **kwargs) -> list:
        """Return a list of Facts for `key`, or raise AdapterError."""
        raise NotImplementedError


@dataclass
class Chain:
    """An ordered list of adapters for one domain, tried in turn.

    The order is the preference order: the first entry is the source you trust
    most, and the rest exist so that trusting it is not the same as depending on
    it.
    """

    domain: str
    adapters: list = field(default_factory=list)

    def fetch(self, key: str, **kwargs) -> list:
        """Walk the chain until one adapter answers.

        Reports every failure it passed, because "the fallback answered" is
        information: a primary that is quietly always failing looks identical to
        one that is working, right up until the fallback fails too.
        """
        if not self.adapters:
            raise AdapterError(f"no adapters registered for domain {self.domain!r}")

        problems = []
        for adapter in self.adapters:
            if not adapter.available():
                problems.append(f"{adapter.name}: {adapter.unavailable_reason()}")
                continue
            try:
                facts = adapter.fetch(key, **kwargs)
            except AdapterError as exc:
                problems.append(f"{adapter.name}: {exc}")
                _log.warning("Adapter %s could not answer for %r: %s",
                             adapter.name, key, exc)
                continue
            if facts:
                if problems:
                    _log.warning(
                        "Answered %r from fallback %s after: %s",
                        key, adapter.name, "; ".join(problems),
                    )
                return facts
            problems.append(f"{adapter.name}: returned nothing")

        raise AdapterError(
            f"no adapter could answer {key!r} for domain {self.domain}. "
            f"Tried: {'; '.join(problems)}"
        )


_REGISTRY = {}


def register(chain: Chain) -> None:
    _REGISTRY[chain.domain] = chain


def get_chain(domain: str) -> Chain:
    if domain not in _REGISTRY:
        raise AdapterError(
            f"no adapters registered for domain {domain!r}. "
            f"Registered: {sorted(_REGISTRY)}"
        )
    return _REGISTRY[domain]


def registered_domains() -> list:
    return sorted(_REGISTRY)


def describe() -> list:
    """What is wired up and what can actually run, for a status report."""
    rows = []
    for domain in sorted(_REGISTRY):
        for position, adapter in enumerate(_REGISTRY[domain].adapters):
            rows.append({
                "domain": domain,
                "adapter": adapter.name,
                "role": "primary" if position == 0 else f"fallback {position}",
                "available": adapter.available(),
                "reason": adapter.unavailable_reason(),
            })
    return rows


def as_fact(name, value, unit, freq, as_of, source, entity="", group="",
            note="") -> Fact:
    """Build a Fact, turning any construction problem into an AdapterError.

    Adapters fail as adapters. A FactError escaping from inside one would send
    the caller looking at their own inputs rather than at the source that
    returned something unusable.
    """
    try:
        return Fact(name=name, value=value, unit=unit, freq=freq, as_of=as_of,
                    source=source, entity=entity, group=group, note=note)
    except Exception as exc:
        raise AdapterError(f"{source} returned a value that is not a usable Fact: {exc}")
