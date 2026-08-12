"""The interactive valuation page.

Two properties matter and neither is cosmetic:

1. It must be genuinely self-contained. A page that quietly needs a CDN is a
   page that stops working the day you most want to re-read it.
2. Its JavaScript reimplements dcf.py so the reader can drag the assumptions.
   Two implementations of the same arithmetic drift. The last test here runs the
   page's own JS and compares it against Python, so a divergence fails the build
   rather than silently changing what the reader is shown.
"""

import json
import re
import shutil
import subprocess
from decimal import Decimal

import pytest

from airesearch.valuation import discounted_cash_flow, scenario_values
from airesearch.valuation.report import render


def _scenarios():
    return scenario_values(
        [
            {"name": "bull", "probability": 0.25, "growth_rate": "0.20",
             "assumptions": "networking attach holds"},
            {"name": "base", "probability": 0.50, "growth_rate": "0.10"},
            {"name": "bear", "probability": 0.25, "growth_rate": "0.00"},
        ],
        dict(owner_earnings=1000, growth_rate="0.10", discount_rate="0.10",
             terminal_growth="0.03", years=10, shares_outstanding=100),
    )


def _page(**overrides):
    kwargs = dict(
        ticker="NVDA",
        scenarios=_scenarios(),
        owner_earnings=1000,
        discount_rate=Decimal("0.10"),
        terminal_growth=Decimal("0.03"),
        years=10,
        shares_outstanding=100,
        discount_rate_source="US 10Y + 5% equity risk premium",
        market_price=150,
        currency="$",
        generated_at="2026-08-04",
    )
    kwargs.update(overrides)
    return render(**kwargs)


# ── self-containment ──────────────────────────────────────────────

def test_the_page_requests_nothing_from_the_network():
    page = _page()
    for pattern in ("http://", "https://", "//cdn", "fetch(", "XMLHttpRequest",
                    "<script src", "<link rel=\"stylesheet\""):
        assert pattern not in page, f"page reaches for {pattern!r}"


def test_the_page_is_a_complete_document():
    page = _page()
    assert page.startswith("<!doctype html>")
    assert "</html>" in page
    assert "<title>" in page


def test_the_page_carries_its_own_styles_and_script():
    page = _page()
    assert "<style>" in page and "</style>" in page
    assert "<script>" in page and "</script>" in page


def test_the_page_adapts_to_a_dark_reader():
    assert "prefers-color-scheme: dark" in _page()


def test_wide_content_scrolls_inside_its_own_container():
    assert "overflow-x: auto" in _page()


# ── content ───────────────────────────────────────────────────────

def test_the_ticker_and_provenance_appear():
    page = _page()
    assert "NVDA" in page
    assert "US 10Y + 5% equity risk premium" in page


def test_every_scenario_reaches_the_payload():
    payload = _payload(_page())
    assert [s["name"] for s in payload["scenarios"]] == ["bull", "base", "bear"]
    assert [s["probability"] for s in payload["scenarios"]] == [0.25, 0.50, 0.25]


def test_assumption_notes_travel_with_their_scenario():
    payload = _payload(_page())
    assert payload["scenarios"][0]["assumptions"] == "networking attach holds"


def test_decimals_survive_as_numbers_not_strings():
    """json.dumps cannot serialise Decimal, and a stringified rate would make
    the sliders start from the wrong place."""
    payload = _payload(_page())
    assert isinstance(payload["discountRate"], float)
    assert isinstance(payload["terminalGrowth"], float)
    assert payload["discountRate"] == 0.10


def test_a_missing_market_price_is_carried_as_null_not_zero():
    payload = _payload(_page(market_price=None))
    assert payload["marketPrice"] is None


def test_a_hostile_ticker_cannot_inject_markup():
    page = _page(ticker="<script>alert(1)</script>")
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;" in page


def test_the_language_attribute_follows_the_configured_output_language():
    assert '<html lang="zh-CN">' in _page(language="zh-CN")


def test_chinese_content_renders_without_escaping_damage():
    page = _page(scenarios=[{
        "name": "乐观", "probability": 1.0, "price_target": 200.0,
        "growth_rate": "0.15", "assumptions": "网络附加率维持",
    }])
    assert "乐观" in page
    assert "网络附加率维持" in page


def _payload(page: str) -> dict:
    match = re.search(r"const DATA = (\{.*?\});\n", page, flags=re.DOTALL)
    assert match, "the page does not embed its data payload"
    return json.loads(match.group(1))


