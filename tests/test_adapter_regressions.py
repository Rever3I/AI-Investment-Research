"""The bugs live SEC and Yahoo data found, pinned so they cannot come back.

Every one of these produced a figure that looked entirely ordinary on the way
into a valuation. None was caught by the Fact contract: a summed share count is
still a plausible number of shares, a quarterly depreciation figure is still a
plausible depreciation figure, and a London price in pence is still a plausible
price. That is what makes them worth a test each.
"""

import pytest

from skills._lib.data.adapters.base import AdapterError
from skills._lib.data.adapters.prices import StooqAdapter, YahooAdapter
from skills._lib.data.adapters.us_sec import SECAdapter


# ── fixtures shaped like the filings that broke ───────────────────

def _facts_payload(tags: dict) -> dict:
    return {"facts": {"us-gaap": tags, "dei": {}}}


def _annual(end, val):
    year = int(end[:4])
    return {"start": f"{year - 1}{end[4:]}", "end": end, "val": val,
            "fp": "FY", "form": "10-K"}


def _quarter(start, end, val):
    return {"start": start, "end": end, "val": val, "fp": "Q1", "form": "10-Q"}


def _weighted_shares(end, val):
    """A weighted-average share count: a duration entry for a stock quantity."""
    year, month, day = (int(x) for x in end.split("-"))
    month -= 3
    if month <= 0:
        month += 12
        year -= 1
    return {"start": f"{year:04d}-{month:02d}-{day:02d}", "end": end,
            "val": val, "fp": "Q1", "form": "10-Q"}


def _complete(**overrides):
    """A payload with every owner-earnings term present, so a test can replace
    exactly the one it is about."""
    tags = {
        "NetIncomeLoss": {"units": {"USD": [_annual("2026-06-30", 100)]}},
        "DepreciationDepletionAndAmortization": {
            "units": {"USD": [_annual("2026-06-30", 10)]}},
        "PaymentsToAcquirePropertyPlantAndEquipment": {
            "units": {"USD": [_annual("2026-06-30", 5)]}},
    }
    tags.update(overrides)
    return _facts_payload(tags)


def _sec(monkeypatch, payload, ticker="X"):
    from skills._lib.data.adapters import us_sec

    monkeypatch.setattr(us_sec, "cache_get", lambda *a, **k: None)
    monkeypatch.setattr(us_sec, "cache_put", lambda *a, **k: None)
    monkeypatch.setattr(us_sec, "get_json", lambda url, **k: (
        {"0": {"ticker": ticker, "cik_str": 1}} if "company_tickers" in url
        else payload))
    return SECAdapter(contact="Jane Roe jane@example.com")


# ── a stock quantity must never be summed ─────────────────────────

def test_a_share_count_is_never_summed_across_quarters(monkeypatch):
    """Simon Property files weighted-average share counts as duration entries.
    Summing four gave 1.30bn against a real 324m, and owner earnings per share
    came out four times too small in the direction that makes a stock look
    overvalued."""
    payload = _complete(**{
        "WeightedAverageNumberOfDilutedSharesOutstanding": {"units": {"shares": [
            _weighted_shares("2025-09-30", 326_485_607),
            _weighted_shares("2025-12-31", 326_180_391),
            _weighted_shares("2026-03-31", 324_961_423),
            _weighted_shares("2026-06-30", 324_018_022),
        ]}},
    })
    facts = {f.name: f for f in _sec(monkeypatch, payload, "SPG").fetch("SPG")}
    shares = facts["SPG_shares_outstanding"]
    assert shares.value < 400_000_000, "four quarters were summed"
    assert shares.freq == "point"


def test_a_share_count_filed_in_millions_is_refused(monkeypatch):
    """McDonald's tags the figure as 716.4. Seven hundred shares outstanding
    produces a per-share value in the millions, and the plausible range for a
    share count is far too wide to notice."""
    payload = _complete(**{
        "CommonStockSharesOutstanding": {"units": {"shares": [
            {"end": "2026-06-30", "val": 716.4, "form": "10-Q"}]}},
    })
    facts = {f.name: f for f in _sec(monkeypatch, payload, "MCD").fetch("MCD")}
    assert "MCD_shares_outstanding" not in facts


