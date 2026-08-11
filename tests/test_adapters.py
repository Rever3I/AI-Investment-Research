"""Market data adapters.

Every network call is stubbed. A test suite that reaches the internet fails on a
plane, fails in CI without egress, and fails when a provider has an outage that
has nothing to do with the code — so the fixtures here are real response shapes,
captured from live calls, replayed offline.

The XBRL fixtures are the important ones. Two bugs found against live SEC data
are pinned here: a tag a company abandoned in 2020 winning over the one it uses
now, and year-to-date cumulative figures being summed as if they were discrete
quarters.
"""

import json

import pytest

from skills._lib.data.adapters import base
from skills._lib.data.adapters.base import (
    Adapter,
    AdapterError,
    AdapterUnavailable,
    Chain,
    as_fact,
    describe,
    register,
)
from skills._lib.data.adapters import status_report
from skills._lib.data.adapters.macro_fred import FREDAdapter
from skills._lib.data.adapters.prices import StooqAdapter, YahooAdapter
from skills._lib.data.adapters.us_sec import SECAdapter


@pytest.fixture(autouse=True)
def clean_registry(monkeypatch):
    monkeypatch.setattr(base, "_REGISTRY", {})


# ── the chain ─────────────────────────────────────────────────────

class _Stub(Adapter):
    def __init__(self, name, facts=None, error=None, available=True):
        super().__init__(name=name, domain="test")
        self._facts = facts or []
        self._error = error
        self._available = available
        self.calls = 0

    def available(self):
        return self._available

    def unavailable_reason(self):
        return "" if self._available else "stub is switched off"

    def fetch(self, key, **kwargs):
        self.calls += 1
        if self._error:
            raise self._error
        return self._facts


def _fact(name="X_price", value=100):
    return as_fact(name=name, value=value, unit="usd", freq="point",
                   as_of="2026-08-04T12:00:00Z", source="stub", entity="X")


def test_the_primary_answers_and_the_fallback_is_not_called():
    primary = _Stub("primary", facts=[_fact()])
    fallback = _Stub("fallback", facts=[_fact()])
    Chain(domain="test", adapters=[primary, fallback]).fetch("X")
    assert primary.calls == 1
    assert fallback.calls == 0


def test_a_failing_primary_falls_through():
    primary = _Stub("primary", error=AdapterError("upstream is down"))
    fallback = _Stub("fallback", facts=[_fact()])
    facts = Chain(domain="test", adapters=[primary, fallback]).fetch("X")
    assert facts
    assert fallback.calls == 1


def test_an_unavailable_adapter_is_skipped_without_being_called():
    primary = _Stub("primary", available=False)
    fallback = _Stub("fallback", facts=[_fact()])
    Chain(domain="test", adapters=[primary, fallback]).fetch("X")
    assert primary.calls == 0
    assert fallback.calls == 1


def test_falling_back_is_logged(caplog):
    """A primary that quietly always fails looks exactly like one that works,
    right up until the fallback fails too."""
    import logging

    chain = Chain(domain="test", adapters=[
        _Stub("primary", error=AdapterError("boom")),
        _Stub("fallback", facts=[_fact()]),
    ])
    with caplog.at_level(logging.WARNING):
        chain.fetch("X")
    assert any("fallback" in r.getMessage() for r in caplog.records)


def test_an_empty_answer_is_treated_as_a_failure():
    """Returning nothing is not answering; the chain keeps going."""
    empty = _Stub("empty", facts=[])
    real = _Stub("real", facts=[_fact()])
    Chain(domain="test", adapters=[empty, real]).fetch("X")
    assert real.calls == 1


def test_an_exhausted_chain_reports_every_reason():
    chain = Chain(domain="test", adapters=[
        _Stub("a", error=AdapterError("no route")),
        _Stub("b", available=False),
    ])
    with pytest.raises(AdapterError) as excinfo:
        chain.fetch("X")
    message = str(excinfo.value)
    assert "no route" in message
    assert "switched off" in message


def test_an_empty_chain_says_so():
    with pytest.raises(AdapterError):
        Chain(domain="test", adapters=[]).fetch("X")


# ── adapters return Facts, never bare numbers ─────────────────────

