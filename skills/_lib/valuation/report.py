#!/usr/bin/env python
"""A self-contained interactive valuation page.

Everything is inlined — no CDN, no fonts, no fetch. The file opens from disk on
a machine with no network and still works, because a valuation you cannot open
in two years is not a record of anything.

The page recomputes in the browser as the reader drags the assumptions. That is
the point: a DCF's output is less interesting than its sensitivity, and a static
number invites the reader to accept it rather than push on it. The JavaScript
mirrors dcf.py's arithmetic, and a test checks the two agree so the page cannot
quietly drift from the figures that were stored.
"""

import html
import json
from decimal import Decimal


def _num(value):
    """JSON cannot carry Decimal; the page works in float, the record does not."""
    return float(value) if isinstance(value, Decimal) else value


def _embed(payload: dict) -> str:
    """Serialise the payload for embedding inside a <script> block.

    `<` is escaped because a `</script>` sequence anywhere in the data — a
    ticker, an assumption note, a thesis quote — terminates the script element
    early and drops the rest of the page into the document as markup. Escaping
    it as \\u003c is invisible to JSON.parse and to the reader.

    ensure_ascii=False so CJK stays readable in the file itself, matching how
    the store writes its JSON columns.
    """
    return json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c")


def render(
    *,
    ticker: str,
    scenarios: list,
    owner_earnings,
    discount_rate,
    terminal_growth,
    years: int,
    shares_outstanding=None,
    discount_rate_source: str = "",
    market_price=None,
    implied_growth=None,
    currency: str = "",
    generated_at: str = "",
    language: str = "en",
) -> str:
    """Return a complete HTML document for one valuation."""
    payload = {
        "ticker": ticker,
        "ownerEarnings": _num(owner_earnings),
        "discountRate": _num(discount_rate),
        "terminalGrowth": _num(terminal_growth),
        "years": int(years),
        "shares": _num(shares_outstanding),
        "scenarios": [
            {
                "name": s["name"],
                "probability": _num(s["probability"]),
                "priceTarget": _num(s["price_target"]),
                "growthRate": _num(s.get("growth_rate", "")) if s.get("growth_rate") not in (None, "") else None,
                "assumptions": s.get("assumptions", ""),
                "terminalShare": _num(s.get("terminal_share")) if s.get("terminal_share") is not None else None,
            }
            for s in scenarios
        ],
        "marketPrice": _num(market_price),
        "impliedGrowth": _num(implied_growth),
        "currency": currency,
    }

    esc = html.escape
    title = f"{esc(ticker)} valuation"
    meta_bits = []
    if discount_rate_source:
        meta_bits.append(f"Discount rate: {esc(discount_rate_source)}")
    if generated_at:
        meta_bits.append(f"Generated {esc(generated_at)}")
    meta = " &middot; ".join(meta_bits)

    return _TEMPLATE.format(
        lang=esc(language),
        title=title,
        ticker=esc(ticker),
        meta=meta,
        payload=_embed(payload),
    )