# ── period quality outranks recency ───────────────────────────────

def test_an_annual_figure_beats_a_fresher_bare_quarter(monkeypatch):
    """Starbucks files DepreciationDepletionAndAmortization annually and
    Depreciation for one quarter. Ranking on recency alone took the quarter,
    five times too small, and the company then appeared to produce no owner
    earnings at all."""
    payload = _facts_payload({
        "NetIncomeLoss": {"units": {"USD": [_annual("2025-09-28", 1_856_400_000)]}},
        # the annual figure, and the one that should win
        "DepreciationDepletionAndAmortization": {
            "units": {"USD": [_annual("2025-09-28", 1_771_500_000)]}},
        # a single quarter, nine months fresher, five times smaller
        "Depreciation": {"units": {"USD": [
            _quarter("2026-03-29", "2026-06-28", 361_600_000)]}},
        "PaymentsToAcquirePropertyPlantAndEquipment": {
            "units": {"USD": [_annual("2025-09-28", 2_305_500_000)]}},
    })
    facts = {f.name: f for f in _sec(monkeypatch, payload, "SBUX").fetch("SBUX")}
    depreciation = facts["SBUX_depreciation_amortisation"]
    assert depreciation.value == 1_771_500_000
    assert depreciation.freq == "annual"


def test_a_bare_quarter_is_not_emitted_as_an_owner_earnings_input(monkeypatch):
    """A quarterly flow in a group the valuation layer reads as annual is a
    fourfold error, and the frequency check only warns about it."""
    payload = _facts_payload({
        "NetIncomeLoss": {"units": {"USD": [
            _quarter("2026-03-29", "2026-06-28", 14_525_000_000)]}},
    })
    with pytest.raises(AdapterError) as excinfo:
        _sec(monkeypatch, payload).fetch("X")
    assert "net_income" in str(excinfo.value)


# ── a partial set is worse than none ──────────────────────────────

def test_a_missing_term_refuses_rather_than_returning_a_partial(monkeypatch):
    """Banks and REITs often have no capital expenditure line. Returning the
    rest lets the caller compute net income plus depreciation less nothing."""
    payload = _facts_payload({
        "NetIncomeLoss": {"units": {"USD": [_annual("2026-06-30", 100)]}},
        "DepreciationDepletionAndAmortization": {
            "units": {"USD": [_annual("2026-06-30", 10)]}},
    })
    with pytest.raises(AdapterError) as excinfo:
        _sec(monkeypatch, payload, "JPM").fetch("JPM")
    message = str(excinfo.value)
    assert "capital_expenditure" in message
    assert "REIT" in message


def test_a_figure_beyond_the_age_limit_is_refused(monkeypatch):
    """Verizon's only remaining capital expenditure tag is from 2018. The Fact
    contract never checks a point-in-time value at all, so the adapter has to."""
    payload = _complete(**{
        "PaymentsToAcquirePropertyPlantAndEquipment": {
            "units": {"USD": [_annual("2018-12-31", 16_658_000_000)]}},
    })
    with pytest.raises(AdapterError) as excinfo:
        _sec(monkeypatch, payload, "VZ").fetch("VZ")
    assert "capital_expenditure" in str(excinfo.value)


def test_an_ifrs_filer_is_told_what_the_problem_is(monkeypatch):
    payload = {"facts": {"ifrs-full": {"ProfitLoss": {}}}}
    with pytest.raises(AdapterError) as excinfo:
        _sec(monkeypatch, payload, "TSM").fetch("TSM")
    assert "IFRS" in str(excinfo.value)


# ── the duration windows, which surviving mutants exposed ─────────

