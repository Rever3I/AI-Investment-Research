#!/usr/bin/env python
"""Chinese listings from Eastmoney's public JSON endpoints.

This is what makes `cn_equity` usable without a licence. Wind remains in the
chain behind it, but Wind ships only with a paid terminal, so an adapter that
needs one leaves the domain unreachable for everyone who does not have it.

Unofficial and undocumented, like the Yahoo endpoint the price chain already
depends on. It is documented as such rather than dressed up: the shape can
change, and the parser fails loudly with an explanation instead of returning
something plausible.

Three ways reading these reports naively produces a wrong number, each found by
running against live data and each now blocked:

* **Depreciation is spread across six fields**, and which ones a company reports
  varies. Kweichow Moutai files five; Gree files two. Summing only the obvious
  `*_AMORTIZE` ones gives Moutai CNY 366m against a real CNY 4.15bn — eleven
  times too small, and still an entirely plausible depreciation figure.
* **Two share counts disagree.** The quote endpoint reports shares outstanding
  now; the balance sheet reports registered capital at the year end. For Moutai
  that is 1.250bn against 1.252bn, a buyback apart. Neither is wrong; using the
  year-end one for a per-share figure dated today is.
* **Registered capital is not a share count** unless par value is CNY 1. It
  usually is, which is what makes the exception dangerous, so the fallback is
  cross-checked against net income over basic EPS before it is trusted.

Banks and insurers file a different report series entirely and return nothing
here. That refusal is correct — owner earnings does not apply to them — but it
is stated as the reason rather than left as an empty response.
"""

import logging
from datetime import datetime, timedelta, timezone

from .base import Adapter, AdapterError, as_fact
from .http import get_json

_log = logging.getLogger(__name__)

SOURCE = "eastmoney"
DOMAIN = "cn_equity"

_DATACENTER = (
    "https://datacenter-web.eastmoney.com/api/data/v1/get"
    "?reportName={report}&columns=ALL"
    "&filter=(SECUCODE%3D%22{code}%22)(REPORT_TYPE%3D%22%E5%B9%B4%E6%8A%A5%22)"
    "&pageSize=1&sortColumns=REPORT_DATE&sortTypes=-1"
)
_QUOTE = ("https://push2.eastmoney.com/api/qt/stock/get"
          "?secid={secid}&fields=f57,f58,f84,f43")

_HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://data.eastmoney.com/"}

_CASHFLOW = "RPT_F10_FINANCE_GCASHFLOW"
_INCOME = "RPT_F10_FINANCE_GINCOME"
_BALANCE = "RPT_F10_FINANCE_GBALANCE"

# Every depreciation and amortisation line in the cash flow statement's
# reconciliation. Absent fields come back as null rather than being omitted.
_DA_FIELDS = (
    "FA_IR_DEPR",              # 固定资产及投资性房地产折旧 — the large one
    "OILGAS_BIOLOGY_DEPR",     # 油气资产折耗、生产性生物资产折旧
    "IA_AMORTIZE",             # 无形资产摊销
    "LPE_AMORTIZE",            # 长期待摊费用摊销
    "USERIGHT_ASSET_AMORTIZE", # 使用权资产摊销
)
# Without this one a sum of the others understates D&A by an order of magnitude
# while still looking like a depreciation figure.
_DA_REQUIRED = "FA_IR_DEPR"

# An annual report more than this old means the company stopped filing, was
# delisted, or the endpoint is serving something stale.
_MAX_AGE_DAYS = 500

# Registered capital divided by a CNY 1 par value should land near the share
# count implied by net income over basic EPS. A par value of CNY 0.1 puts them
# a factor of ten apart; a buyback or a weighted average puts them a few percent
# apart, so the gate has to sit well between those.
_SHARE_CROSSCHECK_TOLERANCE = 0.25
_MIN_PLAUSIBLE_SHARES = 1_000_000