def test_a_value_that_cannot_be_a_fact_fails_as_an_adapter_error():
    """A FactError escaping an adapter sends the caller looking at their own
    inputs rather than at the source that returned something unusable."""
    with pytest.raises(AdapterError) as excinfo:
        as_fact(name="X", value="not a number", unit="usd", freq="daily",
                as_of="2026-08-04T12:00:00Z", source="stub")
    assert "stub" in str(excinfo.value)


def test_a_fact_carries_its_provenance():
    fact = _fact()
    assert fact.source == "stub"
    assert fact.as_of.endswith("+00:00")


# ── the status report ─────────────────────────────────────────────

def test_the_status_report_names_what_to_configure():
    register(Chain(domain="test", adapters=[_Stub("offline", available=False)]))
    report = status_report(describe())
    assert "not configured" in report
    assert "switched off" in report


def test_the_status_report_marks_primary_and_fallback():
    register(Chain(domain="test", adapters=[
        _Stub("first", facts=[_fact()]), _Stub("second", facts=[_fact()]),
    ]))
    rows = describe()
    assert rows[0]["role"] == "primary"
    assert rows[1]["role"] == "fallback 1"


# ── SEC: availability ─────────────────────────────────────────────

def test_sec_without_a_contact_is_unavailable_and_says_why():
    adapter = SECAdapter(contact="")
    assert adapter.available() is False
    assert "sec_contact" in adapter.unavailable_reason()


def test_sec_rejects_a_contact_with_no_email():
    assert SECAdapter(contact="Jane Roe").available() is False


def test_sec_with_a_contact_is_available():
    assert SECAdapter(contact="Jane Roe jane@example.com").available() is True


def test_sec_refuses_to_fetch_without_a_contact():
    with pytest.raises(AdapterUnavailable):
        SECAdapter(contact="").fetch("NVDA")


# ── SEC: the tag-selection bugs found against live data ───────────

def _facts_payload(tags: dict) -> dict:
    return {"facts": {"us-gaap": tags, "dei": {}}}


def _annual(end, val, start=None):
    year = int(end[:4])
    return {"start": start or f"{year - 1}{end[4:]}", "end": end, "val": val,
            "fp": "FY", "form": "10-K"}


def _quarter(start, end, val):
    return {"start": start, "end": end, "val": val, "fp": "Q1", "form": "10-Q"}


def test_the_freshest_tag_wins_over_the_first_listed(monkeypatch):
    """NVDA stopped filing capital expenditure under
    PaymentsToAcquirePropertyPlantAndEquipment in 2020 and moved to
    PaymentsToAcquireProductiveAssets. A first-match rule returned the abandoned
    tag's last value, six years stale, looking entirely normal."""
    payload = _facts_payload({
        "NetIncomeLoss": {"units": {"USD": [_annual("2026-01-25", 120)]}},
        # first in the candidate list, abandoned in 2020
        "PaymentsToAcquirePropertyPlantAndEquipment": {
            "units": {"USD": [_annual("2020-07-26", 1)]}},
        # second in the list, current
        "PaymentsToAcquireProductiveAssets": {
            "units": {"USD": [_annual("2026-01-25", 6)]}},
    })
    adapter = _stubbed_sec(monkeypatch, payload)
    facts = {f.name: f for f in adapter.fetch("NVDA")}
    capex = facts["NVDA_capital_expenditure"]
    assert capex.value == 6
    assert capex.as_of.startswith("2026")
    assert "ProductiveAssets" in capex.note


def test_year_to_date_entries_are_not_summed_as_quarters(monkeypatch):
    """XBRL "Q3" entries usually cover the nine months from the start of the
    year. Summing four of those is not a trailing twelve months, it is roughly
    triple one."""
    cumulative = [
        _quarter("2026-01-27", "2026-04-26", 155),   # 89 days, a real quarter
        _quarter("2026-01-27", "2026-07-26", 372),   # 180 days, H1 cumulative
        _quarter("2026-01-27", "2026-10-27", 590),   # 273 days, 9M cumulative
        _quarter("2026-01-27", "2027-01-25", 800),   # 364 days, full year
    ]
    payload = _facts_payload({
        "NetIncomeLoss": {"units": {"USD": cumulative}},
    })
    adapter = _stubbed_sec(monkeypatch, payload)
    fact = adapter.fetch("NVDA")[0]
    # Naive summation would give 1917. The only entries that are real periods
    # are the 89-day quarter and the 364-day year, and the year is the answer.
    assert fact.value == 800
    assert fact.freq == "annual"