def test_a_nine_month_cumulative_is_not_reported_as_annual(monkeypatch):
    """Widening the annual window would report three quarters as a full year:
    a 25% understatement that reads as an ordinary figure."""
    payload = _complete(**{
        "NetIncomeLoss": {"units": {"USD": [
            {"start": "2026-01-01", "end": "2026-09-30", "val": 75,
             "fp": "Q3", "form": "10-Q"}]}},
    })
    with pytest.raises(AdapterError) as excinfo:
        _sec(monkeypatch, payload).fetch("X")
    # Specifically net income, not a generic refusal that would also fire if
    # the other terms happened to be missing.
    assert "net_income" in str(excinfo.value)


def test_widening_the_quarter_window_would_resurrect_the_summing_bug(monkeypatch):
    """Four year-to-date entries in one year. If the quarter window admitted
    them they would be summed into roughly triple a year."""
    # Four 120-day entries, none of them a quarter, whose ends span 273 days —
    # so a widened quarter window would accept all four and sum them.
    overlapping = [
        {"start": "2025-10-03", "end": "2026-01-31", "val": 100, "fp": "Q1", "form": "10-Q"},
        {"start": "2025-12-31", "end": "2026-04-30", "val": 220, "fp": "Q2", "form": "10-Q"},
        {"start": "2026-04-02", "end": "2026-07-31", "val": 340, "fp": "Q3", "form": "10-Q"},
        {"start": "2026-07-03", "end": "2026-10-31", "val": 480, "fp": "Q4", "form": "10-Q"},
        _annual("2026-06-30", 900),
    ]
    payload = _complete(**{"NetIncomeLoss": {"units": {"USD": overlapping}}})
    facts = {f.name: f for f in _sec(monkeypatch, payload).fetch("X")}
    # The only real period is the year. Summed, the four would give 1140.
    assert facts["X_net_income"].value == 900
    assert facts["X_net_income"].freq == "annual"


def test_a_fifty_three_week_year_is_still_a_year(monkeypatch):
    """Retailers file 371-day years. Narrowing the window would drop them."""
    long_year = [{"start": "2025-01-28", "end": "2026-02-02", "val": 500,
                  "fp": "FY", "form": "10-K"}]
    payload = _complete(**{"NetIncomeLoss": {"units": {"USD": long_year}}})
    facts = {f.name: f for f in _sec(monkeypatch, payload, "KR").fetch("KR")}
    assert facts["KR_net_income"].freq == "annual"
    assert facts["KR_net_income"].value == 500


# ── prices must not lie about their currency ──────────────────────

@pytest.mark.parametrize("currency", ["GBP", "JPY", "EUR"])
def test_a_price_not_in_dollars_is_refused(monkeypatch, currency):
    """A London listing quotes in pence, so Shell comes back as 3356 and reads
    as $3,356 against a real price near $45. Both position sizing and the
    reverse DCF are ratios against this number."""
    from skills._lib.data.adapters import prices

    monkeypatch.setattr(prices, "get_json", lambda *a, **k: {
        "chart": {"result": [{"meta": {"regularMarketPrice": 3356.0,
                                       "regularMarketTime": 1786000000,
                                       "currency": currency}}]}})
    with pytest.raises(AdapterError) as excinfo:
        YahooAdapter().fetch("SHEL.L")
    assert currency in str(excinfo.value)


def test_a_dollar_price_records_its_currency(monkeypatch):
    from skills._lib.data.adapters import prices

    monkeypatch.setattr(prices, "get_json", lambda *a, **k: {
        "chart": {"result": [{"meta": {"regularMarketPrice": 219.15,
                                       "regularMarketTime": 1786000000,
                                       "currency": "USD"}}]}})
    assert YahooAdapter().fetch("NVDA")[0].currency == "USD"


def test_stooq_is_only_trusted_for_us_symbols(monkeypatch):
    """Stooq reports no currency, so a .de symbol would come back in euros
    labelled as dollars."""
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
            b"BMW.DE,2026-08-04,20:00:00,1,2,3,60.12,100\n"),
    )
    with pytest.raises(AdapterError) as excinfo:
        StooqAdapter().fetch("BMW.DE")
    assert "currency" in str(excinfo.value)