class EastmoneyAdapter(Adapter):
    """Owner-earnings inputs for an A-share, from public endpoints.

    Needs no key and no licence, which is the point.
    """

    def __init__(self, db_path=None):
        super().__init__(name=SOURCE, domain=DOMAIN)
        self.db_path = db_path

    # ── code handling ─────────────────────────────────────────────

    @staticmethod
    def _split(key: str):
        """Normalise a code to (SECUCODE, secid).

        Users arrive with whatever their broker or data source calls it:
        `600519`, `600519.SH`, `600519.SS` (Yahoo's suffix), `sh600519`.
        """
        raw = str(key).strip().upper().replace(" ", "")
        for prefix in ("SH", "SZ", "BJ"):
            if raw.startswith(prefix) and raw[2:].isdigit():
                raw = f"{raw[2:]}.{prefix}"
                break
        digits, _, suffix = raw.partition(".")
        if not digits.isdigit() or len(digits) != 6:
            raise AdapterError(
                f"{key!r} is not an A-share code. Expected six digits, "
                f"optionally with an exchange suffix, e.g. '600519.SH'."
            )
        # Yahoo writes Shanghai as .SS and Shenzhen as .SZ; Eastmoney wants .SH.
        exchange = {"SS": "SH", "SH": "SH", "SZ": "SZ", "BJ": "BJ"}.get(suffix)
        if exchange is None:
            exchange = _exchange_from_number(digits)
        # Eastmoney's secid prefixes: 1 for Shanghai, 0 for Shenzhen and Beijing.
        secid = f"{'1' if exchange == 'SH' else '0'}.{digits}"
        return f"{digits}.{exchange}", secid

    # ── fetching ──────────────────────────────────────────────────

    def _report(self, report: str, secucode: str):
        payload = get_json(_DATACENTER.format(report=report, code=secucode),
                           headers=_HEADERS)
        result = payload.get("result") if isinstance(payload, dict) else None
        rows = (result or {}).get("data") or []
        return rows[0] if rows else None

    def fetch(self, key: str, **kwargs) -> list:
        secucode, secid = self._split(key)

        cashflow = self._report(_CASHFLOW, secucode)
        income = self._report(_INCOME, secucode)
        if not cashflow or not income:
            raise AdapterError(
                f"Eastmoney returned no annual general-industry report for "
                f"{secucode}. Banks, insurers and brokers file a different "
                f"report series, and owner earnings does not apply to them "
                f"anyway — net income plus depreciation less capital "
                f"expenditure describes a business that buys equipment."
            )

        as_of = _report_date(cashflow, secucode)
        currency = (cashflow.get("CURRENCY") or "CNY").upper()
        if currency != "CNY":
            raise AdapterError(
                f"{secucode} reports in {currency}, and nothing here converts "
                f"between currencies. Supply the figures directly instead."
            )

        net_income = _number(income.get("PARENT_NETPROFIT"))
        capex = _number(cashflow.get("CONSTRUCT_LONG_ASSET"))
        depreciation = _depreciation(cashflow, secucode)
        shares = self._shares(secid, secucode, income)

        missing = [name for name, value in (
            ("net income (PARENT_NETPROFIT)", net_income),
            ("capital expenditure (CONSTRUCT_LONG_ASSET)", capex),
        ) if value is None]
        if missing:
            raise AdapterError(
                f"{secucode}'s annual report is missing {', '.join(missing)}. "
                f"Owner earnings needs every term; a missing one read as zero "
                f"flatters the company by exactly the amount that is absent."
            )

        return [
            self._fact(f"{secucode}_net_income", net_income, "usd", as_of,
                       secucode, currency, "eastmoney:PARENT_NETPROFIT"),
            self._fact(f"{secucode}_depreciation_amortisation", depreciation[0],
                       "usd", as_of, secucode, currency,
                       f"eastmoney:{'+'.join(depreciation[1])}"),
            self._fact(f"{secucode}_capital_expenditure", capex, "usd", as_of,
                       secucode, currency, "eastmoney:CONSTRUCT_LONG_ASSET"),
            self._fact(f"{secucode}_shares_outstanding", shares[0], "shares",
                       as_of, secucode, "", f"eastmoney:{shares[1]}"),
        ]

    def _fact(self, name, value, unit, as_of, entity, currency, note):
        return as_fact(name=name, value=value, unit=unit, freq="annual",
                       as_of=as_of, source=SOURCE, entity=entity,
                       group="owner_earnings", currency=currency, note=note)

    # ── share count ───────────────────────────────────────────────

    def _shares(self, secid: str, secucode: str, income: dict):
        """Shares outstanding now, or registered capital if that is all there is.

        Returns (value, provenance). The quote endpoint is preferred because it
        is the count as of today, which is what a per-share figure quoted today
        needs. It is also the flakier of the two, so the balance sheet stands
        behind it — under a cross-check, because registered capital is only a
        share count when par value is CNY 1.
        """
        implied = _implied_shares(income)

        try:
            payload = get_json(_QUOTE.format(secid=secid), headers=_HEADERS)
            live = _number((payload.get("data") or {}).get("f84"))
        except Exception as exc:                      # noqa: BLE001 - fall through
            _log.warning("Eastmoney quote endpoint did not answer for %s (%s); "
                         "falling back to registered capital", secucode, exc)
            live = None

        if live and live >= _MIN_PLAUSIBLE_SHARES:
            return live, "f84 shares outstanding"

        # Tencent publishes market capitalisation and price, and their ratio is
        # the count now. Preferred over the balance sheet because the balance
        # sheet's is the count at the last year end, and it answered every time
        # Eastmoney's quote endpoint was returning 502.
        from .cn_tencent import shares_outstanding  # noqa: PLC0415 - optional path

        derived = shares_outstanding(secucode)
        if derived and derived >= _MIN_PLAUSIBLE_SHARES:
            return derived, "tencent market cap over price"

        balance = self._report(_BALANCE, secucode) or {}
        registered = _number(balance.get("SHARE_CAPITAL"))
        if not registered or registered < _MIN_PLAUSIBLE_SHARES:
            raise AdapterError(
                f"No usable share count for {secucode}: the quote endpoint did "
                f"not answer and the balance sheet has no registered capital. "
                f"Every per-share figure divides by this number."
            )
        if implied and abs(registered - implied) / implied > _SHARE_CROSSCHECK_TOLERANCE:
            raise AdapterError(
                f"{secucode}'s registered capital ({registered:,.0f}) is "
                f"{registered / implied:.1f}x the share count its own net income "
                f"and basic EPS imply ({implied:,.0f}). Registered capital is a "
                f"share count only at a par value of CNY 1, so this is most "
                f"likely a different par value rather than a share count."
            )
        return registered, "SHARE_CAPITAL at the year end"