# ── the two implementations must agree ────────────────────────────

_NODE = shutil.which("node")


@pytest.mark.skipif(_NODE is None, reason="node is not installed")
def test_the_pages_javascript_matches_the_python_arithmetic():
    """Runs the page's own dcf() against Python's for a grid of assumptions.

    Without this, the sliders can quietly compute something different from the
    numbers stored on the record, and the reader has no way to tell which one
    they are looking at.
    """
    page = _page()
    script = re.search(r"function project\(.*?^\}\n", page,
                       flags=re.DOTALL | re.MULTILINE)
    dcf_js = re.search(r"function dcf\(.*?\n\}\n", page, flags=re.DOTALL)
    assert script and dcf_js, "could not extract the page's DCF functions"

    cases = [
        (1000, 0.10, 0.10, 0.03, 10, 100),
        (1000, 0.20, 0.12, 0.02, 5, 100),
        (500, 0.00, 0.08, 0.00, 15, 50),
        (2500, -0.05, 0.15, 0.03, 10, 250),
        (100, 0.30, 0.09, 0.025, 3, 10),
    ]
    harness = (
        script.group(0) + dcf_js.group(0) +
        "const cases = " + json.dumps(cases) + ";\n"
        "console.log(JSON.stringify(cases.map("
        "([oe,g,r,tg,y,sh]) => dcf(oe,g,r,tg,y,sh).value)));"
    )
    out = subprocess.run([_NODE, "-e", harness], capture_output=True, text=True,
                         timeout=30)
    assert out.returncode == 0, out.stderr
    js_values = json.loads(out.stdout)

    for (oe, g, r, tg, years, shares), js_value in zip(cases, js_values):
        py = discounted_cash_flow(
            owner_earnings=oe, growth_rate=str(g), discount_rate=str(r),
            terminal_growth=str(tg), years=years, shares_outstanding=shares,
        )
        assert float(py.per_share) == pytest.approx(js_value, rel=1e-9), (
            f"python and the page disagree for oe={oe} g={g} r={r} "
            f"tg={tg} years={years}"
        )


@pytest.mark.skipif(_NODE is None, reason="node is not installed")
def test_the_pages_javascript_refuses_the_same_degenerate_spread():
    """Python raises when the discount rate barely exceeds terminal growth; the
    page must not silently draw a number there."""
    page = _page()
    dcf_js = re.search(r"function project\(.*?\n\}\n.*?function dcf\(.*?\n\}\n",
                       page, flags=re.DOTALL)
    harness = dcf_js.group(0) + "console.log(JSON.stringify(dcf(1000,0.1,0.0801,0.08,10,100)));"
    out = subprocess.run([_NODE, "-e", harness], capture_output=True, text=True,
                         timeout=30)
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout) is None


# ── the page must show the numbers it stored ──────────────────────

def _row_values(rows_html: str) -> list:
    """The value column of each rendered row, as numbers.

    Comparing formatted strings is brittle: the page uses toLocaleString, which
    varies its decimal places with magnitude.
    """
    cells = re.findall(r"<td>(.*?)</td>", rows_html)
    # Columns per row: name, growth, probability, value, vs price, terminal share.
    values = []
    for i in range(3, len(cells), 6):
        raw = re.sub(r"[^0-9.\-]", "", cells[i])
        values.append(float(raw) if raw not in ("", "-", ".") else None)
    return values