def test_four_discrete_quarters_become_a_trailing_twelve_months(monkeypatch):
    quarters = [
        _quarter("2025-04-28", "2025-07-27", 10),
        _quarter("2025-07-28", "2025-10-26", 20),
        _quarter("2025-10-27", "2026-01-25", 30),
        _quarter("2026-01-26", "2026-04-26", 40),
    ]
    payload = _facts_payload({"NetIncomeLoss": {"units": {"USD": quarters}}})
    adapter = _stubbed_sec(monkeypatch, payload)
    fact = adapter.fetch("NVDA")[0]
    assert fact.value == 100
    assert fact.freq == "ttm"
    assert fact.as_of.startswith("2026-04-26")


def test_restated_quarters_are_not_double_counted(monkeypatch):
    """The same quarter appears in several filings. Counting each occurrence
    multiplies the answer."""
    quarters = [
        _quarter("2025-04-28", "2025-07-27", 10),
        _quarter("2025-04-28", "2025-07-27", 10),   # restatement, same period
        _quarter("2025-07-28", "2025-10-26", 20),
        _quarter("2025-10-27", "2026-01-25", 30),
        _quarter("2026-01-26", "2026-04-26", 40),
    ]
    payload = _facts_payload({"NetIncomeLoss": {"units": {"USD": quarters}}})
    fact = _stubbed_sec(monkeypatch, payload).fetch("NVDA")[0]
    assert fact.value == 100


def test_quarters_with_a_gap_are_not_called_a_year(monkeypatch):
    """Four quarters spanning two years is not twelve months, and treating it
    as one understates every ratio built on top."""
    quarters = [
        _quarter("2023-04-28", "2023-07-27", 10),
        _quarter("2025-07-28", "2025-10-26", 20),
        _quarter("2025-10-27", "2026-01-25", 30),
        _quarter("2026-01-26", "2026-04-26", 40),
    ]
    payload = _facts_payload({"NetIncomeLoss": {"units": {"USD": quarters}}})
    fact = _stubbed_sec(monkeypatch, payload).fetch("NVDA")[0]
    assert fact.freq != "ttm"


def test_a_point_in_time_value_is_not_annualised(monkeypatch):
    """Shares outstanding is a level, not a flow: nothing to sum."""
    payload = _facts_payload({
        "NetIncomeLoss": {"units": {"USD": [_annual("2026-01-25", 120)]}},
        "CommonStockSharesOutstanding": {
            "units": {"shares": [{"end": "2026-01-25", "val": 24_304_000_000,
                                  "form": "10-K"}]}},
    })
    facts = {f.name: f for f in _stubbed_sec(monkeypatch, payload).fetch("NVDA")}
    shares = facts["NVDA_shares_outstanding"]
    assert shares.value == 24_304_000_000
    assert shares.freq == "point"


def test_owner_earnings_inputs_share_a_group(monkeypatch):
    """The Fact contract's frequency check only fires within a group, and a
    quarterly figure divided by a trailing-twelve-month one is the classic way a
    valuation comes out four times wrong."""
    payload = _facts_payload({
        "NetIncomeLoss": {"units": {"USD": [_annual("2026-01-25", 120)]}},
        "DepreciationDepletionAndAmortization": {
            "units": {"USD": [_annual("2026-01-25", 3)]}},
    })
    for fact in _stubbed_sec(monkeypatch, payload).fetch("NVDA"):
        assert fact.group == "owner_earnings"


def test_a_company_with_no_known_tags_says_what_to_do(monkeypatch):
    payload = _facts_payload({"SomethingElse": {"units": {"USD": [_annual("2026-01-25", 1)]}}})
    with pytest.raises(AdapterError) as excinfo:
        _stubbed_sec(monkeypatch, payload).fetch("NVDA")
    assert "CONCEPTS" in str(excinfo.value)


