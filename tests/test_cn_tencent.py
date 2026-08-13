"""Tencent quotes, and the share count they imply.

The payload here is the real one, captured live from Kweichow Moutai and Gree:
88 `~`-delimited fields, GBK encoded. Field positions are the whole risk in
this adapter, so the fixtures keep them rather than being trimmed to the few
that are read.
"""

import io
from datetime import datetime, timedelta, timezone

import pytest

from airesearch.data.adapters.base import AdapterError
from airesearch.data.adapters.cn_tencent import (
    TencentAdapter,
    normalise,
    shares_outstanding,
)


def _payload(code="sh600519", name="贵州茅台", price="1343.00",
             stamp="20260812161432", market_cap="16788.60", fields=88):
    """A response shaped like the live one, with the read positions filled."""
    parts = [""] * fields
    parts[0] = "1"
    parts[1] = name
    parts[2] = code[2:]
    parts[3] = price
    parts[30] = stamp
    parts[45] = market_cap
    return f'v_{code}="{"~".join(parts)}";\n'


def _stub(monkeypatch, body=None, error=None):
    from airesearch.data.adapters import cn_tencent

    class _Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake(request, timeout=None):
        if error:
            raise error
        # GBK on the wire, which is the point of one of these tests.
        return _Response((body if body is not None else _payload())
                         .encode("gbk"))

    monkeypatch.setattr(cn_tencent.urllib.request, "urlopen", fake)


def _fresh_stamp(minutes_ago=5):
    """A Beijing-local stamp that is `minutes_ago` old right now."""
    beijing = datetime.now(timezone(timedelta(hours=8)))
    return (beijing - timedelta(minutes=minutes_ago)).strftime("%Y%m%d%H%M%S")


# ── codes ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("given,expected", [
    ("600519", "sh600519"),
    ("600519.SH", "sh600519"),
    ("600519.SS", "sh600519"),      # Yahoo's suffix
    ("sh600519", "sh600519"),
    ("SH600519", "sh600519"),
    ("000651", "sz000651"),
    ("300750.SZ", "sz300750"),
    ("hk00700", "hk00700"),
])
def test_a_code_normalises(given, expected):
    assert normalise(given) == expected


@pytest.mark.parametrize("given", ["AAPL", "12345", "", "600519.XX"])
def test_a_code_this_endpoint_does_not_serve_is_refused(given):
    with pytest.raises(AdapterError):
        normalise(given)


def test_an_unrecognised_suffix_does_not_fall_back_to_guessing():
    """`000651.SH` inferred from its digits resolves to sh000651, a Shanghai
    index rather than Gree, and returns a different instrument's price at a
    plausible-looking level."""
    with pytest.raises(AdapterError) as excinfo:
        normalise("000651.XSHG")
    assert "suffix" in str(excinfo.value)


# ── the response ──────────────────────────────────────────────────

def test_the_payload_is_decoded_as_gbk(monkeypatch):
    """Decoding as UTF-8 corrupts the name, and a corrupted name is the kind of
    thing that reaches a report."""
    _stub(monkeypatch)
    assert TencentAdapter().fetch("600519")[0].value == 1343.00


def test_a_price_comes_back_in_the_market_s_currency(monkeypatch):
    _stub(monkeypatch)
    assert TencentAdapter().fetch("600519")[0].currency == "CNY"


def test_a_hong_kong_listing_is_labelled_hkd(monkeypatch):
    _stub(monkeypatch, body=_payload(code="hk00700", name="腾讯控股",
                                     price="461.60", market_cap="42000.00"))
    assert TencentAdapter().fetch("hk00700")[0].currency == "HKD"


def test_a_suspended_stock_is_refused(monkeypatch):
    """Every per-share figure is a ratio against this."""
    _stub(monkeypatch, body=_payload(price="0.00"))
    with pytest.raises(AdapterError) as excinfo:
        TencentAdapter().fetch("600519")
    assert "suspended" in str(excinfo.value)


def test_a_truncated_payload_is_refused_rather_than_indexed(monkeypatch):
    """The endpoint is unofficial; a shape change must not read field 45 of a
    twelve-field array."""
    _stub(monkeypatch, body='v_sh600519="1~贵州茅台~600519~1343.00";\n')
    with pytest.raises(AdapterError) as excinfo:
        TencentAdapter().fetch("600519")
    assert "unofficial" in str(excinfo.value)