def _run_page(page: str, drag=None) -> dict:
    """Execute the page's own script against a stub DOM and read the result."""
    ids_setup = """
    const ids = {};
    const mk = () => ({textContent:'', innerHTML:'', value:'', hidden:false,
                       addEventListener(){}});
    global.document = { getElementById: (id) => ids[id] || (ids[id] = mk()) };
    """
    body = re.search(r"<script>\s*([\s\S]*?)</script>", page).group(1)
    drag_js = ""
    if drag:
        for key, value in drag.items():
            drag_js += f"ids['{key}'].value = '{value}';\n"
        drag_js += "onSlide();\n"
    harness = ids_setup + body + drag_js + """
    console.log(JSON.stringify({
      ev: ids.ev.textContent, implied: ids.implied.textContent,
      rows: ids.rows.innerHTML, state: ids.state.textContent,
      warn: ids.spreadWarn.hidden,
    }));
    """
    out = subprocess.run([_NODE, "-e", harness], capture_output=True, text=True,
                         timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


@pytest.mark.skipif(_NODE is None, reason="node is not installed")
def test_the_page_first_shows_the_stored_values_not_a_recomputation():
    """The page used to recompute every row from the global assumptions, so a
    scenario that overrode the discount rate was displayed at a completely
    different value from the one saved on the record."""
    scenarios = scenario_values(
        [
            {"name": "base", "probability": 0.5, "growth_rate": "0.10"},
            {"name": "bear", "probability": 0.5, "growth_rate": "0.10",
             "discount_rate": "0.20"},
        ],
        dict(owner_earnings=1000, growth_rate="0.10", discount_rate="0.10",
             terminal_growth="0.03", years=10, shares_outstanding=100),
    )
    stored = {s["name"]: s["price_target"] for s in scenarios}
    assert stored["bear"] < stored["base"] / 2, "fixture should differ materially"

    result = _run_page(_page(scenarios=scenarios))
    shown = _row_values(result["rows"])
    assert len(shown) == len(stored), result["rows"]
    for displayed, (name, value) in zip(shown, stored.items()):
        assert displayed == pytest.approx(value, rel=0.01), (
            f"{name} is stored at {value} but the page shows {displayed}"
        )


@pytest.mark.skipif(_NODE is None, reason="node is not installed")
def test_a_scenario_keeps_its_own_override_when_a_slider_moves():
    scenarios = scenario_values(
        [
            {"name": "base", "probability": 0.5, "growth_rate": "0.10"},
            {"name": "bear", "probability": 0.5, "growth_rate": "0.10",
             "discount_rate": "0.20"},
        ],
        dict(owner_earnings=1000, growth_rate="0.10", discount_rate="0.10",
             terminal_growth="0.03", years=10, shares_outstanding=100),
    )
    page = _page(scenarios=scenarios)
    dragged = _run_page(page, drag={"r": "12"})
    # base follows the slider to 12%; bear holds its own 20% and so stays lower.
    assert "own discount_rate" in dragged["rows"]
    assert dragged["state"].startswith("Recomputed")


@pytest.mark.skipif(_NODE is None, reason="node is not installed")
def test_the_page_says_whether_it_is_showing_stored_or_recomputed_figures():
    assert _run_page(_page())["state"] == "Showing the stored figures."


@pytest.mark.skipif(_NODE is None, reason="node is not installed")
def test_a_hostile_scenario_name_cannot_inject_markup():
    """Scenario names come from model-authored text, and the page opens from
    file://, so an injected tag runs with local-file privileges."""
    scenarios = scenario_values(
        [{"name": '<img src=x onerror="alert(1)">bull', "probability": 1.0,
          "growth_rate": "0.10"}],
        dict(owner_earnings=1000, growth_rate="0.10", discount_rate="0.10",
             terminal_growth="0.03", years=10, shares_outstanding=100),
    )
    rows = _run_page(_page(scenarios=scenarios))["rows"]
    assert "<img" not in rows
    assert "&lt;img" in rows


@pytest.mark.skipif(_NODE is None, reason="node is not installed")
def test_string_rates_do_not_become_string_concatenation():
    """Rates are documented as strings throughout this package. In JavaScript
    1 + "0.10" is "10.10", which drew a 915% growth year and then NaN."""
    page = _page(discount_rate="0.10", terminal_growth="0.03")
    result = _run_page(page, drag={"r": "10"})
    assert "NaN" not in result["rows"]
    assert "NaN" not in result["ev"]


def test_a_string_rate_is_coerced_to_a_number_in_the_payload():
    payload = _payload(_page(discount_rate="0.10", terminal_growth="0.03"))
    assert payload["discountRate"] == 0.10
    assert isinstance(payload["discountRate"], float)


def test_a_non_numeric_rate_is_rejected_rather_than_silently_drawn():
    with pytest.raises(ValueError):
        _page(discount_rate="ten percent")


def test_javascript_line_separators_are_escaped():
    page = _page(scenarios=[{
        "name": "base", "probability": 1.0, "price_target": 100.0,
        "assumptions": "line\u2028separator", "terminal_share": 0.5,
        "inputs": {"owner_earnings": 1000, "growth_rate": 0.1,
                   "discount_rate": 0.1, "terminal_growth": 0.03,
                   "years": 10, "shares_outstanding": 100},
        "overrides": [],
    }])
    script = page[page.index("const DATA = "):]
    assert "\u2028" not in script, "a raw line separator reached the script body"
    assert "\\u2028" in script, "the separator was dropped rather than escaped"
