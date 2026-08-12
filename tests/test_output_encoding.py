"""Guard the console-safety of everything the Fact contract prints.

The verifier is the component whose whole job is to be a dependable stop. If its
own report cannot be encoded by the terminal the host happens to run under, the
gate becomes the crash. Emoji and CJK in these strings did exactly that on every
default Windows codepage, so the property is pinned here rather than left to a
comment nobody re-reads.
"""

from datetime import timedelta

import pytest

from airesearch.factcontract import Fact, FactCheckError, format_report, verify
from airesearch.factcontract.fact import now_utc

# Codepages a stock Windows console actually uses. cp936 is included because a
# Chinese-locale machine is not a workaround: emoji break there too.
LEGACY_CODEPAGES = ("cp1252", "cp936", "cp437", "ascii")


def _report_with_everything():
    """A report carrying a hard stop and warnings, so every branch is rendered."""
    stale = Fact(name="STALE_pct", value=1.2, unit="pct", freq="daily",
                 as_of="2020-01-01T00:00:00Z", source="sec-xbrl", entity="X")
    absurd = Fact(name="HUGE_pct", value=9000.0, unit="pct", freq="daily",
                  as_of=now_utc().isoformat(), source="sec-xbrl", entity="X")
    mixed_a = Fact(name="NI", value=100, unit="usd", freq="quarterly",
                   as_of=now_utc().isoformat(), source="sec-xbrl",
                   entity="X", group="dcf")
    mixed_b = Fact(name="Shares", value=1e9, unit="shares", freq="ttm",
                   as_of=now_utc().isoformat(), source="sec-xbrl",
                   entity="X", group="dcf")
    return verify([stale, absurd, mixed_a, mixed_b],
                  raise_on_error=False, record=False)


@pytest.mark.parametrize("codepage", LEGACY_CODEPAGES)
def test_format_report_encodes_on_legacy_consoles(codepage):
    rendered = format_report(_report_with_everything())
    rendered.encode(codepage)  # raises UnicodeEncodeError if a symbol crept back in


def test_format_report_renders_both_severities():
    rendered = format_report(_report_with_everything())
    assert "[STOP]" in rendered
    assert "[WARN]" in rendered


@pytest.mark.parametrize("codepage", LEGACY_CODEPAGES)
def test_hard_stop_message_encodes_on_legacy_consoles(codepage):
    """The exception text reaches a traceback, so it needs the same guarantee."""
    stale = Fact(name="STALE_pct", value=1.2, unit="pct", freq="daily",
                 as_of="2020-01-01T00:00:00Z", source="sec-xbrl", entity="X")
    with pytest.raises(FactCheckError) as excinfo:
        verify([stale], record=False)
    str(excinfo.value).encode(codepage)


@pytest.mark.parametrize("codepage", LEGACY_CODEPAGES)
def test_construction_errors_encode_on_legacy_consoles(codepage):
    from airesearch.factcontract import FactError

    for kwargs in (
        {"source": ""},
        {"unit": "bananas"},
        {"freq": "hourly"},
        {"as_of": "last tuesday"},
    ):
        base = dict(name="X_pct", value=1.0, unit="pct", freq="daily",
                    as_of=now_utc().isoformat(), source="sec-xbrl")
        base.update(kwargs)
        with pytest.raises(FactError) as excinfo:
            Fact(**base)
        str(excinfo.value).encode(codepage)


@pytest.mark.parametrize("codepage", LEGACY_CODEPAGES)
def test_future_timestamp_message_encodes_on_legacy_consoles(codepage):
    future = Fact(name="X_pct", value=1.0, unit="pct", freq="daily",
                  as_of=(now_utc() + timedelta(hours=5)).isoformat(),
                  source="sec-xbrl")
    report = verify([future], raise_on_error=False, record=False)
    format_report(report).encode(codepage)