def test_an_unknown_ticker_is_explained(monkeypatch):
    from skills._lib.data.adapters import us_sec

    monkeypatch.setattr(us_sec, "get_json", lambda *a, **k: {})
    monkeypatch.setattr(us_sec, "cache_get", lambda *a, **k: None)
    monkeypatch.setattr(us_sec, "cache_put", lambda *a, **k: None)
    adapter = SECAdapter(contact="Jane Roe jane@example.com")
    with pytest.raises(AdapterError) as excinfo:
        adapter.fetch("NOTATICKER")
    assert "foreign issuer" in str(excinfo.value)


def _stubbed_sec(monkeypatch, payload):
    from skills._lib.data.adapters import us_sec

    monkeypatch.setattr(us_sec, "cache_get", lambda *a, **k: None)
    monkeypatch.setattr(us_sec, "cache_put", lambda *a, **k: None)

    def fake_get_json(url, **kwargs):
        if "company_tickers" in url:
            return {"0": {"ticker": "NVDA", "cik_str": 1045810}}
        return payload

    monkeypatch.setattr(us_sec, "get_json", fake_get_json)
    return SECAdapter(contact="Jane Roe jane@example.com")


# ── FRED ──────────────────────────────────────────────────────────

def test_fred_without_a_key_is_unavailable_and_says_where_to_get_one():
    adapter = FREDAdapter(api_key="")
    assert adapter.available() is False
    assert "fredaccount.stlouisfed.org" in adapter.unavailable_reason()


def test_fred_refuses_an_unknown_series():
    adapter = FREDAdapter(api_key="k")
    with pytest.raises(AdapterError) as excinfo:
        adapter.fetch("not_a_series")
    assert "us_10y" in str(excinfo.value)


def test_fred_returns_a_yield_as_a_percent_fact(monkeypatch):
    """FRED publishes yields in percent, and converting to a fraction here would
    hide the unit from the check that catches unit errors."""
    from skills._lib.data.adapters import macro_fred

    monkeypatch.setattr(macro_fred, "cache_put", lambda *a, **k: None)
    monkeypatch.setattr(macro_fred, "get_json", lambda *a, **k: {
        "observations": [{"date": "2026-08-04", "value": "4.23"}]})
    fact = FREDAdapter(api_key="k").fetch("us_10y")[0]
    assert fact.value == 4.23
    assert fact.unit == "pct"
    assert fact.as_of.startswith("2026-08-04")


def test_fred_explains_a_market_holiday(monkeypatch):
    """FRED writes '.' for a day with no print."""
    from skills._lib.data.adapters import macro_fred

    monkeypatch.setattr(macro_fred, "cache_put", lambda *a, **k: None)
    monkeypatch.setattr(macro_fred, "get_json", lambda *a, **k: {
        "observations": [{"date": "2026-07-04", "value": "."}]})
    with pytest.raises(AdapterError) as excinfo:
        FREDAdapter(api_key="k").fetch("us_10y")
    assert "closed" in str(excinfo.value)


# ── prices ────────────────────────────────────────────────────────

def test_yahoo_parses_a_quote(monkeypatch):
    from skills._lib.data.adapters import prices

    monkeypatch.setattr(prices, "get_json", lambda *a, **k: {
        "chart": {"result": [{"meta": {"regularMarketPrice": 219.15,
                                       "regularMarketTime": 1786000000,
                                       "currency": "USD"}}]}})
    fact = YahooAdapter().fetch("NVDA")[0]
    assert fact.value == 219.15
    assert fact.freq == "intraday"
    assert fact.entity == "NVDA"


def test_yahoo_says_so_when_the_shape_changes(monkeypatch):
    """This endpoint is unofficial. A silent None would become a price of zero
    somewhere downstream."""
    from skills._lib.data.adapters import prices

    monkeypatch.setattr(prices, "get_json", lambda *a, **k: {"chart": {"result": []}})
    with pytest.raises(AdapterError) as excinfo:
        YahooAdapter().fetch("NVDA")
    assert "unofficial" in str(excinfo.value)


def test_the_two_yahoo_hosts_are_distinguishable():
    """Two chain entries that look identical hide which one answered."""
    from skills._lib.data.adapters.prices import _YAHOO_HOSTS

    names = {YahooAdapter(host).name for host in _YAHOO_HOSTS}
    assert len(names) == len(_YAHOO_HOSTS)


