"""A-share fundamentals without a Wind licence.

Every response here is the real shape, captured from live calls against
Kweichow Moutai and Gree, replayed offline. The numbers are the real ones,
because the three traps this adapter exists to avoid are all cases where the
wrong figure is entirely plausible.
"""

import pytest

from airesearch.data.adapters.base import AdapterError
from airesearch.data.adapters.cn_eastmoney import EastmoneyAdapter

# Kweichow Moutai, FY2025, as filed.
MOUTAI_CASHFLOW = {
    "REPORT_DATE": "2025-12-31 00:00:00",
    "CURRENCY": "CNY",
    "FA_IR_DEPR": 3_786_676_624.0,
    "OILGAS_BIOLOGY_DEPR": None,
    "IA_AMORTIZE": 289_613_683.0,
    "LPE_AMORTIZE": 20_637_734.0,
    "USERIGHT_ASSET_AMORTIZE": 55_797_325.0,
    "CONSTRUCT_LONG_ASSET": 3_127_594_916.0,
}
MOUTAI_INCOME = {
    "REPORT_DATE": "2025-12-31 00:00:00",
    "PARENT_NETPROFIT": 82_320_067_102.0,
    "BASIC_EPS": 66.0,
}
MOUTAI_BALANCE = {"SHARE_CAPITAL": 1_252_270_215.0}
MOUTAI_QUOTE = {"data": {"f57": "600519", "f58": "贵州茅台",
                         "f84": 1_250_081_601.0, "f43": 134300}}


def _stub(monkeypatch, cashflow=None, income=None, balance=None, quote=None,
          quote_error=None):
    """Route a stubbed get_json by which endpoint the URL names."""
    from airesearch.data.adapters import cn_eastmoney

    def fake(url, headers=None, timeout=None):
        if "push2" in url:
            if quote_error:
                raise quote_error
            return quote if quote is not None else MOUTAI_QUOTE
        table = {"GCASHFLOW": cashflow, "GINCOME": income, "GBALANCE": balance}
        for marker, row in table.items():
            if marker in url:
                return {"result": {"data": [row]} if row else None}
        raise AssertionError(f"unexpected url {url}")

    monkeypatch.setattr(cn_eastmoney, "get_json", fake)
    return EastmoneyAdapter()


def _moutai(monkeypatch, **overrides):
    kwargs = dict(cashflow=dict(MOUTAI_CASHFLOW), income=dict(MOUTAI_INCOME),
                  balance=dict(MOUTAI_BALANCE))
    kwargs.update(overrides)
    return _stub(monkeypatch, **kwargs)


def _by_concept(facts):
    return {f.name.split("_", 1)[1]: f for f in facts}


# ── codes arrive in whatever shape the user's broker uses ─────────

@pytest.mark.parametrize("given,expected", [
    ("600519", ("600519.SH", "1.600519")),
    ("600519.SH", ("600519.SH", "1.600519")),
    ("600519.SS", ("600519.SH", "1.600519")),   # Yahoo's suffix for Shanghai
    ("sh600519", ("600519.SH", "1.600519")),
    (" 600519.sh ", ("600519.SH", "1.600519")),
    ("000651", ("000651.SZ", "0.000651")),
    ("300750.SZ", ("300750.SZ", "0.300750")),
])
def test_a_code_normalises(given, expected):
    assert EastmoneyAdapter._split(given) == expected


@pytest.mark.parametrize("given", ["AAPL", "60051", "6005190", ""])
def test_something_that_is_not_an_a_share_code_is_refused(given):
    with pytest.raises(AdapterError):
        EastmoneyAdapter._split(given)


def test_an_unrecognised_prefix_asks_for_the_suffix_rather_than_guessing():
    """Guessing the exchange returns another company's filings."""
    with pytest.raises(AdapterError) as excinfo:
        EastmoneyAdapter._split("123456")
    assert ".SH" in str(excinfo.value)


# ── depreciation is spread across fields ──────────────────────────

def test_depreciation_sums_every_field_that_is_present(monkeypatch):
    facts = _by_concept(_moutai(monkeypatch).fetch("600519"))
    assert facts["depreciation_amortisation"].value == pytest.approx(4_152_725_366.0)


def test_the_fixed_asset_line_missing_is_refused_rather_than_summed(monkeypatch):
    """Without FA_IR_DEPR the remaining amortisation fields sum to CNY 366m
    against a real CNY 4.15bn — eleven times too small, and still an entirely
    ordinary-looking depreciation figure."""
    cashflow = dict(MOUTAI_CASHFLOW, FA_IR_DEPR=None)
    with pytest.raises(AdapterError) as excinfo:
        _moutai(monkeypatch, cashflow=cashflow).fetch("600519")
    assert "FA_IR_DEPR" in str(excinfo.value)


def test_a_company_reporting_only_two_fields_still_works(monkeypatch):
    """Gree files fixed-asset depreciation and intangible amortisation, nothing
    else. Requiring the full set would refuse a company that filed correctly."""
    cashflow = dict(MOUTAI_CASHFLOW, OILGAS_BIOLOGY_DEPR=None,
                    LPE_AMORTIZE=None, USERIGHT_ASSET_AMORTIZE=None)
    facts = _by_concept(_moutai(monkeypatch, cashflow=cashflow).fetch("600519"))
    da = facts["depreciation_amortisation"]
    assert da.value == pytest.approx(3_786_676_624.0 + 289_613_683.0)
    assert "FA_IR_DEPR" in da.note and "LPE_AMORTIZE" not in da.note


# ── two share counts that disagree ────────────────────────────────