def test_an_unreachable_endpoint_is_an_adapter_error(monkeypatch):
    """So the chain moves to the next source rather than raising through."""
    _stub(monkeypatch, error=OSError("connection reset"))
    with pytest.raises(AdapterError):
        TencentAdapter().fetch("600519")


# ── the timestamp is Beijing local ────────────────────────────────

def test_the_stamp_is_read_as_beijing_time(monkeypatch):
    """It carries no zone marker. Reading it as UTC would put every A-share
    quote eight hours in the future, which the Fact contract hard-stops on."""
    _stub(monkeypatch, body=_payload(stamp="20260812161432"))
    fact = TencentAdapter().fetch("600519")[0]
    assert fact.as_of == "2026-08-12T08:14:32+00:00"


def test_a_live_print_and_a_close_are_labelled_differently(monkeypatch):
    _stub(monkeypatch, body=_payload(stamp=_fresh_stamp(minutes_ago=5)))
    assert TencentAdapter().fetch("600519")[0].freq == "intraday"

    _stub(monkeypatch, body=_payload(stamp=_fresh_stamp(minutes_ago=600)))
    fact = TencentAdapter().fetch("600519")[0]
    assert fact.freq == "daily" and "session close" in fact.note


def test_a_close_passes_the_fact_contract(monkeypatch):
    """An A-share seen from another timezone is always outside market hours."""
    from airesearch.factcontract import verify

    _stub(monkeypatch, body=_payload(stamp=_fresh_stamp(minutes_ago=600)))
    assert verify(TencentAdapter().fetch("600519"), record=False)["ok"] is True


# ── the derived share count ───────────────────────────────────────

def test_shares_are_market_cap_over_price(monkeypatch):
    """16,788.60 亿 over CNY 1,343.00. The reference figure from Eastmoney's
    quote endpoint is 1,250,081,601 — this lands within rounding of a number
    published to two decimal places."""
    _stub(monkeypatch)
    derived = shares_outstanding("600519.SH")
    assert derived == pytest.approx(1_250_081_601, rel=1e-5)


def test_a_share_count_that_cannot_be_derived_returns_none(monkeypatch):
    """This is a fallback inside another adapter's chain. Raising would stop
    the run where returning None lets the next source answer."""
    _stub(monkeypatch, error=OSError("502 Bad Gateway"))
    assert shares_outstanding("600519.SH") is None


def test_an_implausibly_small_share_count_is_not_returned(monkeypatch):
    _stub(monkeypatch, body=_payload(market_cap="0.0001"))
    assert shares_outstanding("600519.SH") is None


def test_a_bad_code_does_not_raise_out_of_the_share_lookup(monkeypatch):
    assert shares_outstanding("AAPL") is None


# ── how the pieces fit together ───────────────────────────────────

def test_eastmoney_prefers_the_derived_count_over_year_end_capital(monkeypatch):
    """Registered capital is the count at the last year end. When the live
    endpoint is down, a count derived from today's market cap is closer to what
    a per-share figure quoted today should divide by."""
    from airesearch.data.adapters import cn_eastmoney
    from tests.test_cn_eastmoney import (
        MOUTAI_BALANCE,
        MOUTAI_CASHFLOW,
        MOUTAI_INCOME,
    )

    def fake_get_json(url, headers=None, timeout=None):
        if "push2" in url:
            raise OSError("502 Bad Gateway")
        table = {"GCASHFLOW": MOUTAI_CASHFLOW, "GINCOME": MOUTAI_INCOME,
                 "GBALANCE": MOUTAI_BALANCE}
        for marker, row in table.items():
            if marker in url:
                return {"result": {"data": [row]}}
        raise AssertionError(url)

    monkeypatch.setattr(cn_eastmoney, "get_json", fake_get_json)
    _stub(monkeypatch)

    facts = {f.name.split("_", 1)[1]: f
             for f in cn_eastmoney.EastmoneyAdapter().fetch("600519")}
    shares = facts["shares_outstanding"]
    assert "tencent" in shares.note
    assert shares.value != MOUTAI_BALANCE["SHARE_CAPITAL"]