def test_stooq_adds_the_market_suffix_callers_forget(monkeypatch):
    import io
    from skills._lib.data.adapters import prices

    captured = {}

    class _Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(url, timeout=None):
        captured["url"] = url
        return _Response(b"Symbol,Date,Time,Open,High,Low,Close,Volume\n"
                         b"NVDA.US,2026-08-04,20:00:00,1,2,3,219.15,100\n")

    monkeypatch.setattr(prices.urllib.request, "urlopen", fake_urlopen)
    fact = StooqAdapter().fetch("NVDA")[0]
    assert "nvda.us" in captured["url"]
    assert fact.value == 219.15


def test_stooq_explains_an_unknown_symbol(monkeypatch):
    import io
    from skills._lib.data.adapters import prices

    class _Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(
        prices.urllib.request, "urlopen",
        lambda url, timeout=None: _Response(
            b"Symbol,Date,Time,Open,High,Low,Close,Volume\n"
            b"XYZ.US,N/D,N/D,N/D,N/D,N/D,N/D,N/D\n"),
    )
    with pytest.raises(AdapterError) as excinfo:
        StooqAdapter().fetch("XYZ")
    assert "suffix" in str(excinfo.value)


# ── Wind, which cannot be exercised here ──────────────────────────

def test_wind_without_the_terminal_is_unavailable_and_explains_why():
    from skills._lib.data.adapters.cn_wind import WindAdapter

    adapter = WindAdapter()
    assert adapter.available() is False
    assert "licensed" in adapter.unavailable_reason()


def test_wind_builds_facts_from_a_response_shape():
    """The parts that do not need a terminal are checked with a stub. The live
    integration is not verified — see the module docstring."""
    from skills._lib.data.adapters.cn_wind import WindAdapter

    class _Client:
        ErrorCode = 0

        def isconnected(self):
            return True

        def wss(self, codes, fields, options):
            class _Response:
                ErrorCode = 0
                Fields = ["NP_BELONGTO_PARCOMSH", "TOTAL_SHARES"]
                Data = [[1_000_000.0], [5_000_000.0]]
                Times = []
            return _Response()

    facts = {f.name: f for f in WindAdapter(client=_Client()).fetch("600519.SH")}
    assert facts["600519.SH_net_income"].value == 1_000_000.0
    assert facts["600519.SH_shares_outstanding"].unit == "shares"


def test_wind_surfaces_its_error_codes():
    from skills._lib.data.adapters.cn_wind import WindAdapter

    class _Client:
        def isconnected(self):
            return True

        def wss(self, *a, **k):
            class _Response:
                ErrorCode = 40520007
                Fields = []
                Data = []
            return _Response()

    with pytest.raises(AdapterError) as excinfo:
        WindAdapter(client=_Client()).fetch("BADCODE")
    assert "40520007" in str(excinfo.value)


# ── configure() ───────────────────────────────────────────────────

def test_configure_registers_every_domain():
    from skills._lib.data.adapters import configure

    rows = configure(profile={})
    assert {row["domain"] for row in rows} == {
        "us_equity", "cn_equity", "macro", "price"}


def test_configure_reports_what_cannot_run_rather_than_raising():
    """A fresh clone with no credentials must import and report, not fail."""
    from skills._lib.data.adapters import configure

    rows = configure(profile={})
    unavailable = [row for row in rows if not row["available"]]
    assert unavailable
    assert all(row["reason"] for row in unavailable)


def test_prices_work_with_no_configuration_at_all():
    """The number most often wanted on an unconfigured machine."""
    from skills._lib.data.adapters import configure

    rows = configure(profile={})
    price_rows = [row for row in rows if row["domain"] == "price"]
    assert all(row["available"] for row in price_rows)


def test_credentials_from_the_profile_reach_their_adapters():
    from skills._lib.data.adapters import configure

    rows = configure(profile={"sec_contact": "Jane Roe jane@example.com",
                              "fred_api_key": "k"})
    ready = {row["domain"] for row in rows if row["available"]}
    assert {"us_equity", "macro"} <= ready