_TEMPLATE = """<!doctype html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  :root {{
    color-scheme: light dark;
    --bg: #ffffff; --fg: #16181d; --muted: #5c6370;
    --line: #e3e6ea; --panel: #f7f8fa; --accent: #2f6feb;
    --bull: #1a7f4b; --bear: #b4362f;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --bg: #14161a; --fg: #e6e8ec; --muted: #9aa1ad;
      --line: #2a2e36; --panel: #1b1e24; --accent: #6b9bff;
      --bull: #4ec98a; --bear: #ef7d75;
    }}
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; padding: 2rem 1.25rem 4rem;
    background: var(--bg); color: var(--fg);
    font: 16px/1.6 -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans SC", sans-serif;
  }}
  main {{ max-width: 60rem; margin: 0 auto; }}
  h1 {{ font-size: 1.6rem; margin: 0 0 .25rem; letter-spacing: -.01em; }}
  .meta {{ color: var(--muted); font-size: .85rem; margin-bottom: 2rem; }}
  h2 {{ font-size: 1rem; text-transform: uppercase; letter-spacing: .08em;
       color: var(--muted); margin: 2.5rem 0 .75rem; font-weight: 600; }}
  .headline {{
    display: flex; flex-wrap: wrap; gap: 2rem;
    padding: 1.25rem; background: var(--panel);
    border: 1px solid var(--line); border-radius: 10px;
  }}
  .stat .label {{ font-size: .8rem; color: var(--muted); }}
  .stat .value {{ font-size: 1.5rem; font-variant-numeric: tabular-nums; }}
  .controls {{ display: grid; gap: 1.1rem; }}
  .control label {{ display: flex; justify-content: space-between;
                    font-size: .9rem; margin-bottom: .3rem; }}
  .control output {{ font-variant-numeric: tabular-nums; color: var(--accent); }}
  input[type=range] {{ width: 100%; accent-color: var(--accent); }}
  .scroll {{ overflow-x: auto; }}
  table {{ border-collapse: collapse; width: 100%; min-width: 34rem; }}
  th, td {{ text-align: right; padding: .55rem .7rem;
            border-bottom: 1px solid var(--line); font-variant-numeric: tabular-nums; }}
  th:first-child, td:first-child {{ text-align: left; }}
  thead th {{ font-size: .8rem; color: var(--muted); font-weight: 600; }}
  tr.bull td:first-child {{ color: var(--bull); }}
  tr.bear td:first-child {{ color: var(--bear); }}
  .note {{ color: var(--muted); font-size: .85rem; max-width: 44rem; }}
  .warn {{ color: var(--bear); font-size: .85rem; }}
</style>
</head>
<body>
<main>
  <h1>{ticker}</h1>
  <p class="meta">{meta}</p>

  <div class="headline">
    <div class="stat"><div class="label">Expected value</div>
      <div class="value" id="ev">—</div></div>
    <div class="stat"><div class="label">Market price</div>
      <div class="value" id="px">—</div></div>
    <div class="stat"><div class="label">Growth the price implies</div>
      <div class="value" id="implied">—</div></div>
  </div>

  <h2>Assumptions</h2>
  <div class="controls">
    <div class="control">
      <label for="r">Discount rate <output id="rOut"></output></label>
      <input type="range" id="r" min="1" max="25" step="0.25">
    </div>
    <div class="control">
      <label for="tg">Terminal growth <output id="tgOut"></output></label>
      <input type="range" id="tg" min="-2" max="6" step="0.25">
    </div>
    <div class="control">
      <label for="yr">Projection years <output id="yrOut"></output></label>
      <input type="range" id="yr" min="3" max="20" step="1">
    </div>
  </div>
  <p class="warn" id="spreadWarn" hidden>
    Terminal growth is too close to the discount rate. Below a half-point spread
    the terminal value dominates arithmetically and the result stops meaning anything.
  </p>

  <h2>Scenarios</h2>
  <div class="scroll">
    <table>
      <thead><tr>
        <th>Scenario</th><th>Growth</th><th>Probability</th>
        <th>Value</th><th>vs price</th><th>Terminal share</th>
      </tr></thead>
      <tbody id="rows"></tbody>
    </table>
  </div>
  <p class="note" id="assumptionNotes"></p>

  <p class="note">
    Values recompute from the sliders; the stored record holds the figures as
    they were when this was generated. Terminal share is how much of the value
    sits in the perpetuity assumption rather than the projected years — a
    valuation that is mostly terminal value is a statement about the discount
    rate, not about the business.
  </p>
</main>

<script>
const DATA = {payload};

// Mirrors skills/_lib/valuation/dcf.py. A test computes both and compares, so
// this cannot drift from the arithmetic that produced the stored numbers.
function project(oe, g, years, terminalG) {{
  const out = [];
  let current = oe;
  for (let year = 1; year <= years; year++) {{
    const weight = years === 1 ? 0 : (year - 1) / (years - 1);
    const rate = g + (terminalG - g) * weight;
    current = current * (1 + rate);
    out.push(current);
  }}
  return out;
}}

function dcf(oe, g, r, terminalG, years, shares) {{
  if (r - terminalG < 0.005) return null;
  const series = project(oe, g, years, terminalG);
  let pv = 0;
  series.forEach((cash, i) => {{ pv += cash / Math.pow(1 + r, i + 1); }});
  const terminal = series[series.length - 1] * (1 + terminalG) / (r - terminalG);
  const terminalPv = terminal / Math.pow(1 + r, years);
  pv += terminalPv;
  return {{ value: shares ? pv / shares : pv, terminalShare: terminalPv / pv }};
}}

function impliedGrowth(target, oe, r, terminalG, years, shares) {{
  let low = -0.5, high = 1.0;
  const at = (g) => {{ const d = dcf(oe, g, r, terminalG, years, shares); return d && d.value; }};
  if (!(at(low) <= target && at(high) >= target)) return null;
  for (let i = 0; i < 200; i++) {{
    const mid = (low + high) / 2;
    const v = at(mid);
    if (Math.abs(v - target) <= Math.abs(target) * 0.0001) return mid;
    if (v < target) low = mid; else high = mid;
  }}
  return (low + high) / 2;
}}

const fmt = (n) => n === null || n === undefined || !isFinite(n) ? "—"
  : (DATA.currency ? DATA.currency + " " : "") + n.toLocaleString(undefined,
      {{ maximumFractionDigits: n >= 100 ? 0 : 2 }});
const pct = (n) => n === null || n === undefined || !isFinite(n) ? "—"
  : (n * 100).toFixed(1) + "%";

const els = {{
  r: document.getElementById("r"), tg: document.getElementById("tg"),
  yr: document.getElementById("yr"),
  rOut: document.getElementById("rOut"), tgOut: document.getElementById("tgOut"),
  yrOut: document.getElementById("yrOut"),
  rows: document.getElementById("rows"), ev: document.getElementById("ev"),
  px: document.getElementById("px"), implied: document.getElementById("implied"),
  warn: document.getElementById("spreadWarn"),
  notes: document.getElementById("assumptionNotes"),
}};

els.r.value = (DATA.discountRate * 100).toFixed(2);
els.tg.value = (DATA.terminalGrowth * 100).toFixed(2);
els.yr.value = DATA.years;

function redraw() {{
  const r = parseFloat(els.r.value) / 100;
  const tg = parseFloat(els.tg.value) / 100;
  const years = parseInt(els.yr.value, 10);
  els.rOut.textContent = (r * 100).toFixed(2) + "%";
  els.tgOut.textContent = (tg * 100).toFixed(2) + "%";
  els.yrOut.textContent = years;
  els.warn.hidden = (r - tg) >= 0.005;

  let ev = 0, rows = "";
  DATA.scenarios.forEach((s) => {{
    const g = s.growthRate === null ? null : s.growthRate;
    const d = g === null ? null
      : dcf(DATA.ownerEarnings, g, r, tg, years, DATA.shares);
    const value = d ? d.value : null;
    if (value !== null) ev += value * s.probability;
    const cls = /bull|upside/i.test(s.name) ? "bull"
      : /bear|downside/i.test(s.name) ? "bear" : "";
    const vsPrice = (value !== null && DATA.marketPrice)
      ? ((value / DATA.marketPrice - 1) * 100).toFixed(0) + "%" : "—";
    rows += `<tr class="${{cls}}"><td>${{s.name}}</td><td>${{pct(g)}}</td>` +
            `<td>${{pct(s.probability)}}</td><td>${{fmt(value)}}</td>` +
            `<td>${{vsPrice}}</td><td>${{d ? pct(d.terminalShare) : "—"}}</td></tr>`;
  }});
  els.rows.innerHTML = rows;
  els.ev.textContent = fmt(ev || null);
  els.px.textContent = fmt(DATA.marketPrice);

  const implied = DATA.marketPrice
    ? impliedGrowth(DATA.marketPrice, DATA.ownerEarnings, r, tg, years, DATA.shares)
    : null;
  els.implied.textContent = implied === null ? "—" : pct(implied);

  const notes = DATA.scenarios.filter((s) => s.assumptions)
    .map((s) => s.name + ": " + s.assumptions).join(" · ");
  els.notes.textContent = notes;
}}

[els.r, els.tg, els.yr].forEach((el) => el.addEventListener("input", redraw));
redraw();
</script>
</body>
</html>
"""