def test_the_live_share_count_is_preferred(monkeypatch):
    """It is the count as of today, which is what a per-share figure quoted
    today divides by. The balance sheet's is the year-end registration."""
    facts = _by_concept(_moutai(monkeypatch).fetch("600519"))
    assert facts["shares_outstanding"].value == 1_250_081_601.0


def test_registered_capital_stands_in_when_the_quote_endpoint_is_down(monkeypatch):
    """push2 returned 502 repeatedly while this was being built, so the
    fallback is the normal path rather than a rare one."""
    facts = _by_concept(_moutai(
        monkeypatch, quote_error=OSError("502 Bad Gateway")).fetch("600519"))
    shares = facts["shares_outstanding"]
    assert shares.value == 1_252_270_215.0
    assert "SHARE_CAPITAL" in shares.note


def test_registered_capital_at_a_different_par_value_is_refused(monkeypatch):
    """Registered capital is a share count only at a par value of CNY 1. At
    CNY 0.1 it is ten times the share count and still a plausible one."""
    with pytest.raises(AdapterError) as excinfo:
        _moutai(monkeypatch,
                balance={"SHARE_CAPITAL": 12_522_702_150.0},
                quote_error=OSError("502")).fetch("600519")
    assert "par value" in str(excinfo.value)


def test_no_share_count_anywhere_is_refused(monkeypatch):
    """Every per-share figure divides by this number."""
    with pytest.raises(AdapterError) as excinfo:
        _moutai(monkeypatch, balance={"SHARE_CAPITAL": None},
                quote_error=OSError("502")).fetch("600519")
    assert "share count" in str(excinfo.value)


# ── what it refuses ───────────────────────────────────────────────

def test_a_bank_is_told_the_method_does_not_apply(monkeypatch):
    """Banks file a different report series and return nothing here. The
    refusal is right; leaving it as an empty response is not."""
    with pytest.raises(AdapterError) as excinfo:
        _stub(monkeypatch, cashflow=None, income=None).fetch("601398.SH")
    assert "Banks" in str(excinfo.value)


def test_a_report_in_another_currency_is_refused(monkeypatch):
    with pytest.raises(AdapterError) as excinfo:
        _moutai(monkeypatch,
                cashflow=dict(MOUTAI_CASHFLOW, CURRENCY="HKD")).fetch("600519")
    assert "HKD" in str(excinfo.value)


def test_a_report_past_the_age_limit_is_refused(monkeypatch):
    """A delisted company's last annual filing must not arrive looking current."""
    with pytest.raises(AdapterError) as excinfo:
        _moutai(monkeypatch,
                cashflow=dict(MOUTAI_CASHFLOW,
                              REPORT_DATE="2019-12-31 00:00:00")).fetch("600519")
    assert "2019-12-31" in str(excinfo.value)


@pytest.mark.parametrize("field,label", [
    ("CONSTRUCT_LONG_ASSET", "capital expenditure"),
])
def test_a_missing_cashflow_term_refuses_rather_than_returning_a_partial(
        monkeypatch, field, label):
    """A missing term read as zero flatters the company by exactly the amount
    that is absent."""
    with pytest.raises(AdapterError) as excinfo:
        _moutai(monkeypatch,
                cashflow=dict(MOUTAI_CASHFLOW, **{field: None})).fetch("600519")
    assert label in str(excinfo.value)


def test_a_missing_net_income_refuses(monkeypatch):
    with pytest.raises(AdapterError) as excinfo:
        _moutai(monkeypatch,
                income=dict(MOUTAI_INCOME, PARENT_NETPROFIT=None)).fetch("600519")
    assert "net income" in str(excinfo.value)


def test_an_unreadable_report_date_says_the_endpoint_is_unofficial(monkeypatch):
    with pytest.raises(AdapterError) as excinfo:
        _moutai(monkeypatch,
                cashflow=dict(MOUTAI_CASHFLOW, REPORT_DATE="whenever")).fetch("600519")
    assert "unofficial" in str(excinfo.value)


# ── what the facts carry ──────────────────────────────────────────

def test_money_facts_say_they_are_in_yuan(monkeypatch):
    """check_currency_align is what lets a CNY price value a CNY company, and
    it can only see a currency that was recorded."""
    facts = _by_concept(_moutai(monkeypatch).fetch("600519"))
    assert facts["net_income"].currency == "CNY"
    assert facts["capital_expenditure"].currency == "CNY"
    # A share count is not money and must not carry one.
    assert facts["shares_outstanding"].currency == ""


def test_the_owner_earnings_terms_share_a_group(monkeypatch):
    """Sharing a group is what makes the frequency check able to catch a
    quarterly figure mixed in with annual ones."""
    facts = _moutai(monkeypatch).fetch("600519")
    assert {f.group for f in facts} == {"owner_earnings"}


def test_every_fact_names_the_field_it_came_from(monkeypatch):
    facts = _moutai(monkeypatch).fetch("600519")
    assert all(f.note.startswith("eastmoney:") for f in facts)


def test_the_four_owner_earnings_terms_are_all_returned(monkeypatch):
    facts = _by_concept(_moutai(monkeypatch).fetch("600519"))
    assert set(facts) == {"net_income", "depreciation_amortisation",
                          "capital_expenditure", "shares_outstanding"}


def test_owner_earnings_comes_out_where_it_should(monkeypatch):
    """The end-to-end number, against the figures Moutai actually filed."""
    facts = _by_concept(_moutai(monkeypatch).fetch("600519"))
    owner_earnings = (facts["net_income"].value
                      + facts["depreciation_amortisation"].value
                      - facts["capital_expenditure"].value)
    assert owner_earnings == pytest.approx(83_345_197_552.0, rel=1e-9)
    per_share = owner_earnings / facts["shares_outstanding"].value
    assert 60 < per_share < 75, "a plausible per-share owner earnings for Moutai"