# ── helpers ───────────────────────────────────────────────────────

def _exchange_from_number(digits: str) -> str:
    """Which exchange a bare six-digit code belongs to.

    Shanghai issues 60/68/9-prefixed codes, Beijing 43/83/87/88/92, and
    Shenzhen the rest. Guessing wrong returns another company's filings, so an
    unrecognised prefix is refused rather than defaulted.
    """
    if digits[:2] in ("60", "68") or digits[0] == "9":
        return "SH"
    if digits[:2] in ("43", "83", "87", "88", "92"):
        return "BJ"
    if digits[:2] in ("00", "30", "20"):
        return "SZ"
    raise AdapterError(
        f"Cannot tell which exchange {digits} is listed on. Add the suffix, "
        f"e.g. '{digits}.SH' or '{digits}.SZ'."
    )


def _number(value):
    """A float, or None. Eastmoney sends absent fields as null, and occasionally
    as a string."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _depreciation(cashflow: dict, secucode: str):
    """Total D&A, and which fields it came from.

    Every present field is summed. `FA_IR_DEPR` has to be one of them: it is
    usually most of the total, and a sum without it is wrong by roughly an order
    of magnitude while still reading as an ordinary depreciation figure.
    """
    present = {name: _number(cashflow.get(name)) for name in _DA_FIELDS}
    present = {name: value for name, value in present.items() if value is not None}
    if _DA_REQUIRED not in present:
        raise AdapterError(
            f"{secucode}'s annual report does not carry {_DA_REQUIRED}, the "
            f"fixed-asset depreciation line. The remaining amortisation fields "
            f"{sorted(present) or '(none)'} would sum to a figure that looks "
            f"like depreciation and is a fraction of it, so this is refused "
            f"rather than reported."
        )
    return sum(present.values()), sorted(present)


def _implied_shares(income: dict):
    """Share count implied by net income over basic EPS, for cross-checking.

    A weighted average rather than a point-in-time count, so it is close but
    never exact — useful for catching a factor of ten, not a buyback.
    """
    net_income = _number(income.get("PARENT_NETPROFIT"))
    eps = _number(income.get("BASIC_EPS"))
    if not net_income or not eps:
        return None
    return abs(net_income / eps)


def _report_date(row: dict, secucode: str) -> str:
    """The period the report describes, as UTC ISO 8601.

    Eastmoney sends "2025-12-31 00:00:00" with no zone. Read as the report date
    it is, and refused past an age limit so a delisted company's last filing
    cannot arrive looking current.
    """
    raw = str(row.get("REPORT_DATE") or "").strip()
    try:
        stamp = datetime.strptime(raw[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise AdapterError(
            f"Eastmoney returned an unreadable report date {raw!r} for "
            f"{secucode}. The endpoint is unofficial and its shape can change."
        ) from exc
    if datetime.now(timezone.utc) - stamp > timedelta(days=_MAX_AGE_DAYS):
        raise AdapterError(
            f"{secucode}'s most recent annual report is dated {raw[:10]}, more "
            f"than {_MAX_AGE_DAYS} days ago. The company may have stopped "
            f"filing or been delisted; it is not current financial data."
        )
    return stamp.isoformat()
